"""Offline contracts for explicit imports and normal application decisions."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from jobdisco import manual_intake as intake, applications, jsearch, review


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
