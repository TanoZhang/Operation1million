"""Application decisions survive job-index replacement and process restarts."""
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
                                  first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT);''')
            for ident, title, age, closed in [('a', 'RTL Engineer', 1, None),
                                               ('b', ' rtl  engineer ', 2, None),
                                               ('c', 'Old Engineer', 4, None),
                                               ('d', 'Closed Engineer', 1, 'closed')]:
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                           (f'https://example.test/{ident}', 'sample', title, ident.upper(),
                            (self.now - timedelta(days=age)).isoformat(), None, 'direct', 80, closed,
                            json.dumps({'description': '<p>Design hardware.</p>'})))

    def queue(self):
        return applications.queue(self.db, self.ledger, self.now)

    def test_three_day_open_queue_groups_company_and_normalized_title(self):
        groups = self.queue()['pending']
        self.assertEqual(len(groups), 1)
        self.assertEqual({job['location'] for job in groups[0]['jobs']}, {'A', 'B'})

    def test_applied_survives_database_rebuild_and_new_location(self):
        group = self.queue()['pending'][0]
        applications.append_decision(self.ledger, group, 'applied')
        self.db.unlink()
        self.create_database()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO jobs SELECT 'https://example.test/new', company_key, title, 'New York', first_seen, posted_at, provider_key, relevance, closed_at, raw FROM jobs WHERE url='https://example.test/a'")
        state = self.queue()
        self.assertEqual(state['pending'], [])
        self.assertEqual(len(state['applied']), 1)
        self.assertEqual(applications.read_events(self.ledger)[0]['status'], 'applied')

    def test_skip_and_reopen_only_append(self):
        group = self.queue()['pending'][0]
        applications.append_decision(self.ledger, group, 'skipped', 'Location')
        original = self.ledger.read_bytes()
        self.assertEqual(self.queue()['skipped'][0]['reason'], 'Location')
        applications.append_decision(self.ledger, group, 'pending')
        self.assertTrue(self.ledger.read_bytes().startswith(original))
        self.assertEqual(len(self.queue()['pending']), 1)
        self.assertEqual(self.queue()['skipped'], [])

    def test_url_only_event_is_honored(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text(json.dumps({'url': 'https://example.test/a', 'at': self.now.isoformat(),
                                           'status': 'applied'}) + '\n', encoding='utf-8')
        self.assertEqual([job['url'] for job in self.queue()['pending'][0]['jobs']], ['https://example.test/b'])
        self.assertEqual(self.queue()['applied'][0]['jobs'][0]['url'], 'https://example.test/a')
        applications.append_decision(self.ledger, self.queue()['applied'][0], 'pending')
        self.assertEqual(len(self.queue()['pending'][0]['jobs']), 2)

    def test_corrupt_tail_blocks_writes_without_rewriting_evidence(self):
        group = self.queue()['pending'][0]
        self.ledger.write_bytes(b'{"url":')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            applications.append_decision(self.ledger, group, 'applied')
        self.assertEqual(self.ledger.read_bytes(), b'{"url":')

    def test_concurrent_decisions_produce_complete_append_only_events(self):
        group = self.queue()['pending'][0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda number: applications.append_decision(
                self.ledger, group, 'skipped', str(number)), range(8)))
        events = applications.read_events(self.ledger)
        self.assertEqual(len(events), 8)
        self.assertEqual({event['reason'] for event in events}, {str(n) for n in range(8)})

    def test_history_survives_closure_and_aging_out(self):
        group = self.queue()['pending'][0]
        applications.append_decision(self.ledger, group, 'applied')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET closed_at='closed'")
        state = applications.queue(self.db, self.ledger, self.now + timedelta(days=30))
        self.assertEqual(state['pending'], [])
        self.assertEqual(state['applied'][0]['title'], group['title'])

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
            self.assertEqual(json.load(response)['pending'], [])


if __name__ == '__main__':
    unittest.main()
