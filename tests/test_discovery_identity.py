"""Stable publisher identities survive search IDs and confirmed direct copies."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from jobdisco import applications, store
from jobdisco.validate_sources import Source


class DiscoveryIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'jobs.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('sample', 'Sample Semiconductor')")
            db.commit()
        store.migrate(self.path)
        self.db = store.connect(self.path)
        self.addCleanup(self.db.close)
        log = patch.object(store, 'LOG', self.root / 'store')
        log.start()
        self.addCleanup(log.stop)
        self.source = Source('jsearch:sample', 'company_sources', 'sample',
                             'Sample Semiconductor', 'jsearch', 'https://example.test', {})
        self.ledger = self.root / 'applications.ndjson'

    def row(self, ident, url=None, provider='jsearch', description=''):
        return dict(company_key='sample', company_name='Sample Semiconductor',
                    provider_key=provider, source_job_id=ident,
                    title='ASIC Verification Engineer - New College Grad 2027',
                    location='US', url=url or 'https://www.linkedin.com/jobs/view/asic-engineer-1234567890',
                    raw={'job_description': description}, relevance=70)

    def save(self, row, day):
        store.record_source(self.db, self.source, [row], 'partial', 'full', 1,
                            stamp='2026-10-%02dT12:00:00+00:00' % day)
        self.db.commit()

    def test_rotating_search_id_preserves_linkedin_discovery(self):
        self.save(self.row('search-a'), 1)
        self.save(self.row('search-b'), 2)
        row = self.db.execute('SELECT * FROM jobs').fetchone()
        self.assertEqual(row['first_seen'], '2026-10-01T12:00:00+00:00')
        self.assertEqual(row['last_seen'], '2026-10-02T12:00:00+00:00')
        self.assertEqual(row['source_job_id'], 'search-b')

    def test_changed_opening_still_resets_history(self):
        self.save(self.row('search-a'), 1)
        changed = self.row('search-b')
        changed['title'] = 'Physical Design Engineer'
        self.save(changed, 2)
        self.assertEqual(self.db.execute('SELECT first_seen FROM jobs').fetchone()[0],
                         '2026-10-02T12:00:00+00:00')

    def test_unproven_reused_url_still_resets_history(self):
        self.save(self.row('a', 'https://example.test/opening'), 1)
        self.save(self.row('b', 'https://example.test/opening'), 2)
        self.assertEqual(self.db.execute('SELECT first_seen FROM jobs').fetchone()[0],
                         '2026-10-02T12:00:00+00:00')

    def test_confirmed_workday_copy_follows_applied_official(self):
        direct = self.row('JR1234567', 'https://sample.wd5.myworkdayjobs.com/job/ASIC_JR1234567', 'workday')
        self.save(direct, 1)
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        original = applications.queue(self.path, self.ledger, now)['pending'][0]
        applications.append_decision(self.ledger, original, 'applied')
        self.save(self.row('search-a', description='ASIC verification SystemVerilog UVM. JR1234567'), 2)
        state = applications.queue(self.path, self.ledger, now)
        self.assertEqual(state['pending'] + state['backlog'], [])
        self.assertEqual(len(state['applied']), 1)

    def test_same_title_without_requisition_evidence_is_not_hidden(self):
        self.save(self.row('JR1234567', 'https://sample.wd5.myworkdayjobs.com/job/ASIC_JR1234567', 'workday'), 1)
        self.save(self.row('search-a', description='ASIC verification SystemVerilog UVM'), 2)
        self.assertEqual(len(applications.queue(self.path, self.ledger,
                            datetime(2026, 10, 3, tzinfo=timezone.utc))['pending']), 2)

    def test_replay_recovers_earliest_discovery_from_old_rotating_ids(self):
        self.save(self.row('search-a'), 1)
        old = dict(self.db.execute('SELECT * FROM jobs').fetchone())
        old['raw'] = json.loads(old['raw'])
        old['type'] = 'job'
        later = dict(old, source_job_id='search-b',
                     first_seen='2026-10-02T12:00:00+00:00',
                     last_seen='2026-10-02T12:00:00+00:00')
        with patch.object(store, 'verify', return_value=[]), \
             patch.object(store, 'log_lines', return_value=iter(map(json.dumps, [old, later]))):
            runs = store.LOG / 'runs'
            runs.mkdir(parents=True)
            (runs / '2026-10-02.ndjson.gz').touch()
            store.rebuild(self.path)
        self.assertEqual(self.db.execute('SELECT first_seen FROM jobs').fetchone()[0],
                         '2026-10-01T12:00:00+00:00')

    def test_requisition_reference_does_not_cross_companies(self):
        direct = self.row('JR1234567', 'https://sample.wd5.myworkdayjobs.com/job/ASIC_JR1234567', 'workday')
        self.save(direct, 1)
        paid = self.row('search-a', description='ASIC verification JR1234567')
        paid['company_key'] = 'other'
        self.save(paid, 2)
        self.assertEqual(len(applications.queue(self.path, self.ledger,
                            datetime(2026, 10, 3, tzinfo=timezone.utc))['pending']), 2)

    def test_multiple_requisition_references_are_ambiguous(self):
        self.save(self.row('JR1234567', 'https://sample.wd5.myworkdayjobs.com/job/ASIC_JR1234567', 'workday'), 1)
        self.save(self.row('search-a', description='ASIC verification JR1234567 or JR7654321'), 2)
        self.assertEqual(len(applications.queue(self.path, self.ledger,
                            datetime(2026, 10, 3, tzinfo=timezone.utc))['pending']), 2)
