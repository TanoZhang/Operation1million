"""Application decisions survive job-index replacement and process restarts.

A decision covers one requisition. Company and title used to be the identity,
which merged separate openings that happened to share a name: measured on the
live queue, Apple's Design Verification Engineer was 48 postings across 14
locations, so skipping it once would have buried at least 34 other requisitions
without saying so. Showing a posting twice is recoverable; hiding one is not.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from jobdisco import applications, review


class ApplicationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / 'jobs.sqlite'
        self.ledger = self.root / 'operational/applications.ndjson'
        self.now = datetime.now(timezone.utc)
        self.create_database()

    def create_database(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample Semiconductor');
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT,
                                  first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT);''')
            # a and b share a company and a normalized title but are separate
            # requisitions. a2 is the same requisition as a, in another city.
            rows = [('a', 'RTL Engineer', 'req-a', 1, None),
                    ('a2', 'RTL Engineer', 'req-a', 1, None),
                    ('b', ' rtl  engineer ', 'req-b', 2, None),
                    ('c', 'Old Engineer', 'req-c', 4, None),
                    ('d', 'Closed Engineer', 'req-d', 1, 'closed')]
            for ident, title, requisition, age, closed in rows:
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (f'https://example.test/{ident}', 'sample', title, ident.upper(),
                            requisition,
                            (self.now - timedelta(days=age)).isoformat(), None, 'direct', 80, closed,
                            json.dumps({'description': '<p>Design hardware.</p>'})))

    def queue(self):
        return applications.queue(self.db, self.ledger, self.now)

    def group_for(self, requisition, bucket='pending'):
        key = applications.decision_key({'provider_key': 'direct',
                                         'company_key': 'sample',
                                         'source_job_id': requisition, 'url': ''})
        return next(g for g in self.queue()[bucket] if g['id'] == key)

    def test_a_shared_title_is_not_a_shared_decision(self):
        """The bug this replaced: two requisitions answered by one click."""
        pending = self.queue()['pending']
        self.assertEqual(len(pending), 2, 'separate requisitions were merged')
        self.assertEqual({g['id'] for g in pending},
                         {applications.decision_key({'provider_key': 'direct',
                                                     'company_key': 'sample',
                                                     'source_job_id': r, 'url': ''})
                          for r in ('req-a', 'req-b')})

    def test_one_requisition_in_two_cities_is_still_one_decision(self):
        """The case the old grouping was right about, kept."""
        group = self.group_for('req-a')
        self.assertEqual({job['location'] for job in group['jobs']}, {'A', 'A2'})
        applications.append_decision(self.ledger, group, 'skipped', 'wrong stack')
        self.assertEqual(len(self.queue()['pending']), 1, 'the other city stayed open')
        self.assertEqual(len(self.queue()['skipped'][0]['jobs']), 2)

    def test_deciding_one_requisition_leaves_its_namesake_alone(self):
        applications.append_decision(self.ledger, self.group_for('req-a'), 'applied')
        remaining = self.queue()['pending']
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['id'],
                         applications.decision_key({'provider_key': 'direct',
                                                    'company_key': 'sample',
                                                    'source_job_id': 'req-b', 'url': ''}))

    def test_direct_requisition_ids_are_scoped_to_the_company_board(self):
        left = applications.decision_key({'provider_key': 'workday', 'company_key': 'left',
                                          'source_job_id': 'R-123', 'url': 'https://left.test/job'})
        right = applications.decision_key({'provider_key': 'workday', 'company_key': 'right',
                                           'source_job_id': 'R-123', 'url': 'https://right.test/job'})
        self.assertNotEqual(left, right)

    def test_jsearch_requisition_ids_remain_provider_scoped(self):
        left = applications.decision_key({'provider_key': 'jsearch', 'company_key': 'left',
                                          'source_job_id': 'shared', 'url': 'https://left.test/job'})
        right = applications.decision_key({'provider_key': 'jsearch', 'company_key': 'right',
                                           'source_job_id': 'shared', 'url': 'https://right.test/job'})
        self.assertEqual(left, right)

    def test_applied_survives_database_rebuild(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'applied')
        self.db.unlink()
        self.create_database()
        state = self.queue()
        self.assertEqual(len(state['applied']), 1)
        self.assertEqual(applications.read_events(self.ledger)[0]['status'], 'applied')

    def test_a_new_requisition_under_a_decided_title_stays_pending(self):
        """Not missing a posting outranks not seeing a familiar title twice."""
        applications.append_decision(self.ledger, self.group_for('req-a'), 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""INSERT INTO jobs SELECT 'https://example.test/new', company_key,
                          title, 'New York', 'req-new', first_seen, posted_at, provider_key,
                          relevance, closed_at, raw FROM jobs WHERE url='https://example.test/a'""")
        self.assertIn('req-new', {job['source_job_id']
                                  for group in self.queue()['pending'] for job in group['jobs']})

    def test_skip_and_reopen_only_append(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'skipped', 'Location')
        original = self.ledger.read_bytes()
        self.assertEqual(self.queue()['skipped'][0]['reason'], 'Location')
        applications.append_decision(self.ledger, group, 'pending')
        self.assertTrue(self.ledger.read_bytes().startswith(original))
        self.assertEqual(len(self.queue()['pending']), 2)
        self.assertEqual(self.queue()['skipped'], [])

    def test_url_only_event_is_honored(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text(json.dumps({'url': 'https://example.test/a', 'at': self.now.isoformat(),
                                           'status': 'applied'}) + '\n', encoding='utf-8')
        surviving = {job['url'] for group in self.queue()['pending'] for job in group['jobs']}
        self.assertNotIn('https://example.test/a', surviving)
        self.assertIn('https://example.test/a2', surviving)
        self.assertEqual(self.queue()['applied'][0]['jobs'][0]['url'], 'https://example.test/a')

    def test_corrupt_tail_blocks_writes_without_rewriting_evidence(self):
        group = self.group_for('req-a')
        self.ledger.write_bytes(b'{"url":')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            applications.append_decision(self.ledger, group, 'applied')
        self.assertEqual(self.ledger.read_bytes(), b'{"url":')

    def test_concurrent_decisions_produce_complete_append_only_events(self):
        group = self.group_for('req-a')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda number: applications.append_decision(
                self.ledger, group, 'skipped', str(number)), range(8)))
        events = applications.read_events(self.ledger)
        self.assertEqual(len(events), 8)
        self.assertEqual({event['reason'] for event in events}, {str(n) for n in range(8)})

    def test_history_survives_closure_and_aging_out(self):
        group = self.group_for('req-a')
        applications.append_decision(self.ledger, group, 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET closed_at='closed'")
        state = applications.queue(self.db, self.ledger, self.now + timedelta(days=30))
        self.assertEqual(state['pending'], [])
        self.assertEqual(state['backlog'], [])
        self.assertEqual(state['applied'][0]['title'], group['title'])


class BacklogTests(ApplicationsTests):
    """A three-day queue is a working rhythm, not an expiry date."""

    def test_an_undecided_job_moves_to_backlog_instead_of_vanishing(self):
        state = self.queue()
        backlog_ids = {job['source_job_id'] for g in state['backlog'] for job in g['jobs']}
        self.assertEqual(backlog_ids, {'req-c'}, 'the four-day-old posting was lost')
        self.assertNotIn('req-c', {job['source_job_id']
                                   for g in state['pending'] for job in g['jobs']})

    def test_the_backlog_is_still_decidable(self):
        applications.append_decision(self.ledger, self.group_for('req-c', 'backlog'), 'skipped')
        self.assertEqual(self.queue()['backlog'], [])
        self.assertEqual(self.queue()['skipped'][0]['jobs'][0]['source_job_id'], 'req-c')

    def test_a_closed_job_is_in_neither_queue(self):
        everywhere = {job['source_job_id'] for bucket in ('pending', 'backlog')
                      for g in self.queue()[bucket] for job in g['jobs']}
        self.assertNotIn('req-d', everywhere)

    def test_the_backlog_obeys_the_same_exclusions_as_the_queue(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET title='Senior RTL Engineer' WHERE source_job_id='req-c'")
        self.assertEqual(self.queue()['backlog'], [])


class HttpTests(ApplicationsTests):
    def test_http_decisions_require_token_and_replay_on_refresh(self):
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        payload = json.dumps({'id': state['pending'][0]['id'], 'status': 'applied'}).encode()
        with self.assertRaises(HTTPError) as rejected:
            urlopen(Request(root + '/api/decision', data=payload))
        self.assertEqual(rejected.exception.code, 403)
        with urlopen(Request(root + '/api/decision', data=payload,
                             headers={'X-Review-Token': state['token']})) as response:
            self.assertEqual(json.load(response)['status'], 'applied')
        with urlopen(root + '/api/queue') as response:
            refreshed = json.load(response)
        self.assertEqual(len(refreshed['pending']), len(state['pending']) - 1)
        self.assertEqual(len(refreshed['applied']), 1)

    def test_a_backlog_item_can_be_decided_over_http(self):
        server = review.make_server(self.db, self.ledger, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        root = f'http://127.0.0.1:{server.server_port}'
        with urlopen(root + '/api/queue') as response:
            state = json.load(response)
        self.assertTrue(state['backlog'], 'the backlog never reached the client')
        payload = json.dumps({'id': state['backlog'][0]['id'], 'status': 'skipped'}).encode()
        with urlopen(Request(root + '/api/decision', data=payload,
                             headers={'X-Review-Token': state['token']})) as response:
            self.assertEqual(json.load(response)['status'], 'skipped')


if __name__ == '__main__':
    unittest.main()
