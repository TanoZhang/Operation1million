"""Passed or Declined for an applied position, asked for on 2026-10-05.

Recorded by the review page beside the decision ledger, never in it: the
position stays applied, and the mark is shown on the Applied tab only.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jobdisco import applications, review

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://careers.example.test/jobs/R123'


class OutcomeStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'operational/application_outcomes.ndjson'

    def test_the_latest_outcome_wins_and_an_empty_one_clears_it(self):
        applications.append_outcome(self.path, 'g1', 'passed')
        applications.append_outcome(self.path, 'g1', 'declined')
        applications.append_outcome(self.path, 'g2', 'passed')
        read = applications.read_outcomes(self.path)
        self.assertEqual({key: event['outcome'] for key, event in read.items()},
                         {'g1': 'declined', 'g2': 'passed'})
        applications.append_outcome(self.path, 'g1', '')
        self.assertEqual(list(applications.read_outcomes(self.path)), ['g2'])

    def test_only_the_two_outcomes_are_accepted(self):
        for bad in ('offer', 'Passed', None, 3):
            with self.assertRaises(ValueError, msg=bad):
                applications.append_outcome(self.path, 'g1', bad)
        with self.assertRaises(ValueError):
            applications.append_outcome(self.path, '', 'passed')
        self.assertFalse(self.path.exists())

    def test_a_damaged_line_does_not_hide_the_others(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"id": "x", "outc\n' + json.dumps({'id': 'g1', 'outcome': 'passed', 'at': 't'})
                             + '\n' + json.dumps({'id': 'g2', 'outcome': 'offer', 'at': 't'}) + '\n',
                             encoding='utf-8')
        self.assertEqual(list(applications.read_outcomes(self.path)), ['g1'])

    def test_the_file_sits_beside_the_ledger(self):
        ledger = Path('/data/operational/applications.ndjson')
        self.assertEqual(applications.outcomes_path(ledger),
                         Path('/data/operational/application_outcomes.ndjson'))

    def test_only_an_applied_position_shows_its_outcome(self):
        state = {'pending': [{'id': 'g1', 'outcome': 'passed'}], 'backlog': [],
                 'applied': [{'id': 'g2'}, {'id': 'g3', 'outcome': 'declined', 'outcome_at': 't'}],
                 'skipped': []}
        applications.attach_outcomes(state, {'g1': {'outcome': 'passed', 'at': 't'},
                                             'g2': {'outcome': 'passed', 'at': 't2'}})
        self.assertNotIn('outcome', state['pending'][0])
        self.assertEqual((state['applied'][0]['outcome'], state['applied'][0]['outcome_at']), ('passed', 't2'))
        self.assertNotIn('outcome', state['applied'][1])


class OutcomeEndpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.db = root / 'jobs.sqlite'
        self.ledger = root / 'operational/applications.ndjson'
        seen = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (URL, 'acme', 'RTL Engineer', 'Austin, TX', 'R123', seen, None, 'jsearch', 80, None,
                        json.dumps({'description': '<p>RTL design.</p>'}), seen))
        server = review.make_server(self.db, self.ledger, 0, root / 'review-queue.xlsx')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        self.root = f'http://127.0.0.1:{server.server_port}'

    def queue(self):
        with urlopen(self.root + '/api/queue') as response:
            return json.load(response)

    def post(self, path, body, token):
        request = Request(self.root + path, data=json.dumps(body).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'X-Review-Token': token})
        with urlopen(request) as response:
            return json.load(response)

    def applied(self):
        state = self.queue()
        group = state['pending'][0]
        self.post('/api/decision', {'id': group['id'], 'status': 'applied'}, state['token'])
        return group['id'], state['token']

    def test_passed_is_recorded_and_shown_without_touching_the_ledger(self):
        group_id, token = self.applied()
        ledger_before = self.ledger.read_bytes()
        self.assertEqual(self.post('/api/outcome', {'id': group_id, 'outcome': 'passed'}, token)['outcome'],
                         'passed')
        self.assertEqual(self.queue()['applied'][0]['outcome'], 'passed')
        self.assertEqual(self.ledger.read_bytes(), ledger_before)
        # A fresh build reads it back from the file.
        rebuilt = applications.queue(self.db, self.ledger)
        self.assertEqual(rebuilt['applied'][0]['outcome'], 'passed')

    def test_changing_and_clearing_it(self):
        group_id, token = self.applied()
        self.post('/api/outcome', {'id': group_id, 'outcome': 'passed'}, token)
        self.post('/api/outcome', {'id': group_id, 'outcome': 'declined'}, token)
        self.assertEqual(self.queue()['applied'][0]['outcome'], 'declined')
        self.post('/api/outcome', {'id': group_id, 'outcome': ''}, token)
        self.assertNotIn('outcome', self.queue()['applied'][0])

    def test_refusals(self):
        state = self.queue()
        pending = state['pending'][0]['id']
        with self.assertRaises(HTTPError) as refused:
            self.post('/api/outcome', {'id': pending, 'outcome': 'passed'}, state['token'])
        self.assertEqual(refused.exception.code, 409)
        group_id, token = self.applied()
        with self.assertRaises(HTTPError) as refused:
            self.post('/api/outcome', {'id': group_id, 'outcome': 'offer'}, token)
        self.assertEqual(refused.exception.code, 400)
        with self.assertRaises(HTTPError) as refused:
            self.post('/api/outcome', {'id': group_id, 'outcome': 'passed'}, 'wrong')
        self.assertEqual(refused.exception.code, 403)
        self.assertFalse(applications.outcomes_path(self.ledger).exists())


class OutcomePageTests(unittest.TestCase):
    def test_the_page_offers_and_highlights_the_outcome(self):
        script = (ROOT / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')
        for needle in ("'/api/outcome'", 'outcome-passed', 'outcome-declined', 'Clear outcome'):
            self.assertIn(needle, script)
        style = (ROOT / 'src/jobdisco/review_static/style.css').read_text(encoding='utf-8')
        self.assertIn('.job.outcome-passed', style)
        self.assertIn('outcome', review.GROUP_FIELDS)

    def test_the_file_is_backed_up_and_merged_with_the_ledger(self):
        for script in ('backup-applications.sh', 'daily-pass.sh', 'data-sync.sh'):
            text = (ROOT / 'deploy/vps' / script).read_text(encoding='utf-8')
            self.assertIn('operational/application_outcomes.ndjson', text, script)


if __name__ == '__main__':
    unittest.main()
