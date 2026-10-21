"""Every Applied entry has a description, from the index or from Muse (2026-10-16)."""
import copy
import csv
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote
from urllib.request import urlopen

from operation1million import applications, applied_jd, manual_intake as intake, review
from operation1million.paths import ROOT

JD = ('Design and verify RTL for a memory controller block. Write SystemVerilog '
      'testbenches, run regressions, and debug failures with the design team. '
      'Requires a BS in Electrical or Computer Engineering; internship experience preferred.')


def empty():
    return {name: [] for name in ('pending', 'backlog', 'applied', 'skipped')}


class AppliedDescriptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = self.root / 'operational' / 'applications.ndjson'
        self.db = self.root / 'index.sqlite'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript(
                'CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);'
                'CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, provider_key TEXT, title TEXT,'
                ' location TEXT, source_job_id TEXT, posted_at TEXT, first_seen TEXT, closed_at TEXT, raw TEXT);')
            db.execute("INSERT INTO companies VALUES ('kla', 'KLA')")

    def imported(self, company, title, requisition, status='applied'):
        """A Muse submission, imported without a description."""
        url = f'https://muse.invalid/{company.casefold()}/{requisition}'
        group = intake.create_group(url, {'title': title, 'company': company, 'location': 'Austin, TX',
                                          'source_job_id': requisition, 'description': ''})
        intake.save_manual(self.ledger, group)
        applications.append_decision(self.ledger, group, status, 'Applied by Muse')
        return group

    def indexed(self, url, title, description):
        """An Applied posting the index holds, with or without its text."""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)',
                       (url, 'kla', 'workday', title, 'Milpitas, CA', url[-4:], '2026-10-01T00:00:00+00:00',
                        json.dumps({'description': description})))
        group = {'id': 'g-' + url[-4:], 'company': 'KLA', 'title': title,
                 'jobs': [{'url': url, 'company_key': 'kla', 'provider_key': 'workday', 'title': title,
                           'location': 'Milpitas, CA', 'source_job_id': url[-4:]}]}
        applications.append_decision(self.ledger, group, 'applied')
        return group

    def supply(self, *records):
        source = self.root / 'applied-jds.jsonl'
        source.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
        return applied_jd.import_supplied(source, self.ledger)

    def state(self):
        state = empty()
        for group in self.indexed_groups:
            state['applied'].append(group)
        return intake.augment_queue(state, self.ledger, self.db)

    def test_supplied_text_binds_by_group_link_or_requisition_never_title(self):
        by_id = self.imported('Skyworks', 'RFIC Design Intern', 'R-1001')
        by_requisition = self.imported('Skyworks', 'Analog Design Intern', 'R-1002')
        same_title = self.imported('Qorvo', 'Design Intern', 'Q-1')
        self.imported('Qorvo', 'Design Intern', 'Q-2')
        withdrawn = self.imported('Teradyne', 'Test Intern', 'T-1')
        applications.append_decision(self.ledger, withdrawn, 'pending')
        written, refused = self.supply(
            {'group_id': by_id['id'], 'description': JD},
            {'company': 'Skyworks Solutions, Inc.', 'requisition': 'r-1002', 'description': JD},
            {'company': 'Qorvo', 'title': 'Design Intern', 'description': JD},
            {'group_id': withdrawn['id'], 'description': JD},
            {'url': same_title['jobs'][0]['url'], 'description': 'Too short.'},
            'not an object',
        )
        self.assertEqual(written, 2)
        self.assertEqual([why for _, why in refused],
                         ['no group id, link or employer and requisition matched',
                          'no Applied entry has this group id',
                          'description shorter than 200 characters'])
        supplied = applied_jd.read(self.ledger)
        self.assertEqual(set(supplied), {by_id['id'], by_requisition['id']})
        self.assertEqual(supplied[by_requisition['id']]['matched'], 'employer and requisition')
        # Read again, nothing is written twice.
        self.assertEqual(self.supply({'group_id': by_id['id'], 'description': JD})[0], 0)
        written, _ = self.supply({'url': same_title['jobs'][0]['url'], 'description': JD})
        self.assertEqual(written, 1)

    def test_an_id_the_missing_list_asked_for_binds_though_the_ledger_has_another(self):
        """A posting regrouped after it was applied to is listed under the id
        Review shows, while its decision keeps the old one (2026-10-20)."""
        withdrawn = self.imported('Teradyne', 'Test Intern', 'T-1')
        applications.append_decision(self.ledger, withdrawn, 'pending')
        self.ledger.with_name('applied-missing-jd.json').write_text(json.dumps(
            {'listings': [{'Group': 'regrouped'}, {'Group': withdrawn['id']}]}), encoding='utf-8')
        written, refused = self.supply({'group_id': 'regrouped', 'description': JD},
                                       {'group_id': withdrawn['id'], 'description': JD},
                                       {'group_id': 'never-asked', 'description': JD})
        self.assertEqual(written, 1)
        self.assertEqual(set(applied_jd.read(self.ledger)), {'regrouped'})
        # A decision taken since the list was written still settles it.
        self.assertEqual([why for _, why in refused], ['no Applied entry has this group id'] * 2)

    def test_the_missing_list_is_what_the_page_shows_without_text(self):
        imported = self.imported('Skyworks', 'RFIC Design Intern', 'R-1001')
        skipped = self.imported('Skyworks', 'PCB Intern', 'R-1003', status='skipped')
        full = self.indexed('https://kla.example/job/Full_0001', 'RTL Engineer', JD)
        bare = self.indexed('https://kla.example/job/Bare_0002', 'RTL Engineer II', '')
        self.indexed_groups = [full, bare]
        state = self.state()
        lacking = applied_jd.missing(state, self.db, applied_jd.read(self.ledger))
        self.assertEqual({g['id'] for g in lacking}, {imported['id'], bare['id']})
        self.assertNotIn(skipped['id'], {g['id'] for g in lacking})
        self.assertEqual(applied_jd.write_missing(self.root, lacking), 2)
        with (self.root / 'applied-missing-jd.csv').open(encoding='utf-8', newline='') as handle:
            table = list(csv.DictReader(handle))
        self.assertEqual(list(table[0]), list(applied_jd.MISSING_COLUMNS))
        row = next(r for r in table if r['Group'] == imported['id'])
        self.assertEqual((row['Company'], row['Requisition']), ('Skyworks', 'R-1001'))
        record = json.loads((self.root / 'applied-missing-jd.json').read_text(encoding='utf-8'))
        self.assertEqual(record['rows'], 2)
        self.assertEqual(record['answer_in'], 'job-applications/applied-jds.jsonl')
        # Supplied, the entry leaves the list.
        self.supply({'group_id': imported['id'], 'description': JD})
        lacking = applied_jd.missing(state, self.db, applied_jd.read(self.ledger))
        self.assertEqual({g['id'] for g in lacking}, {bare['id']})

    def test_review_shows_supplied_text_only_where_it_had_none(self):
        imported = self.imported('Skyworks', 'RFIC Design Intern', 'R-1001')
        full = self.indexed('https://kla.example/job/Full_0001', 'RTL Engineer', JD)
        self.supply({'group_id': imported['id'], 'description': JD + ' Supplied copy.'},
                    {'group_id': full['id'], 'description': JD + ' Supplied copy.'})
        self.indexed_groups = [full]
        with patch.object(review.applications, 'queue', side_effect=lambda *args: self.state_from_index()):
            server = review.make_server(self.db, self.ledger, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'

                def body(group):
                    url = group['jobs'][0]['url']
                    return json.load(urlopen(f"{base}/api/job?url={quote(url, safe='')}&id={group['id']}"))
                self.assertEqual(body(imported), {'description': JD + ' Supplied copy.', 'kind': 'supplied'})
                # The index's own description stays what is shown.
                self.assertEqual(body(full), {'description': JD})
            finally:
                server.shutdown()
                server.server_close()

    def state_from_index(self):
        state = empty()
        state['applied'] = list(self.indexed_groups)
        return state

    def test_the_daily_pass_reads_supplied_text_and_publishes_the_list(self):
        script = (ROOT / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')
        publish = script.split('publish_state() {')[1].split('\n}\n')[0]
        self.assertLess(publish.index('operation1million.applied_jd'), publish.index('operation1million.export'))
        self.assertIn('--missing-jd-dir operational', publish)
        staged = publish.split('for name in operational/source_access.sqlite', 1)[1].split('; do', 1)[0]
        for name in ('applied_descriptions.ndjson', 'applied-missing-jd.csv', 'applied-missing-jd.json'):
            self.assertIn('operational/' + name, staged)
        self.assertIn("'operational/applied_descriptions.ndjson'",
                      (ROOT / 'deploy/vps/data-sync.sh').read_text(encoding='utf-8'))
        self.assertIn('DESCRIPTIONS=operational/applied_descriptions.ndjson',
                      (ROOT / 'deploy/vps/backup-applications.sh').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()


def imported_group(ident, title, place, url='Open listing', requisition=''):
    return {'id': ident, 'company': 'AMD', 'title': title, 'manual_import': True,
            'jobs': [{'url': url, 'title': title, 'location': place, 'provider_key': 'manual',
                      'source_job_id': requisition, 'manual_import': True}]}


def listing(ident, title, place, url, provider='jsearch', requisition=''):
    return {'id': ident, 'company': 'Advanced Micro Devices, Inc.', 'title': title,
            'jobs': [{'url': url, 'title': title, 'location': place, 'provider_key': provider,
                      'source_job_id': requisition}]}


class MergeCopiesTests(unittest.TestCase):
    """Muse applied on the employer's page to what the queue offered (2026-10-16)."""

    def merged(self, applied, pending):
        state = empty()
        state['applied'], state['pending'] = applied, pending
        return intake.merge_copies(state)

    def test_the_queue_listing_joins_the_application_with_the_employer_page_leading(self):
        state = self.merged([imported_group('a', 'DFT Engineer', 'Austin, Texas')],
                            [listing('q', 'DFT Engineer', 'Austin, TX', 'https://careers.amd.com/jobs/88522', 'amd_careers')])
        self.assertEqual(state['pending'], [])
        group = state['applied'][0]
        self.assertEqual([job['url'] for job in group['jobs']], ['https://careers.amd.com/jobs/88522', 'Open listing'])
        self.assertEqual(group['merged_ids'], ['q'])

    def test_a_listing_already_shown_with_the_entry_is_not_added_twice(self):
        applied = imported_group('a', 'DFT Engineer', 'Austin, Texas')
        applied['jobs'].insert(0, {'url': 'https://careers.amd.com/jobs/88522', 'location': 'Austin, TX',
                                   'provider_key': 'amd_careers', 'matched': 'title and place'})
        state = self.merged([applied], [listing('q', 'DFT Engineer', 'Austin, TX',
                                                'https://careers.amd.com/jobs/88522', 'amd_careers')])
        self.assertEqual([job['url'] for job in state['applied'][0]['jobs']],
                         ['https://careers.amd.com/jobs/88522', 'Open listing'])
        self.assertEqual(state['pending'], [])

    def test_a_real_muse_link_leads_a_job_board_copy(self):
        state = self.merged([imported_group('a', 'DFT Engineer', 'Austin, Texas', 'https://careers.amd.com/jobs/1')],
                            [listing('q', 'DFT Engineer', 'Austin, TX', 'https://www.linkedin.com/jobs/view/1')])
        self.assertEqual(state['applied'][0]['jobs'][0]['url'], 'https://careers.amd.com/jobs/1')

    def test_a_requisition_must_be_named_by_the_listing(self):
        applied = [imported_group('a', 'Hardware Design Engineer', 'San Diego, CA', requisition='3096816')]
        other = listing('q', 'Hardware Design Engineer', 'San Diego, CA', 'https://careers.example/job/446721143441')
        self.assertEqual(len(self.merged(copy.deepcopy(applied), [other])['pending']), 1)
        named = listing('q', 'Hardware Design Engineer', 'San Diego, CA', 'https://careers.example/job/3096816')
        self.assertEqual(self.merged(copy.deepcopy(applied), [named])['pending'], [])

    def test_no_place_or_two_candidates_merge_nothing(self):
        nowhere = [imported_group('a', 'FPGA Engineer - Intern (Asia)', '')]
        self.assertEqual(len(self.merged(nowhere, [listing('q', 'FPGA Engineer - Intern (Asia)', 'Miami, FL',
                                                          'https://x.example/1')])['pending']), 1)
        two = [listing('q1', 'DFT Engineer', 'Austin, TX', 'https://x.example/1'),
               listing('q2', 'DFT Engineer', 'Austin, TX', 'https://x.example/2')]
        state = self.merged([imported_group('a', 'DFT Engineer', 'Austin, Texas')], two)
        self.assertEqual([group['id'] for group in state['pending']], ['q1', 'q2'])
        self.assertNotIn('merged_ids', state['applied'][0])
