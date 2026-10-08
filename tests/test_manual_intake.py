"""Offline contracts for explicit imports and normal application decisions."""
import copy
import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import quote
from urllib.request import Request, urlopen
from operation1million import manual_intake as intake, applications, jsearch, review


def empty():
    return {name: [] for name in ('pending', 'backlog', 'applied', 'skipped')}


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / 'decisions.ndjson'

    def test_jobmesh_blocked(self):
        rules = jsearch.load_plan()[0]['filter']
        self.assertTrue(jsearch.publisher_excluded('https://jobmesh.io/jobs/123', {}, rules))

    def test_structured_posting_and_score(self):
        record = {'@type': 'JobPosting', 'title': 'RTL Design Engineer',
                  'hiringOrganization': {'name': 'Example'}, 'identifier': {'value': 'R1'},
                  'description': '<p>SystemVerilog ASIC synthesis</p>'}
        metadata = intake.posting_metadata('<script type="application/ld+json">' + json.dumps(record) + '</script>', {})
        group = intake.create_group('https://company.example/R1', metadata)
        self.assertGreater(group['confidence'], 0)
        self.assertEqual(group['jobs'][0]['source_job_id'], 'R1')

    def test_explicit_import_survives_filters_rebuild_and_applied_decision(self):
        metadata = intake.posting_metadata('', {'title': 'Sales Manager', 'company': 'Example'})
        group = intake.create_group('https://company.example/R1', metadata)
        intake.save_manual(self.ledger, group)
        self.assertEqual(intake.augment_queue(empty(), self.ledger)['pending'][0]['id'], group['id'])
        applications.append_decision(self.ledger, group, 'applied', 'already applied')
        restored = intake.augment_queue(empty(), self.ledger)
        self.assertFalse(restored['pending'])
        self.assertEqual(restored['applied'][0]['id'], group['id'])

    def test_no_title_only_deduplication(self):
        group = intake.create_group('https://company.example/one', intake.posting_metadata('', {'title': 'Engineer', 'company': 'Example'}))
        state = empty(); state['pending'].append(group)
        self.assertIsNone(intake.match_group(state, 'https://company.example/two', {'title': 'Engineer', 'company': 'Example'})[1])
        self.assertEqual(intake.match_group(state, 'https://company.example/one#tracking')[1]['id'], group['id'])

    def test_replacement_preserves_provenance_and_removes_duplicate(self):
        old = intake.create_group('https://third.example/1', intake.posting_metadata('', {'title': 'Engineer', 'company': 'Example'}))
        new = intake.create_group('https://company.example/1', intake.posting_metadata('', {'title': 'Engineer', 'company': 'Example'}))
        intake.save_manual(self.ledger, new, [old['id']], [old])
        state = empty(); state['pending'].append(old)
        self.assertEqual([g['id'] for g in intake.augment_queue(state, self.ledger)['pending']], [new['id']])
        self.assertEqual(json.loads(intake.path_for(self.ledger).read_text())['replaced_groups'][0]['id'], old['id'])

    def test_private_network_refused(self):
        with patch.object(intake.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError): intake.public_url('https://localhost/job')

    def test_http_manual_add_and_applied_match_do_not_fetch(self):
        with patch.object(review.applications, 'queue', side_effect=lambda *args: empty()), patch.object(intake, 'read_public_page') as fetch:
            server = review.make_server(Path(self.temp.name)/'missing.sqlite', self.ledger, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                token = json.load(urlopen(base+'/api/queue'))['token']
                def post(data):
                    return json.load(urlopen(Request(base+'/api/manual', data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'X-Review-Token': token})))
                added = post({'url': 'https://company.example/1', 'company': 'Example', 'title': 'RTL Engineer'})
                marked = post({'url': 'https://company.example/1', 'status': 'applied'})
                self.assertEqual(marked['id'], added['id'])
                self.assertFalse(marked['created'])
                state = json.load(urlopen(base+'/api/queue'))
                self.assertEqual(len(state['applied']), 1)
                self.assertFalse(state['pending'])
                description = json.load(urlopen(base+'/api/job?id='+added['id']+'&url=https://company.example/1'))
                self.assertEqual(description['description'], '')
                fetch.assert_not_called()
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_http_company_link_replaces_matching_third_party(self):
        old = intake.create_group('https://third.example/1', intake.posting_metadata('', {'title': 'RTL Engineer', 'company': 'Example', 'source_job_id': 'R1'}))
        old['jobs'][0]['provider_key'] = 'jsearch'
        fixture = empty(); fixture['pending'].append(old)
        with patch.object(review.applications, 'queue', side_effect=lambda *args: copy.deepcopy(fixture)):
            server = review.make_server(Path(self.temp.name)/'missing.sqlite', self.ledger, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                token = json.load(urlopen(base+'/api/queue'))['token']
                data = {'url': 'https://company.example/R1', 'company': 'Example', 'title': 'RTL Engineer', 'source_job_id': 'R1', 'official': True}
                written = json.load(urlopen(Request(base+'/api/manual', data=json.dumps(data).encode(), headers={'X-Review-Token': token})))
                self.assertTrue(written['replaced'])
                state = json.load(urlopen(base+'/api/queue'))
                self.assertEqual([g['id'] for g in state['pending']], [written['id']])
                rebuilt = intake.augment_queue(copy.deepcopy(fixture), self.ledger)
                self.assertEqual([g['id'] for g in rebuilt['pending']], [written['id']])
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_access_refusal_persists_cooldown_and_prevents_next_fetch(self):
        session = MagicMock()
        session.__enter__.return_value = session
        response = MagicMock(status_code=403, headers={})
        response.__enter__.return_value = response
        session.get.return_value = response
        with patch.object(intake, 'public_url', side_effect=lambda url: url), \
             patch.object(intake.requests, 'Session', return_value=session), \
             patch.object(intake, 'collection_slot', side_effect=lambda _ledger: nullcontext()), \
             patch.object(intake.collection_policy, 'STATE', Path(self.temp.name)/'absent.sqlite'), \
             patch.object(intake.collection_policy, 'request_interval', return_value=0):
            with self.assertRaises(intake.collection_policy.SourcePaused):
                intake.read_public_page('https://company.example/job', self.ledger)
            with self.assertRaises(intake.collection_policy.SourcePaused):
                intake.read_public_page('https://company.example/job', self.ledger)
        self.assertEqual(session.get.call_count, 1)
        self.assertTrue(self.ledger.with_name('source_access.sqlite').exists())

    def test_cold_queue_returns_preparing_instead_of_waiting_on_build(self):
        from urllib.error import HTTPError
        entered, release = threading.Event(), threading.Event()
        def build(*args):
            entered.set(); release.wait(5); return empty()
        with patch.object(review.applications, 'queue', side_effect=build):
            server = review.make_server(Path(self.temp.name)/'missing.sqlite', self.ledger, port=0)
            serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
            warming = threading.Thread(target=server.current_queue); warming.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(HTTPError) as caught:
                    urlopen(f'http://127.0.0.1:{server.server_port}/api/queue', timeout=1)
                self.assertEqual(caught.exception.code, 503)
                self.assertIn('Preparing', caught.exception.read().decode())
            finally:
                release.set(); warming.join(); server.shutdown(); server.server_close(); serving.join()


class ImportedPostingTests(unittest.TestCase):
    """An imported entry is shown with the index's copy of its posting (2026-10-08).

    Muse's submissions were imported as `https://muse.invalid/<company>/<req>`
    with no description, so Review showed Renesas req 20032940 with neither
    text nor a working link, while the index held the posting as jid-7004.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / 'decisions.ndjson'
        self.db = Path(self.temp.name) / 'index.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript(
                'CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);'
                'CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, provider_key TEXT, title TEXT,'
                ' location TEXT, source_job_id TEXT, posted_at TEXT, first_seen TEXT, closed_at TEXT, raw TEXT);')
            db.executemany('INSERT INTO companies VALUES (?, ?)', [('renesas', 'Renesas'), ('kla', 'KLA')])

    def posting(self, url, company_key, title, place, requisition=None):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)',
                       (url, company_key, 'html', title, place, requisition,
                        '2026-09-24T11:40:46+00:00', json.dumps({'description': 'Debug SystemVerilog'})))
        return url

    def applied(self, company, title, place, requisition):
        url = f'https://muse.invalid/{company.casefold()}/{requisition}'
        group = intake.create_group(url, {'title': title, 'company': company, 'location': place,
                                          'source_job_id': requisition, 'description': ''})
        intake.save_manual(self.ledger, group)
        applications.append_decision(self.ledger, group, 'applied', 'Applied by Muse')
        return group

    def shown(self, group):
        state = intake.augment_queue(empty(), self.ledger, self.db)
        return next(item for item in state['applied'] if item['id'] == group['id'])

    def test_renesas_entry_shows_the_index_posting_of_its_title_and_city(self):
        group = self.applied('Renesas', 'Electrical Engineer', 'Austin, TX', '20032940')
        real = self.posting('https://jobs.renesas.com/job/electrical-engineer-in-austin-texas-united-states-jid-7004',
                            'renesas', 'Electrical Engineer', 'Austin, TEXAS, United States', '7004')
        self.posting('https://jobs.renesas.com/job/electrical-engineer-in-san-jose-jid-7005',
                     'renesas', 'Electrical Engineer', 'San Jose, CALIFORNIA, United States', '7005')
        shown = self.shown(group)
        self.assertEqual([job['url'] for job in shown['jobs']], [real, group['jobs'][0]['url']])
        self.assertEqual(shown['jobs'][0]['matched'], 'title and place')
        self.assertFalse(shown['jobs'][0].get('manual_import'))

    def test_a_requisition_picks_one_of_several_postings_of_one_title(self):
        group = self.applied('KLA', 'Sr. Electrical Engineer', 'Milpitas, CA', '2641848')
        for number in ('2636363', '2641848', '2641850'):
            self.posting(f'https://kla.wd1.myworkdayjobs.com/Search/job/Milpitas-CA/Sr-Electrical-Engineer_{number}',
                         'kla', 'Sr. Electrical Engineer', 'Milpitas, CA', number)
        shown = self.shown(group)
        self.assertTrue(shown['jobs'][0]['url'].endswith('_2641848'))
        self.assertEqual(shown['jobs'][0]['matched'], 'requisition')

    def test_a_board_number_inside_the_requisition_is_that_posting(self):
        group = self.applied('KLA', 'Photonics Design Co-Op', 'San Jose CA', '2026-91633')
        real = self.posting('https://kla.example/careers/jobs/91633', 'kla', 'Masters Photonics Co-Op',
                            'San Jose, California', '91633')
        self.assertEqual(self.shown(group)['jobs'][0]['url'], real)

    def test_one_posting_taken_by_two_requisitions_goes_to_neither(self):
        first = self.applied('KLA', 'Applications Engineer', 'Sunnyvale, CA', '18811')
        second = self.applied('KLA', 'Applications Engineer', 'Sunnyvale, CA', '18812')
        self.posting('https://kla.example/applications-engineer/44408/100768196016',
                     'kla', 'Applications Engineer', 'Sunnyvale, California', '100768196016')
        self.assertEqual([len(self.shown(group)['jobs']) for group in (first, second)], [1, 1])

    def test_a_requisition_in_another_case_is_the_same(self):
        group = self.applied('KLA', 'Static Timing Engineer', 'Phoenix, AZ', 'jr0286869')
        real = self.posting('https://kla.example/Static-Timing-Engineer_JR0286869-1', 'kla',
                            'Senior Static Timing Engineer', '2 Locations', 'JR0286869-1')
        self.assertEqual(self.shown(group)['jobs'][0]['matched'], 'requisition')
        self.assertEqual(self.shown(group)['jobs'][0]['url'], real)

    def test_two_postings_of_the_title_in_its_city_link_neither(self):
        group = self.applied('KLA', 'Product Development Engineer', 'Milpitas, CA', '2640241')
        for number in ('2634749', '2636529'):
            self.posting(f'https://kla.example/Product-Development-Engineer-{number}',
                         'kla', 'Product Development Engineer', 'Milpitas, CA')
        self.assertEqual(len(self.shown(group)['jobs']), 1)

    def test_a_posting_of_another_requisition_is_not_linked(self):
        group = self.applied('KLA', 'Product Development Engineer', 'Milpitas, CA', '2640241')
        self.posting('https://kla.example/Product-Development-Engineer_2634749',
                     'kla', 'Product Development Engineer', 'Milpitas, CA', '2634749')
        self.assertEqual(len(self.shown(group)['jobs']), 1)

    def test_another_city_or_employer_is_not_linked(self):
        group = self.applied('Renesas', 'Electrical Engineer', 'Austin, TX', '20032940')
        self.posting('https://jobs.renesas.com/job/electrical-engineer-in-san-jose-jid-7005',
                     'renesas', 'Electrical Engineer', 'San Jose, CALIFORNIA, United States')
        self.posting('https://kla.example/Electrical-Engineer', 'kla', 'Electrical Engineer', 'Austin, TX')
        self.assertEqual(len(self.shown(group)['jobs']), 1)

    def test_an_entry_with_its_own_description_is_left_alone(self):
        group = intake.create_group('https://company.example/1', {'title': 'Electrical Engineer', 'company': 'Renesas',
                                    'location': 'Austin, TX', 'description': 'Pasted text'})
        intake.save_manual(self.ledger, group)
        self.posting('https://jobs.renesas.com/job/electrical-engineer-jid-7004',
                     'renesas', 'Electrical Engineer', 'Austin, TX')
        state = intake.augment_queue(empty(), self.ledger, self.db)
        self.assertEqual(len(state['pending'][0]['jobs']), 1)

    def test_description_endpoint_reads_the_linked_posting(self):
        group = self.applied('Renesas', 'Electrical Engineer', 'Austin, TX', '20032940')
        real = self.posting('https://jobs.renesas.com/job/electrical-engineer-jid-7004',
                            'renesas', 'Electrical Engineer', 'Austin, TX')
        with patch.object(review.applications, 'queue', side_effect=lambda *args: empty()):
            server = review.make_server(self.db, self.ledger, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                shown = json.load(urlopen(base + '/api/queue'))['applied'][0]
                self.assertEqual(shown['jobs'][0]['url'], real)
                self.assertEqual(shown['jobs'][0]['matched'], 'title and place')
                body = json.load(urlopen(base + '/api/job?url=' + quote(real, safe='') + '&id=' + group['id']))
                self.assertEqual(body['description'], 'Debug SystemVerilog')
            finally:
                server.shutdown(); server.server_close()
