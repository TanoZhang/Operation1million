"""Policy cases for title-only Apple rows; no invented provider responses."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from operation1million import apple, applications, collector, jsearch, store
from operation1million.collection_policy import SourcePaused


class AppleEligibilityTests(unittest.TestCase):
    def test_title_only_apple_remains_unknown_not_rejected(self):
        row = {'title': 'Design Verification Engineer', 'provider_key': 'apple_jobs',
               'raw': {'title': 'Design Verification Engineer'}}
        reason, experience = jsearch.eligibility_rejection(row, jsearch.load_plan()[0]['filter'])
        self.assertEqual(reason, '')
        self.assertIsNone(experience['effective_experience_years'])

    def test_review_filters_required_years_without_rejecting_unknown_or_preferred(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / 'jobs.sqlite'
            now = datetime.now(timezone.utc)
            with closing(sqlite3.connect(db_path)) as db, db:
                db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                    INSERT INTO companies VALUES ('example', 'Example');
                    CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                        source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                        relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
                cases = [
                    ('unknown', 'Design Verification Engineer', {}),
                    ('senior', 'Design Verification Engineer', {'minimum_qualifications':
                        'BS plus 10 years relevant industry experience.'}),
                    ('entry', 'Design Verification Engineer', {'minimum_qualifications':
                        'BS and coursework in digital verification.', 'preferred_qualifications':
                        '3 years of verification experience.'}),
                    ('intern', 'Design Verification Intern', {}),
                ]
                for ident, title, raw in cases:
                    db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('https://example.test/' + ident, 'example', title, 'Austin', ident,
                         now.isoformat(), None, 'apple_jobs', 80, None, json.dumps(raw), now.isoformat()))
            state = applications.queue(db_path, root / 'applications.ndjson', now)
            ids = {j['source_job_id'] for g in state['pending'] + state['backlog'] for j in g['jobs']}
            self.assertEqual(ids, {'unknown', 'entry', 'intern'})

    def test_other_boards_and_apple_interns_keep_existing_missing_jd_policy(self):
        rules = jsearch.load_plan()[0]['filter']
        for title, provider in [('RTL Engineer', 'other'), ('RTL Intern', 'apple_jobs')]:
            self.assertEqual(jsearch.eligibility_rejection(
                {'title': title, 'provider_key': provider, 'raw': {}}, rules)[0], '')


class AppleDetailTests(unittest.TestCase):
    def setUp(self):
        self.page = (Path(__file__).parent / 'fixtures/apple_detail_redacted.html').read_text(encoding='utf-8')
        self.url = 'https://jobs.apple.com/en-us/details/200000001-0001/example'

    def test_captured_hydration_supplies_real_qualification_fields(self):
        fields = apple.detail_fields(self.page, self.url)
        row = {'title': 'RTL Engineer', 'provider_key': 'apple_jobs', 'raw': fields}
        self.assertEqual(jsearch.eligibility_rejection(row, jsearch.load_plan()[0]['filter'])[0],
                         'required_experience_over_2_years')
        self.assertEqual(fields['preferred_qualifications'], 'Experience with verification tools.')

    def test_detail_reads_prioritize_relevant_inventory(self):
        rules = jsearch.load_plan()[0]['filter']
        for title in ('Retail Specialist', 'Existing job', 'Senior RTL Engineer'):
            self.assertFalse(apple.candidate({'title': title}, rules))
        self.assertTrue(apple.candidate({'title': 'RTL Engineer'}, rules))
        self.assertTrue(apple.candidate({'title': 'ASIC Software Engineer'}, rules))

    def test_shell_and_wrong_requisition_supply_no_evidence(self):
        for page, url in [('<html>Please enable Javascript</html>', self.url),
                          (self.page, self.url.replace('0001/example', '0002/example'))]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                apple.detail_fields(page, url)

    def collector(self):
        response = Mock(text=self.page)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return SimpleNamespace(jobs=[{'title': 'RTL Engineer', 'raw': {}, 'url': self.url,
                                     'source_job_id': '200000001-0001', 'posted_at': '2026-10-01'}],
                               fetch=Mock(return_value=response))

    def test_enrichment_survives_list_only_storage_update(self):
        c = self.collector()
        self.assertEqual(apple.enrich(c), [])
        raw = store.merge_raw(store.slim(c.jobs[0]['raw']), {'title': 'RTL Engineer'})
        self.assertEqual(raw['apple_detail']['status'], 'verified')
        self.assertIn('10 years', raw['minimum_qualifications'])

    def test_failed_detail_is_unknown_without_removing_inventory(self):
        c = self.collector()
        c.fetch.return_value.text = '<html>Search jobs</html>'
        self.assertEqual(len(apple.enrich(c)), 1)
        self.assertEqual(len(c.jobs), 1)
        self.assertEqual(c.jobs[0]['raw']['apple_detail']['status'], 'unverified')

    def test_source_pause_stops_detail_requests(self):
        c = self.collector()
        c.jobs += [dict(c.jobs[0], url=self.url + '2')]
        c.fetch.side_effect = SourcePaused('HTTP 429')
        with self.assertRaises(SourcePaused):
            apple.enrich(c)
        self.assertEqual(c.fetch.call_count, 1)

    def test_fresh_evidence_cached_but_changed_listing_refetched(self):
        c = self.collector()
        apple.enrich(c)
        raw = c.jobs[0]['raw']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE jobs(url, raw, provider_key)')
                db.execute('INSERT INTO jobs VALUES (?,?,?)', (self.url, json.dumps(raw), 'apple_jobs'))
            c = self.collector()
            apple.enrich(c, path)
            c.fetch.assert_not_called()
            self.assertEqual(c.jobs[0]['raw']['apple_detail']['status'], 'verified')
            c.jobs[0]['posted_at'] = '2026-10-02'
            apple.enrich(c, path)
            c.fetch.assert_called_once()

    def test_collector_reads_details_before_closing_its_session(self):
        source = SimpleNamespace(company_key='example', provider_key='apple_jobs',
                                 access_url='https://jobs.apple.com/en-us/search')
        args = SimpleNamespace(delay=1, store=False)
        c = collector.Collector(source, args)
        c.jobs = self.collector().jobs
        c.fetch = self.collector().fetch
        with patch.object(c, 'collect_html', return_value=('complete', '')), \
                patch.object(c.session, 'close') as close:
            self.assertEqual(c.run(), ('complete', ''))
            close.assert_called_once()
        self.assertIn('10 years', c.jobs[0]['raw']['minimum_qualifications'])

    def test_collector_keeps_inventory_when_detail_access_is_paused(self):
        source = SimpleNamespace(company_key='example', provider_key='apple_jobs',
                                 access_url='https://jobs.apple.com/en-us/search')
        c = collector.Collector(source, SimpleNamespace(delay=1, store=False))
        c.jobs = self.collector().jobs
        c.fetch = Mock(side_effect=SourcePaused('HTTP 429'))
        with patch.object(c, 'collect_html', return_value=('complete', '')):
            status, _ = c.run()
        self.assertEqual(status, 'paused')
        self.assertEqual(len(c.jobs), 1)
