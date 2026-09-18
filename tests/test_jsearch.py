"""Offline discovery, weighted quota, and shared durable-store regressions."""
import gzip
import io
import json
import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from jobdisco import collector, jsearch, store
from jobdisco import jsearch_access
from jobdisco.jsearch_access import RequestGuard, QuotaExhausted
from jobdisco.validate_sources import Source

SEARCH = {'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
          'connection': {'auth_header': 'X-API-Key'}}
STAMP = '2026-09-18T01:00:00+00:00'


def job(ident='1', **extra):
    return {'job_id': ident, 'job_title': 'RTL Design Engineer',
            'employer_name': 'Analog Devices', 'job_apply_link': f'https://jobs.example/{ident}',
            'job_description': 'Full responsibilities and qualifications. ' * 500,
            'job_min_salary': 120000, 'job_max_salary': 190000,
            'salary_currency': 'USD', 'salary_period': 'YEAR',
            'visa': {'sponsorship': 'unknown'}, 'skills': ['RTL', 'SystemVerilog'],
            'job_highlights': {'Qualifications': ['Degree or equivalent']},
            'employer_logo': 'https://example/logo', 'benefits': ['Insurance'],
            'future_useful_field': 'preserve', **extra}


class DiscoveryTests(unittest.TestCase):
    def test_single_week_query_skips_direct_sources_and_preserves_daily_budget(self):
        self.session.get.return_value = self.response([job()])
        output = self.root / 'manual'
        arguments = ['collector', '--jsearch-only', '--jsearch-query', 'Design Verification Engineer',
                     '--jsearch-pages', '1', '--date-posted', 'week', '--jsearch-budget', '1',
                     '--no-store', '--db', str(self.db_path), '--output', str(output)]
        # Earlier daily reservations must not turn a one-credit run cap into
        # a one-credit account/day cap.
        self.guard.get(self.session, 'https://example', credits=2)
        self.session.get.reset_mock()
        with patch.object(collector, 'load_sources', return_value=[]), \
             patch.object(collector, 'Collector') as direct, \
             patch.object(collector, 'RequestGuard', return_value=self.guard) as guard_factory, \
             patch.object(collector, 'load_credentials'), \
             patch.object(jsearch.requests, 'Session', return_value=self.session), \
             patch('sys.argv', arguments), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(collector.main(), 0)
        direct.assert_not_called()
        self.session.get.assert_called_once()
        params = parse_qs(urlsplit(self.session.get.call_args.args[0]).query)
        self.assertEqual(params['date_posted'], ['week'])
        self.assertEqual(params['num_pages'], ['1'])
        self.assertEqual(guard_factory.call_args.kwargs['daily_limit'], 320)
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['jsearch_pages_used'], 1)
        self.assertEqual(manifest['jsearch_queries'][0]['date_posted'], 'week')
        self.assertEqual(
            (manifest['store_new'], manifest['store_closed'], manifest['store_seen']),
            (0, 0, 0))
        self.assertFalse(store.LOG.exists())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings, self.plan = jsearch.load_plan()
        for target, value in [('jobdisco.store.LOG', self.root / 'store'),
                              ('jobdisco.jsearch_access.time.sleep', Mock())]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.dict('os.environ', {'JSEARCH_API_KEY': 'offline-test-placeholder'})
        p.start()
        self.addCleanup(p.stop)
        p = patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden'))
        p.start()
        self.addCleanup(p.stop)
        self.guard = RequestGuard(self.root / "usage.sqlite", daily_limit=320, target_limit=9600)
        self.session = Mock()
        self.client = jsearch.Client(SEARCH, self.settings, self.guard, session=self.session)
        self.db_path = self.root / 'jobs.sqlite'
        self.create_database(self.db_path)
        self.db = store.connect(self.db_path)
        self.addCleanup(self.db.close)

    def create_database(self, path):
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('sample', 'Sample')")
            db.commit()
        store.migrate(path)

    def response(self, jobs=(), status=200):
        response = Mock(status_code=status, headers={})
        response.json.return_value = {'status': 'OK', 'data': {'jobs': list(jobs), 'next_cursor': 'unused'}}
        return response

    def per_query(self, *responses):
        """One response per query.

        Every call asks for a single page, and a page holding fewer than ten
        jobs ends its query, so a one-job response is exactly one call.
        """
        return list(responses)

    def persist(self, query, rows, detail):
        source = Source(query.key, 'discovery', 'discovery', query.query, 'jsearch', '', {})
        delta = store.record_source(self.db, source, rows, detail['status'], 'full', 1, stamp=STAMP)
        store.append_log(self.db, delta['new_urls'] + delta['changed_urls'], delta['closed_urls'],
                         STAMP, seen_urls=delta['seen_urls'], source_id=source.source_id)
        self.db.commit()

    def collect(self, queries):
        return jsearch.collect(queries, self.client, self.settings, {}, self.persist)

    def test_fixed_catalog_and_budget_math(self):
        self.assertEqual(len(self.plan), 52)
        self.assertEqual(self.settings['monthly_target'], 9600)
        self.assertEqual(self.settings['daily_budget'], 320)
        # 320 a day for 30 days is exactly the month's target, and the anchor is
        # the day the provider resets, not the day after.
        self.assertEqual(self.settings['daily_budget'] * 30, self.settings['monthly_target'])
        # A 30-day cycle, not a day of the month: a calendar anchor would drift
        # against the provider every time a period crosses a short month.
        self.assertEqual(self.settings['cycle_start'], '2026-09-16')
        self.assertEqual(self.settings['cycle_days'], 30)
        self.assertEqual(self.settings['backfill_max_pages_per_query'], 200)
        self.assertEqual(self.settings['date_posted'], '3days')
        # No query declares a depth; each carries only the runaway guard.
        self.assertEqual(self.settings['max_pages_per_query'], 40)
        self.assertTrue(all(q.pages == 40 for q in self.plan))

    def test_more_queries_than_credits_refused_before_transport(self):
        """The tail of an oversized plan would be unreachable every day."""
        jsearch.validate_budget(self.plan, 52)
        with self.assertRaises(ValueError):
            jsearch.validate_budget(self.plan, 51)
        self.session.get.assert_not_called()

    def test_invalid_page_allocation_rejected(self):
        path = self.root / 'invalid.toml'
        for pages in (0, 41):
            path.write_text(f'[[query]]\nquery="RTL Engineer"\npages={pages}\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                jsearch.load_plan(path)

    def test_request_defaults_and_multi_page_batch_without_expansion(self):
        self.session.get.return_value = self.response([job(str(i)) for i in range(20)])
        rows, stats = self.collect([jsearch.Query('RTL Design Engineer', 40, 'A')])
        params = parse_qs(urlsplit(self.session.get.call_args_list[0].args[0]).query)
        self.assertEqual(params, {'query': ['RTL Design Engineer'], 'num_pages': ['1'],
                                 'country': ['us'], 'date_posted': ['3days'],
                                 'employment_types': ['FULLTIME,INTERN']})
        # A full page advances; the identical second page is the provider
        # repeating itself, which stops the query and is not counted twice.
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(len(rows), 20)
        self.assertEqual(stats['jsearch_pages_used'], 2)
        self.assertEqual(self.guard.attempts, 2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 20)

    def test_duplicate_id_across_queries_and_changed_urls_is_one_stored_job(self):
        self.session.get.side_effect = self.per_query(
            self.response([job()]),
            self.response([job(job_apply_link='https://other.example/apply')]))
        _, stats = self.collect([replace(q, pages=1) for q in self.plan[:2]])
        self.assertEqual(stats['jsearch_jobs_raw'], 2)
        self.assertEqual(stats['jsearch_jobs_unique'], 1)
        records = self.db.execute('SELECT * FROM jobs').fetchall()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(json.loads(records[0]['raw'])['discovery_queries']), 2)

    def test_url_identity_without_job_id(self):
        self.session.get.return_value = self.response([job(None, job_apply_link='https://example/apply')])
        self.collect(self.plan[:2])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_full_content_salary_and_unknown_fields_survive_log_and_rebuild(self):
        original = job()
        self.session.get.return_value = self.response([original])
        _, stats = self.collect(self.plan[:1])
        store.write_manifest(self.db, STAMP, [], stats)
        fresh = self.root / 'rebuilt.sqlite'
        self.create_database(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as db:
            raw = json.loads(db.execute('SELECT raw FROM jobs').fetchone()[0])
            for key in ('job_description', 'job_min_salary', 'job_max_salary', 'salary_currency',
                        'salary_period', 'visa', 'skills', 'job_highlights', 'future_useful_field'):
                self.assertEqual(raw[key], original[key])
            for key in ('employer_logo', 'benefits'):
                self.assertNotIn(key, raw)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM job_identities').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT last_seen FROM jobs').fetchone()[0], STAMP)

    def test_html_only_and_nonduplicate_html_retained(self):
        for raw in ({'descriptionHtml': '<p>Required skill</p>'},
                    {'description': 'Summary', 'descriptionHtml': '<p>Full qualifications</p>'}):
            self.assertEqual(store.slim(raw), raw)
        self.assertNotIn('descriptionHtml', store.slim(
            {'description': 'Full text', 'descriptionHtml': '<p>Full text</p>'}))

    def test_filter_uses_title_not_employer_and_keeps_ambiguous_experience(self):
        self.session.get.return_value = self.response([
            job('1'), job('2', job_title='Analog IC Designer'),
            job('3', job_title='Engineer'), job('4', job_title='Senior FPGA Engineer')])
        rows, stats = self.collect([replace(self.plan[0], pages=1)])
        self.assertEqual([r['source_job_id'] for r in rows], ['1', '3', '4'])
        self.assertEqual(stats['jsearch_jobs_rejected'], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM companies').fetchone()[0], 1)
        self.assertEqual(jsearch.rejection_reason({'title': 'RF Engineer'}, self.settings['filter']), 'title_mismatch')

    def test_company_fallback_requires_exact_employer_alias(self):
        self.session.get.return_value = self.response([job(), job('2', employer_name='Sample')])
        rows, stats = self.collect([jsearch.Query('Sample', 1, 'company', 'sample', ('Sample',))])
        self.assertEqual([r['company_name'] for r in rows], ['Sample'])
        self.assertEqual(stats['jsearch_jobs_rejected'], 1)

    def test_direct_record_remains_authoritative_with_search_enrichment(self):
        source = Source('direct', 'company_sources', 'sample', 'Sample', 'ashby', '', {})
        row = jsearch.normalize_job(job(), self.plan[0], {})
        row.update(company_key='sample', provider_key='ashby', title='Official title', source_job_id='ATS-1')
        store.record_source(self.db, source, [row], 'complete', 'full', 1)
        self.session.get.return_value = self.response([job()])
        self.collect(self.plan[:1])
        record = self.db.execute('SELECT * FROM jobs').fetchone()
        self.assertEqual((record['title'], record['provider_key']), ('Official title', 'ashby'))
        self.assertEqual(json.loads(record['raw'])['jsearch']['job_id'], '1')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_search_absence_never_closes_jobs(self):
        self.session.get.side_effect = self.per_query(self.response([job()]), self.response([]))
        self.collect(self.plan[:2])
        self.assertIsNone(self.db.execute('SELECT closed_at FROM jobs').fetchone()[0])

    def test_empty_direct_inventory_trips_fuse_without_touching_search_rows(self):
        self.session.get.return_value = self.response([job()])
        self.collect(self.plan[:1])
        source = Source('direct', 'company_sources', 'sample', 'Sample', 'ashby', '', {})
        row = jsearch.normalize_job(job('direct'), self.plan[0], {})
        row.update(company_key='sample', provider_key='ashby')
        store.record_source(self.db, source, [row], 'complete', 'full', 1)
        delta = store.record_source(self.db, source, [], 'complete', 'full', 1)
        self.assertEqual(delta['status'], 'partial')
        self.assertTrue(delta['closure_fused'])
        self.assertEqual(delta['closed'], 0)
        self.assertIsNone(self.db.execute("SELECT closed_at FROM jobs WHERE provider_key='jsearch'").fetchone()[0])

    def test_collector_report_exposes_a_tripped_closure_fuse(self):
        source = Source('direct', 'company_sources', 'sample', 'Sample', 'ashby', '', {})
        baseline = []
        for i in range(8):
            item = jsearch.normalize_job(job(str(i)), self.plan[0], {})
            item.update(company_key='sample', company_name='Sample', provider_key='ashby')
            baseline.append(item)
        store.record_source(self.db, source, baseline, 'complete', 'full', 1,
                            stamp='2026-09-17T00:00:00+00:00')
        self.db.commit()
        fake = Mock(jobs=[], rejected=[], requests=1, listed=None, etag=None,
                    last_modified=None)
        fake.run.return_value = ('complete', '')
        output = self.root / 'fuse-run'
        arguments = ['collector', '--db', str(self.db_path), '--output', str(output)]
        with patch.object(collector, 'load_sources', return_value=[source]), \
             patch.object(collector, 'Collector', return_value=fake), \
             patch.object(collector, 'RequestGuard', return_value=self.guard), \
             patch.object(collector, 'load_credentials'), \
             patch('sys.argv', arguments), patch('sys.stdout', new_callable=io.StringIO) as stdout:
            self.assertEqual(collector.main(), 2)
        with (output / 'company_results.csv').open(newline='', encoding='utf-8') as handle:
            report = next(csv.DictReader(handle))
        self.assertEqual(report['direct_status'], 'partial')
        self.assertIn('Closure fuse blocked 8 of 8', report['failure_reason'])
        self.assertIn('WARNING: Closure fuse blocked 8 of 8', stdout.getvalue())
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM jobs WHERE provider_key='ashby' AND closed_at IS NULL"
        ).fetchone()[0], 8)

    def test_changed_and_seen_events_rebuild_with_stale_state_snapshot(self):
        self.session.get.return_value = self.response([job()])
        self.collect(self.plan[:1])
        store.export_state(self.db)
        later = '2026-09-19T01:00:00+00:00'
        query = self.plan[0]
        source = Source(query.key, 'discovery', 'discovery', query.query, 'jsearch', '', {})
        row = jsearch.normalize_job(job(job_description='Updated full description'), query, {})
        delta = store.record_source(self.db, source, [row], 'query_limited', 'full', 1, stamp=later)
        store.append_log(self.db, delta['changed_urls'], [], later, source_id=source.source_id)
        final = '2026-09-20T01:00:00+00:00'
        delta = store.record_source(self.db, source, [row], 'query_limited', 'full', 1, stamp=final)
        store.append_log(self.db, [], [], final, seen_urls=delta['seen_urls'], source_id=source.source_id)
        self.db.commit()
        fresh = self.root / 'seen.sqlite'
        self.create_database(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as db:
            restored = db.execute('SELECT * FROM jobs').fetchone()
            self.assertEqual(restored['first_seen'], STAMP)
            self.assertEqual(restored['last_seen'], final)
            self.assertEqual(json.loads(restored['raw'])['job_description'], 'Updated full description')
            self.assertEqual(db.execute('SELECT last_run_at FROM source_state').fetchone()[0], final)

    def test_preview_without_database_has_no_network_or_durable_side_effect(self):
        missing = self.root / 'absent.sqlite'
        with patch('sys.argv', ['collector', '--jsearch-plan', '--db', str(missing)]), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(collector.main(), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview['queries_planned'], 52)
        self.assertEqual(preview['max_pages_per_query'], 40)
        self.assertFalse(missing.exists())
        self.assertFalse(store.LOG.exists())

    def test_each_page_is_reserved_before_dispatch_and_settled_after(self):
        """Accounting must be durable per page, not summarised at run end."""
        guard = RequestGuard(path=self.root / 'live.sqlite', limit=100,
                           target_limit=100, daily_limit=10, cycle_start="2026-09-16", cycle_days=30)
        seen = []

        def dispatch(url, **kwargs):
            # Mid-flight the credit is already committed and already visible.
            seen.append(RequestGuard(path=self.root / 'live.sqlite', limit=100,
                                   target_limit=100, daily_limit=10,
                                   cycle_start="2026-09-16", cycle_days=30).balance())
            return Mock(status_code=200, headers={'X-RapidAPI-Billing': 'Queries=1; Requests=1'})

        session = Mock()
        session.get.side_effect = dispatch
        guard.get(session, 'https://example', credits=1)
        self.assertEqual(seen[0]['period_used'], 1)
        self.assertEqual(seen[0]['day_remaining'], 9)

        session.get.side_effect = requests.Timeout('gateway')
        with self.assertRaises(requests.Timeout):
            guard.get(session, 'https://example', credits=1)

        after = RequestGuard(path=self.root / 'live.sqlite', limit=100,
                           target_limit=100, daily_limit=10, cycle_start="2026-09-16", cycle_days=30).balance()
        # A failed page is charged, and is visible as charged-but-unproductive.
        self.assertEqual(after['period_used'], 2)
        self.assertEqual(after['period_unproductive'], 1)
        # The provider charged what was reserved for the page it answered.
        self.assertEqual(after['provider_drift'], 0)

    def test_rolling_cycle_tracks_thirty_days_not_a_calendar_day(self):
        guard = RequestGuard(path=self.root / 'cycle.sqlite',
                             cycle_start='2026-09-16', cycle_days=30)
        expected = {'2026-09-16': ('2026-09-16', 30), '2026-10-13': ('2026-09-16', 3),
                    '2026-10-15': ('2026-09-16', 1), '2026-10-16': ('2026-10-16', 30),
                    # Thirty days after 16 October is 15 November, so the sweep
                    # window is not a fixed set of month days.
                    '2026-11-14': ('2026-10-16', 1)}
        for today, (start, left) in expected.items():
            stamp = datetime.fromisoformat(today + 'T12:00:00+00:00').timestamp()
            with patch.object(jsearch_access.time, 'time', return_value=stamp):
                self.assertEqual(guard.period()[0], start, today)
                self.assertEqual(guard.days_until_reset(), left, today)

    def test_a_run_budget_binds_now_that_depth_is_discovered(self):
        """A declared plan used to bound a run; adaptive paging does not.

        The sum of a plan's pages once guaranteed the spend, so a budget only
        had to be checked before the run. With depth discovered while paging,
        nothing stops a run at its share unless the guard itself does.
        """
        guard = RequestGuard(path=self.root / 'runcap.sqlite', limit=10000,
                             target_limit=9600, daily_limit=320,
                             cycle_start='2026-09-16', cycle_days=30,
                             ignore_daily_limit=True, run_limit=4)
        client = jsearch.Client(SEARCH, self.settings, guard, session=self.session)
        # Distinct jobs per page, so only the budget can end this query.
        self.session.get.side_effect = lambda url, **kw: self.response(
            [job(f'{parse_qs(urlsplit(url).query).get("page", ["1"])[0]}-{i}') for i in range(10)])
        _, stats = jsearch.collect([jsearch.Query('RTL Design Engineer', 200, 'A')],
                                   client, self.settings, {}, self.persist)
        # Four pages, not two hundred, and not the cycle's whole remainder.
        self.assertEqual(guard.credits, 4)
        self.assertEqual(stats['jsearch_pages_used'], 4)

    def test_reaching_the_budget_is_not_counted_as_a_failure(self):
        """It is how an adaptive run ends, so counting it would hide real ones."""
        guard = RequestGuard(path=self.root / 'endofrun.sqlite', limit=10000,
                             target_limit=9600, daily_limit=320,
                             cycle_start='2026-09-16', cycle_days=30, run_limit=2)
        client = jsearch.Client(SEARCH, self.settings, guard, session=self.session)
        self.session.get.side_effect = lambda url, **kw: self.response(
            [job(f'{parse_qs(urlsplit(url).query).get("page", ["1"])[0]}-{i}') for i in range(10)])
        _, stats = jsearch.collect([jsearch.Query('RTL Design Engineer', 200, 'A')],
                                   client, self.settings, {}, self.persist)
        self.assertEqual(stats['jsearch_failures'], 0)
        self.assertEqual(stats['jsearch_queries'][0]['status'], 'query_limited')
        self.assertIn('budget', stats['jsearch_queries'][0]['reason'])

    def test_backfill_budget_splits_the_remainder_over_the_days_that_remain(self):
        """An early sweep must leave something for a day that has to retry."""
        settings = dict(self.settings, monthly_target=9600)
        for days, left, expected in ((3, 900, 300), (2, 600, 300), (1, 300, 300)):
            guard = RequestGuard(path=self.root / f'split{days}.sqlite',
                                 limit=10000, target_limit=settings['monthly_target'],
                                 daily_limit=320, cycle_start='2026-09-16', cycle_days=30,
                                 ignore_daily_limit=True)
            guard.baseline(settings['monthly_target'] - left, period='2026-09-16')
            with patch.object(guard, 'days_until_reset', return_value=days),                  patch.object(guard, 'period', return_value=('2026-09-16', '2026-10-14')):
                remaining = guard.balance()['period_remaining']
                budget = remaining if days <= 1 else remaining // days
            self.assertEqual((remaining, budget), (left, expected))

    def test_backfill_resumes_where_the_previous_day_stopped(self):
        """A month-wide sweep is split across days without losing its depth.

        One long run does not fit an Actions job, but restarting each day at
        page one would re-buy the pages the sweep already holds, so the split
        would cost depth rather than time.
        """
        pages = {}

        def dispatch(url, **kwargs):
            asked = parse_qs(urlsplit(url).query)
            page = int(asked.get('page', ['1'])[0])
            pages.setdefault(asked['query'][0], []).append(page)
            # Full pages for a while, so nothing exhausts within one day.
            return self.response([job(f'p{page}-{i}') for i in range(10)])

        self.session.get.side_effect = dispatch
        query = jsearch.Query('RTL Design Engineer', 3, 'A')
        jsearch.collect([query], self.client, self.settings, {}, self.persist, backfill=True)
        first = list(pages['RTL Design Engineer'])
        jsearch.collect([query], self.client, self.settings, {}, self.persist, backfill=True)
        self.assertEqual(first, [1, 2, 3])
        # The second day continues past the cap the first day reached, rather
        # than asking for page one again.
        self.assertEqual(pages['RTL Design Engineer'][len(first):], [])
        # The cap binds before the credit is spent, so a resumed sweep that is
        # already past it buys nothing at all.
        self.assertEqual(self.guard.credits, 3)
        self.assertEqual(self.guard.resume_page(query.key), (4, False))

    def test_backfill_checkpoints_jobs_before_advancing_its_cursor(self):
        self.session.get.return_value = self.response([job('kept')])
        query = jsearch.Query('RTL Design Engineer', 3, 'A')
        order = []

        def checkpoint(current, rows, detail):
            order.append(('checkpoint', self.guard.resume_page(current.key), len(rows)))
            raise RuntimeError('simulated crash while committing the page')

        with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
            jsearch.collect([query], self.client, self.settings, {}, self.persist,
                            backfill=True, checkpoint=checkpoint)

        self.assertEqual(order, [('checkpoint', (1, False), 1)])
        self.assertEqual(self.guard.resume_page(query.key), (1, False))

    def test_successful_checkpoint_advances_backfill_cursor_after_commit(self):
        self.session.get.return_value = self.response([job('kept')])
        query = jsearch.Query('RTL Design Engineer', 3, 'A')

        def checkpoint(current, rows, detail):
            self.persist(current, rows, dict(detail, status='query_limited'))

        jsearch.collect([query], self.client, self.settings, {}, lambda *args: None,
                        backfill=True, checkpoint=checkpoint)

        self.assertEqual(self.guard.resume_page(query.key), (2, True))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_backfill_mode_changes_only_window_cap_and_daily_slice(self):
        """The daily pass must behave exactly as before the sweep existed."""
        daily, _ = jsearch.load_plan()
        sweep, _ = jsearch.load_plan()
        sweep['date_posted'] = 'month'
        sweep['max_pages_per_query'] = sweep['backfill_max_pages_per_query']
        differing = {k for k in daily if k != 'query' and daily[k] != sweep.get(k)}
        self.assertEqual(differing, {'date_posted', 'max_pages_per_query'})
        self.assertEqual(daily['date_posted'], '3days')
        self.assertEqual(daily['max_pages_per_query'], 40)
        self.assertEqual(sweep['max_pages_per_query'], 200)

    def test_a_daily_run_ignores_the_backfill_cursor(self):
        """Only the sweep resumes; the ordinary daily pass always starts fresh."""
        self.guard.advance('anything', 9)
        self.session.get.return_value = self.response([job()])
        self.collect([replace(self.plan[0], pages=40)])
        asked = parse_qs(urlsplit(self.session.get.call_args.args[0]).query)
        self.assertNotIn('page', asked)

    def test_backfill_may_pass_the_daily_slice_but_never_the_month(self):
        """Credits expire with the cycle, so the daily slice must not hold them."""
        free = RequestGuard(path=self.root / 'sweep.sqlite', limit=100, target_limit=5,
                            daily_limit=2, cycle_start="2026-09-16", cycle_days=30, ignore_daily_limit=True)
        session = Mock()
        session.get.return_value = Mock(status_code=200, headers={})
        for _ in range(5):
            free.get(session, 'https://example', credits=1)
        self.assertEqual(free.balance()['period_used'], 5)
        with self.assertRaises(QuotaExhausted):
            free.get(session, 'https://example', credits=1)

    def test_baseline_counts_credits_spent_outside_this_ledger(self):
        """A rebuilt ledger must not read the provider's spend as available."""
        guard = RequestGuard(path=self.root / 'base.sqlite', limit=1000,
                           target_limit=1000, daily_limit=10, cycle_start="2026-09-16", cycle_days=30)
        guard.baseline(218)
        self.assertEqual(guard.balance()['period_used'], 218)
        self.assertEqual(guard.balance()['period_remaining'], 782)
        near = RequestGuard(path=self.root / 'base.sqlite', limit=1000,
                          target_limit=219, daily_limit=10, cycle_start="2026-09-16", cycle_days=30)
        with self.assertRaises(QuotaExhausted):
            near.get(Mock(), 'https://example', credits=2)

    def test_weighted_daily_and_monthly_caps_survive_restart(self):
        self.session.get.return_value = self.response()
        guard = RequestGuard(self.root / 'small.sqlite', daily_limit=3, target_limit=4)
        guard.get(self.session, 'https://example', credits=2)
        again = RequestGuard(self.root / 'small.sqlite', daily_limit=3, target_limit=4)
        with self.assertRaises(QuotaExhausted):
            again.get(self.session, 'https://example', credits=2)
        with patch.object(again, 'period', return_value=(again.period()[0], '2099-01-02')):
            again.get(self.session, 'https://example', credits=2)
            with self.assertRaises(QuotaExhausted):
                again.get(self.session, 'https://example', credits=1)
        self.assertEqual(self.session.get.call_count, 2)

    def test_timeout_consumes_reserved_pages_but_does_not_damage_prior_data(self):
        self.session.get.side_effect = self.per_query(
            self.response([job()]), requests.Timeout('secret-like exception text'))
        _, stats = self.collect(self.plan[:2])
        self.assertEqual(stats['jsearch_failures'], 1)
        # One page each: the first query exhausts on a short page, and the
        # second loses a single credit rather than a whole declared batch.
        self.assertEqual(stats['jsearch_pages_used'], 2)
        self.assertNotIn('secret-like', json.dumps(stats))
        manifest = store.write_manifest(self.db, STAMP, [], stats)
        for field in ('jsearch_queries_planned', 'jsearch_queries_completed', 'jsearch_pages_cap',
                      'jsearch_pages_used', 'jsearch_jobs_raw', 'jsearch_jobs_unique', 'jsearch_failures'):
            self.assertEqual(manifest[field], stats[field])
        self.assertEqual(store.verify(), [(STAMP[:10], 'ok')])
        with gzip.open(store.daily_log(STAMP), 'rt', encoding='utf-8') as handle:
            self.assertTrue(all(isinstance(json.loads(line), dict) for line in handle))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_throttle_stops_remaining_queries_and_persists_account_pause(self):
        self.session.get.return_value = self.response(status=429)
        _, stats = self.collect(self.plan[:3])
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual([q['status'] for q in stats['jsearch_queries']], ['failed', 'skipped', 'skipped'])
        restarted = RequestGuard(self.root / 'usage.sqlite')
        with self.assertRaises(QuotaExhausted):
            restarted.get(self.session, 'https://example')

    def test_a_day_that_is_over_cannot_be_changed(self):
        # Sealing follows the calendar, not the run: a finished pass does not lock
        # the current day, but nothing may touch a day already in the record.
        past = '2020-01-01T01:00:00+00:00'
        # Lay the day down directly: the guard refuses to create it too.
        store.daily_log(past).parent.mkdir(parents=True, exist_ok=True)
        store.manifest_path(past).parent.mkdir(parents=True, exist_ok=True)
        store.daily_log(past).write_bytes(gzip.compress(b'', mtime=0))
        store.manifest_path(past).write_text('{"run_date": "2020-01-01"}', encoding='utf-8')
        original = store.daily_log(past).read_bytes()
        with self.assertRaises(FileExistsError):
            store.append_log(self.db, [], [], past)
        with self.assertRaises(FileExistsError):
            store.write_manifest(self.db, past, [])
        self.assertEqual(store.daily_log(past).read_bytes(), original)

    def test_a_second_pass_today_appends_beside_the_first(self):
        today = store.now()
        store.write_manifest(self.db, today, [])
        first = store.manifest_path(today).read_text(encoding='utf-8')
        store.append_log(self.db, [], [], today, seen_urls=['https://x/1'])
        store.write_manifest(self.db, today, [])
        # The digest tracks the file as it now stands rather than staying stale.
        self.assertNotEqual(store.manifest_path(today).read_text(encoding='utf-8'), first)

    def test_checksum_failure_prevents_replay(self):
        store.write_manifest(self.db, STAMP, [])
        with store.daily_log(STAMP).open('ab') as handle:
            handle.write(b'corrupt')
        fresh = self.root / 'bad.sqlite'
        with self.assertRaises(ValueError):
            store.rebuild(fresh)
        self.assertFalse(fresh.exists())

    def test_a_bounded_run_is_not_a_misconfigured_plan(self):
        """A deliberately small budget must not be read as a broken catalog.

        The plan is checked against the budget it is written for. Checking it
        against whatever one run was told to spend refused the sweep outright:
        a capped test, and equally a sweep whose share of the cycle is small,
        looked like a plan holding more queries than it had credits.
        """
        jsearch.validate_budget(self.plan, self.settings['daily_budget'])
        configs = {'discovery_queries.toml': {},
                   'sources_search.toml': {'search': {'jsearch': SEARCH}}}
        self.session.get.return_value = self.response([job()])
        argv = ['collector', '--jsearch-only', '--backfill', '--jsearch-budget', '5',
                '--db', str(self.db_path), '--output', str(self.root / 'bounded')]
        with (
            patch.object(collector, 'load_sources', return_value=[]),
            patch.object(collector, 'config', side_effect=configs.__getitem__),
            patch.object(collector, 'RequestGuard', return_value=self.guard),
            patch.object(collector, 'load_credentials'),
            patch.object(jsearch, 'load_plan', return_value=(self.settings, self.plan)),
            patch.object(jsearch.requests, 'Session', return_value=self.session),
            patch.object(store, 'now', return_value=STAMP),
            patch('sys.argv', argv),
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            collector.main()
        # All 52 queries are planned; the guard, not the plan check, bounds it.
        self.assertLessEqual(self.guard.credits, 5)

    def test_a_crash_mid_run_still_seals_the_day(self):
        """Boards are committed one at a time, so a crash leaves the log longer.

        A manifest that still describes the file as it was makes the store fail
        its own integrity check, and the next run cannot rebuild from it. The
        seal has to survive a failure anywhere, including before the search
        block has bound the statistics it reports.
        """
        source = Source('direct', 'company_sources', 'sample', 'Sample', 'ashby', '', {})
        direct = Mock(jobs=[], rejected=[], requests=1, etag=None, last_modified=None, listed=None)
        direct.run.side_effect = RuntimeError('board exploded after the first store')
        configs = {'discovery_queries.toml': {},
                   'sources_search.toml': {'search': {'jsearch': SEARCH}}}
        argv = ['collector', '--db', str(self.db_path), '--jsearch-budget', '0',
                '--output', str(self.root / 'crash')]
        with (
            patch.object(collector, 'Collector', return_value=direct),
            patch.object(collector, 'load_sources', return_value=[source]),
            patch.object(collector, 'config', side_effect=configs.__getitem__),
            patch.object(collector, 'RequestGuard', return_value=self.guard),
            patch.object(collector, 'load_credentials'),
            patch.object(store, 'now', return_value=STAMP),
            patch('sys.argv', argv),
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            with self.assertRaises(BaseException):
                collector.main()
        # Sealed on the way out, so the store still verifies against itself.
        self.assertEqual(store.verify(), [(STAMP[:10], 'ok')])

    def test_backfill_alone_still_carries_the_functional_plan(self):
        """`--backfill` on its own must not be a silent no-op.

        `--jsearch-only` sets `--jsearch`, so the workflow's sweep was never
        affected, but selecting the functional queries listed only the flags
        that turn paid search on. A bare `--backfill` therefore ran no queries
        and reported success for doing nothing.
        """
        asked = []
        self.session.get.side_effect = lambda url, **kw: (
            asked.append(parse_qs(urlsplit(url).query)['query'][0])
            or self.response([job(employer_name='Sample')]))
        configs = {'discovery_queries.toml': {},
                   'sources_search.toml': {'search': {'jsearch': SEARCH}}}
        argv = ['collector', '--backfill', '--jsearch-budget', '2',
                '--db', str(self.db_path), '--output', str(self.root / 'sweep')]
        with (
            patch.object(collector, 'load_sources', return_value=[]),
            patch.object(collector, 'config', side_effect=configs.__getitem__),
            patch.object(collector, 'RequestGuard', return_value=self.guard),
            patch.object(collector, 'load_credentials'),
            patch.object(jsearch, 'load_plan',
                         return_value=(self.settings, [replace(self.plan[0], pages=1)])),
            patch.object(jsearch.requests, 'Session', return_value=self.session),
            patch.object(store, 'now', return_value=STAMP),
            patch('sys.argv', argv),
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            collector.main()
        self.assertEqual(asked, [self.plan[0].query])

    def test_backfill_uses_the_deeper_query_guard(self):
        observed = []
        configs = {'discovery_queries.toml': {},
                   'sources_search.toml': {'search': {'jsearch': SEARCH}}}
        argv = ['collector', '--backfill', '--jsearch-budget', '320',
                '--db', str(self.db_path), '--output', str(self.root / 'deep-sweep')]

        def capture(queries, *args, **kwargs):
            observed.extend(q.pages for q in queries)
            return [], {'jsearch_queries_planned': len(queries)}

        with (
            patch.object(collector, 'load_sources', return_value=[]),
            patch.object(collector, 'config', side_effect=configs.__getitem__),
            patch.object(collector, 'RequestGuard', return_value=self.guard),
            patch.object(collector, 'load_credentials'),
            patch.object(jsearch, 'collect', side_effect=capture),
            patch.object(store, 'now', return_value=STAMP),
            patch('sys.argv', argv),
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            collector.main()

        self.assertEqual(observed, [self.settings['backfill_max_pages_per_query']] * len(self.plan))

    def test_backfill_rejects_no_store_before_any_paid_request(self):
        with patch('sys.argv', ['collector', '--backfill', '--no-store']), \
             self.assertRaises(SystemExit):
            collector.main()
        self.session.get.assert_not_called()

    def test_collector_runs_direct_then_functional_then_configured_company(self):
        source = Source('direct', 'company_sources', 'sample', 'Sample', 'ashby', '', {})
        direct = Mock(jobs=[], rejected=[], requests=1, etag=None, last_modified=None, listed=None)
        order = []
        direct.run.side_effect = lambda: (order.append('direct') or ('complete', ''))
        def search_response(url, **kwargs):
            query = parse_qs(urlsplit(url).query)['query'][0]
            order.append(query)
            return self.response([job(employer_name='Sample')])
        self.session.get.side_effect = search_response
        discovery = {'company_fallbacks': [{'company_key': 'sample', 'mode': 'supplement',
                                           'employer_aliases': ['Sample']}]}
        configs = {'discovery_queries.toml': discovery, 'sources_search.toml': {'search': {'jsearch': SEARCH}}}
        output = self.root / 'output'
        with patch.object(collector, 'Collector', return_value=direct), \
             patch.object(collector, 'load_sources', return_value=[source]), \
             patch.object(collector, 'config', side_effect=configs.__getitem__), \
             patch.object(collector, 'RequestGuard', return_value=self.guard), \
             patch.object(collector, 'load_credentials'), \
             patch.object(jsearch, 'load_plan',
                          return_value=(self.settings, [replace(self.plan[0], pages=1)])), \
             patch.object(jsearch.requests, 'Session', return_value=self.session), \
             patch.object(store, 'now', return_value=STAMP), \
             patch('sys.argv', ['collector', '--jsearch', '--db', str(self.db_path), '--output', str(output)]), \
             patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(collector.main(), 0)
        self.assertEqual(order, ['direct', self.plan[0].query, 'Sample'])
        manifest = json.loads(store.manifest_path(STAMP).read_text())
        self.assertEqual(manifest['jsearch_queries_completed'], 2)
        self.assertEqual(manifest['jsearch_jobs_unique'], 1)
        self.assertEqual(len(list((store.LOG / 'runs').glob('*.ndjson.gz'))), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)

    def test_paging_advances_and_stops_on_a_short_page(self):
        """Depth is discovered: full pages advance, a short page ends it."""
        full = [self.response([job(f'{page}-{i}') for i in range(10)]) for page in range(3)]
        self.session.get.side_effect = full + [self.response([job('last')])]
        _, stats = self.collect([jsearch.Query('RTL Design Engineer', 40, 'A')])
        asked = [parse_qs(urlsplit(c.args[0]).query) for c in self.session.get.call_args_list]
        self.assertEqual([a['num_pages'] for a in asked], [['1']] * 4)
        self.assertEqual([a.get('page', ['1'])[0] for a in asked], ['1', '2', '3', '4'])
        self.assertEqual(stats['jsearch_jobs_raw'], 31)
        self.assertEqual(self.guard.credits, 4)

    def test_runaway_guard_stops_a_provider_that_never_runs_short(self):
        """A cursor that never ends must not spend the day on one query."""
        self.session.get.side_effect = [
            self.response([job(f'{page}-{i}') for i in range(10)]) for page in range(99)]
        _, stats = self.collect([jsearch.Query('RTL Design Engineer', 6, 'A')])
        self.assertEqual(self.guard.credits, 6)
        self.assertIn('Runaway guard', stats['jsearch_queries'][0]['reason'])

    def test_a_failed_page_costs_one_credit(self):
        self.session.get.side_effect = requests.Timeout('secret-like exception text')
        _, stats = self.collect([jsearch.Query('RTL Design Engineer', 40, 'A')])
        self.assertEqual(stats['jsearch_failures'], 1)
        self.assertEqual(stats['jsearch_pages_used'], 1)
        self.assertEqual(self.guard.credits, 1)

    def test_a_short_first_page_stays_one_call(self):
        self.session.get.return_value = self.response([job()])
        self.collect([jsearch.Query('DFT Engineer', 40, 'B')])
        self.assertEqual(self.session.get.call_count, 1)
        self.assertNotIn('page', parse_qs(urlsplit(self.session.get.call_args.args[0]).query))

    def test_tiers_are_paged_breadth_first_in_rank_order(self):
        """Tier A exhausts before tier B starts, and neither starves the other.

        Running one query to its end before the next begins would spend the
        budget depth first, so the tail of the plan would go unreached every
        day -- always the same queries.
        """
        self.session.get.side_effect = lambda url, **kw: self.response(
            [job(f'{parse_qs(urlsplit(url).query)["query"][0]}-'
                 f'{parse_qs(urlsplit(url).query).get("page", ["1"])[0]}')]
            if parse_qs(urlsplit(url).query).get('page', ['1'])[0] != '1'
            else [job(f'{parse_qs(urlsplit(url).query)["query"][0]}-{i}') for i in range(10)])
        self.collect([jsearch.Query('first A', 40, 'A'), jsearch.Query('second A', 40, 'A'),
                      jsearch.Query('only B', 40, 'B')])
        asked = [(parse_qs(urlsplit(c.args[0]).query)['query'][0],
                  parse_qs(urlsplit(c.args[0]).query).get('page', ['1'])[0])
                 for c in self.session.get.call_args_list]
        # Both tier A queries take page 1 before either takes page 2, and tier B
        # is not reached until tier A has finished.
        self.assertEqual(asked, [('first A', '1'), ('second A', '1'),
                                 ('first A', '2'), ('second A', '2'),
                                 ('only B', '1'), ('only B', '2')])
