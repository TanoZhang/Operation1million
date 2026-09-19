"""Remembering an exclusion answer must give the same answer.

`queue()` ran 2.5 million regex searches a request against 39,765 postings, and
both exclusion checks are pure functions of a string. The strings repeat -- 413
distinct company keys, 29,088 distinct titles -- so the answers are cached
within a call. These tests hold the two ways that can go wrong: caching under a
key the function does not read, and caching across rules that changed.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from jobdisco import applications


class QueueCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / 'jobs.sqlite'
        self.ledger = self.root / 'operational/applications.ndjson'
        self.now = datetime.now(timezone.utc)

    def build(self, rows):
        """rows: (ident, title, company_key, catalog_name, employer_name)"""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT,
                                  location TEXT, source_job_id TEXT, first_seen TEXT,
                                  posted_at TEXT, provider_key TEXT, relevance REAL,
                                  closed_at TEXT, raw TEXT);''')
            for ident, title, key, catalog, employer in rows:
                db.execute('INSERT OR IGNORE INTO companies VALUES (?, ?)', (key, catalog))
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?)',
                           (f'https://example.test/{ident}', key, title, 'Austin', ident,
                            (self.now - timedelta(days=1)).isoformat(), 'jsearch', 80,
                            json.dumps({'employer_name': employer,
                                        'description': 'RTL SystemVerilog UVM ' * 80})))

    def titles(self):
        state = applications.queue(self.db, self.ledger, self.now)
        return {job['source_job_id'] for g in state['pending'] for job in g['jobs']}

    def test_one_company_key_with_two_display_names_is_judged_separately(self):
        """The bug a company_key cache would have introduced.

        employer_excluded reads the display name, and the select COALESCEs a
        catalog name over the provider's. Two rows can share a key and differ
        in the name the rule is written against.
        """
        self.build([
            ('clean', 'RTL Design Engineer', 'shared', None, 'Example Semiconductor'),
            ('defence', 'RTL Design Engineer', 'shared', None, 'Lockheed Martin'),
        ])
        surviving = self.titles()
        self.assertIn('clean', surviving)
        self.assertNotIn('defence', surviving, 'a blacklisted employer was cached away')

    def test_repeated_employers_and_titles_still_produce_the_same_queue(self):
        rows = []
        for n in range(40):
            rows.append((f'keep{n}', 'RTL Design Engineer', 'ok', 'Example Semiconductor', 'x'))
            rows.append((f'drop{n}', 'Senior RTL Design Engineer', 'ok', 'Example Semiconductor', 'x'))
        self.build(rows)
        surviving = self.titles()
        self.assertEqual(len(surviving), 40)
        self.assertTrue(all(s.startswith('keep') for s in surviving))

    def test_a_title_excluded_once_is_excluded_every_time(self):
        self.build([('a', 'Data Center Technician', 'ok', 'Example', 'x'),
                    ('b', 'Data Center Technician', 'ok', 'Example', 'x'),
                    ('c', 'RTL Design Engineer', 'ok', 'Example', 'x')])
        self.assertEqual(self.titles(), {'c'})

    def test_an_empty_or_missing_employer_name_does_not_collide_with_a_real_one(self):
        self.build([('named', 'RTL Design Engineer', 'k1', 'Raytheon', 'Raytheon'),
                    ('blank', 'RTL Design Engineer', 'k2', None, '')])
        surviving = self.titles()
        self.assertIn('blank', surviving)
        self.assertNotIn('named', surviving)


if __name__ == '__main__':
    unittest.main()
