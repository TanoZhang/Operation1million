"""The company's own link for a third-party listing, asked for on 2026-10-02.

Recorded by the review page beside the decision ledger, attached to every
listing at that address, shown first on the page and used by the export.
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

from jobdisco import applications, export, review

ROOT = Path(__file__).resolve().parents[1]
PAID = 'https://www.linkedin.com/jobs/view/rtl-engineer-123'
COMPANY = 'https://careers.example.test/jobs/R123'


class LinkStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'operational/listing_links.ndjson'

    def test_the_latest_link_wins_and_an_empty_one_removes_it(self):
        applications.append_link(self.path, PAID, 'https://careers.example.test/old')
        applications.append_link(self.path, PAID, COMPANY)
        self.assertEqual(applications.read_links(self.path), {PAID: COMPANY})
        applications.append_link(self.path, PAID, '')
        self.assertEqual(applications.read_links(self.path), {})

    def test_only_a_full_web_address_is_accepted(self):
        for bad in ('careers.example.test/jobs/1', 'javascript:alert(1)', 'ftp://x.test/a', 'https://'):
            with self.assertRaises(ValueError, msg=bad):
                applications.append_link(self.path, PAID, bad)
        self.assertFalse(self.path.exists())

    def test_a_damaged_line_does_not_hide_the_others(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"url": "x", "link": \n' + json.dumps({'url': PAID, 'link': COMPANY}) + '\n',
                             encoding='utf-8')
        self.assertEqual(applications.read_links(self.path), {PAID: COMPANY})

    def test_the_file_sits_beside_the_ledger(self):
        ledger = Path('/data/operational/applications.ndjson')
        self.assertEqual(applications.links_path(ledger), Path('/data/operational/listing_links.ndjson'))

    def test_the_export_links_to_the_company(self):
        group = {'id': 'g', 'company': 'Acme', 'title': 'RTL Engineer', 'confidence': 60, 'bucket': 2,
                 'jobs': [{'url': PAID, 'publisher': 'LinkedIn', 'official_link': COMPANY}]}
        row = export.rows([('pending', group)])[0]
        names = [name for name, _ in export.COLUMNS]
        self.assertEqual(row[names.index('Link')], COMPANY)
        self.assertEqual(row[names.index('Published via')], 'company site')
        self.assertEqual(row[names.index('Third-party listing')], PAID)
        plain = dict(group, jobs=[{'url': PAID, 'publisher': 'LinkedIn'}])
        row = export.rows([('pending', plain)])[0]
        self.assertEqual((row[names.index('Link')], row[names.index('Third-party listing')]), (PAID, ''))


class LinkEndpointTests(unittest.TestCase):
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
                       (PAID, 'acme', 'RTL Engineer', 'Austin, TX', 'js-1', seen, None, 'jsearch', 80, None,
                        json.dumps({'job_publisher': 'LinkedIn', 'description': '<p>RTL design.</p>'}), seen))
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

    def post(self, body, token):
        request = Request(self.root + '/api/link', data=json.dumps(body).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'X-Review-Token': token})
        with urlopen(request) as response:
            return json.load(response)

    def test_a_link_is_recorded_and_shown_without_a_rebuild(self):
        state = self.queue()
        self.assertEqual(self.post({'url': PAID, 'link': COMPANY}, state['token'])['link'], COMPANY)
        job = self.queue()['pending'][0]['jobs'][0]
        self.assertEqual(job['official_link'], COMPANY)
        self.assertEqual(applications.read_links(applications.links_path(self.ledger)), {PAID: COMPANY})
        # And a fresh build reads it back from the file.
        rebuilt = applications.queue(self.db, self.ledger)
        self.assertEqual(rebuilt['pending'][0]['jobs'][0]['official_link'], COMPANY)

    def test_removing_it(self):
        token = self.queue()['token']
        self.post({'url': PAID, 'link': COMPANY}, token)
        self.post({'url': PAID, 'link': ''}, token)
        self.assertNotIn('official_link', self.queue()['pending'][0]['jobs'][0])

    def test_refusals(self):
        token = self.queue()['token']
        for body, code in (({'url': 'https://elsewhere.test/1', 'link': COMPANY}, 409),
                           ({'url': PAID, 'link': 'not a link'}, 400)):
            with self.assertRaises(HTTPError) as refused:
                self.post(body, token)
            self.assertEqual(refused.exception.code, code)
        with self.assertRaises(HTTPError) as refused:
            self.post({'url': PAID, 'link': COMPANY}, 'wrong')
        self.assertEqual(refused.exception.code, 403)


class LinkPageTests(unittest.TestCase):
    def test_the_page_offers_and_shows_the_company_link(self):
        script = (ROOT / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')
        for needle in ("'/api/link'", 'official_link', 'Use company link', 'Open company listing'):
            self.assertIn(needle, script)
        self.assertIn('official_link', review.JOB_FIELDS)


if __name__ == '__main__':
    unittest.main()
