"""Offline discovery, weighted quota, and shared durable-store regressions."""
import gzip
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from jobdisco import collector, jsearch, store
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
        self.assertEqual(guard_factory.call_args.kwargs['daily_limit'], 316)
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['jsearch_pages_used'], 1)
        self.assertEqual(manifest['jsearch_queries'][0]['date_posted'], 'week')
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
        self.guard = RequestGuard(self.root / 'usage.sqlite', daily_limit=316, target_limit=9500)
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
        """Expand one response per query into one per call.

        A query wider than max_pages_per_call is fetched in several calls, so a
        list holding one entry per query would run out partway through the first.
        """
        width = self.settings.get('max_pages_per_call', 10)
        expanded = []
        for query, response in zip(self.plan, responses):
            calls = max(1, -(-query.pages // width))
            expanded.extend([response] * calls)
        return expanded

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
        self.assertEqual(sum(q.pages for q in self.plan), 310)
        self.assertEqual(self.settings['monthly_target'], 9500)
        self.assertEqual(self.settings['daily_budget'], 9500 // 30)
        self.assertEqual(self.settings['billing_cycle_start_day'], 17)
        self.assertTrue(all(1 <= q.pages <= 20 for q in self.plan))

    def test_over_budget_refused_before_transport(self):
        with self.assertRaises(ValueError):
            jsearch.validate_budget(self.plan, 309)
        self.session.get.assert_not_called()

    def test_invalid_page_allocation_rejected(self):
        path = self.root / 'invalid.toml'
        for pages in (0, 21):
            path.write_text(f'[[query]]\nquery="RTL Engineer"\npages={pages}\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                jsearch.load_plan(path)

    def test_request_defaults_and_multi_page_batch_without_expansion(self):
        self.session.get.return_value = self.response([job(str(i)) for i in range(20)])
        rows, stats = self.collect([jsearch.Query('RTL Design Engineer', 2, 'A')])
        params = parse_qs(urlsplit(self.session.get.call_args.args[0]).query)
        self.assertEqual(params, {'query': ['RTL Design Engineer'], 'num_pages': ['2'],
                                 'country': ['us'], 'date_posted': ['today'],
                                 'employment_types': ['FULLTIME,INTERN']})
        self.assertEqual(len(rows), 20)
        self.assertEqual(stats['jsearch_pages_used'], 2)
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual(self.guard.attempts, 1)
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

    def test_empty_direct_inventory_closes_only_its_own_provider(self):
        self.session.get.return_value = self.response([job()])
        self.collect(self.plan[:1])
        source = Source('direct', 'company_sources', 'sample', 'Sample', 'ashby', '', {})
        row = jsearch.normalize_job(job('direct'), self.plan[0], {})
        row.update(company_key='sample', provider_key='ashby')
        store.record_source(self.db, source, [row], 'complete', 'full', 1)
        delta = store.record_source(self.db, source, [], 'complete', 'full', 1)
        self.assertEqual(delta['closed'], 1)
        self.assertIsNone(self.db.execute("SELECT closed_at FROM jobs WHERE provider_key='jsearch'").fetchone()[0])

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
        self.assertEqual(preview['pages_planned'], 310)
        self.assertFalse(missing.exists())
        self.assertFalse(store.LOG.exists())

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
        # The first query's pages in full, then only the batch the second lost:
        # a wide query no longer forfeits every page it asked for.
        width = self.settings['max_pages_per_call']
        self.assertEqual(stats['jsearch_pages_used'],
                         self.plan[0].pages + min(self.plan[1].pages, width))
        self.assertLess(stats['jsearch_pages_used'], sum(q.pages for q in self.plan[:2]))
        self.assertNotIn('secret-like', json.dumps(stats))
        manifest = store.write_manifest(self.db, STAMP, [], stats)
        for field in ('jsearch_queries_planned', 'jsearch_queries_completed', 'jsearch_pages_planned',
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

    def test_a_wide_query_is_split_and_asks_for_each_slice(self):
        self.session.get.return_value = self.response([job()])
        self.collect([jsearch.Query('RTL Design Engineer', 18, 'A')])
        self.assertEqual(self.session.get.call_count, 2)
        first, second = (parse_qs(urlsplit(c.args[0]).query)
                         for c in self.session.get.call_args_list)
        self.assertEqual(first['num_pages'], ['10'])
        self.assertNotIn('page', first)
        self.assertEqual(second['num_pages'], ['8'])
        self.assertEqual(second['page'], ['11'])
        # The provider is asked for the same 18 pages either way.
        self.assertEqual(self.guard.credits, 18)

    def test_a_query_within_the_width_stays_one_call(self):
        self.session.get.return_value = self.response([job()])
        self.collect([jsearch.Query('DFT Engineer', 5, 'B')])
        self.assertEqual(self.session.get.call_count, 1)
        self.assertNotIn('page', parse_qs(urlsplit(self.session.get.call_args.args[0]).query))

    def test_a_failed_slice_costs_only_that_slice(self):
        self.session.get.side_effect = [self.response([job()]),
                                        requests.Timeout('provider gateway timeout')]
        _, stats = self.collect([jsearch.Query('RTL Design Engineer', 18, 'A')])
        self.assertEqual(stats['jsearch_failures'], 1)
        # Ten pages spent, not the eighteen the query asked for.
        self.assertEqual(stats['jsearch_pages_used'], 18)
        self.assertEqual(self.guard.credits, 18)

    def test_width_of_one_sends_a_call_per_page(self):
        self.settings = dict(self.settings, max_pages_per_call=1)
        self.client = jsearch.Client(SEARCH, self.settings, self.guard, session=self.session)
        self.session.get.return_value = self.response([job()])
        self.collect([jsearch.Query('RTL Design Engineer', 4, 'A')])
        self.assertEqual(self.session.get.call_count, 4)
        asked = [parse_qs(urlsplit(c.args[0]).query).get('page', ['1'])[0]
                 for c in self.session.get.call_args_list]
        self.assertEqual(asked, ['1', '2', '3', '4'])
