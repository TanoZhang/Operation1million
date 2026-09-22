"""Regression contracts for B73-B84, using offline state and loopback HTTP."""
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import random
import sqlite3
import string
import tempfile
import threading
from types import SimpleNamespace
from urllib.request import urlopen
import unittest
from unittest.mock import patch

from jobdisco import applications, collection_policy, jsearch, query_catalog, review, store, validate_sources
from jobdisco.validate_sources import Source


class AuditRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='jobdisco-regressions-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, field, value in ((store, 'ROOT', self.root), (store, 'LOG', self.root / 'history')):
            patcher = patch.object(target, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.path = self.make_database('index.sqlite')
        self.db = store.connect(self.path)
        self.addCleanup(self.db.close)
        self.source = Source('ashby:fixture', 'company_sources', 'fixture', 'Fixture', 'ashby',
                             'https://example.test/jobs', {})
        self.stamp = datetime.now(timezone.utc) - timedelta(seconds=1)

    def make_database(self, name):
        path = self.root / name
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('fixture', 'Fixture')")
        store.migrate(path)
        return path

    def row(self, ident, address=None, **extra):
        result = dict(company_key='fixture', company_name='Fixture', provider_key='ashby',
                      source_job_id=ident, url=address or f'https://example.test/{ident}',
                      title='RTL Design Engineer', location='US', posted_at=None, raw={})
        result.update(extra)
        return result

    def persist(self, rows, stamp=None):
        stamp = (stamp or self.stamp).isoformat()
        result = store.record_source(self.db, self.source, rows, 'partial', 'full', 1, stamp=stamp)
        store.append_log(self.db, result['new_urls'] + result['changed_urls'], result['closed_urls'],
                         stamp, seen_urls=result['seen_urls'], source_id=self.source.source_id, allow_sealed=True)
        self.db.commit()
        return result

    def probe(self, html, provider='apple_jobs'):
        item = Source('fixture', 'company_direct_sources', 'fixture', 'Fixture', provider,
                      'https://example.test/jobs', {})
        policy_type = collection_policy.SourcePolicy
        session = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
            status_code=200, text=html, headers={'content-type': 'text/html'}))
        with patch.object(validate_sources, 'SourcePolicy',
                          side_effect=lambda s, d: policy_type(s, d, path=self.root / 'pause.sqlite')), \
             patch.object(collection_policy, 'request_interval', return_value=1), \
             patch.object(validate_sources.time, 'sleep'):
            return validate_sources.validate(item, session)

    def test_published_source_pause_is_merged_without_shortening_local_pause(self):
        local, remote = self.root / 'local.sqlite', self.root / 'remote.sqlite'
        for path, rows in ((local, [('a', 300, 'local'), ('c', 100, 'old local')]),
                           (remote, [('a', 200, 'older'), ('b', 400, 'published'),
                                     ('c', 500, 'new published')])):
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE source_pauses (company_key TEXT PRIMARY KEY, retry_at REAL, reason TEXT)')
                db.executemany('INSERT INTO source_pauses VALUES (?, ?, ?)', rows)
        collection_policy.merge_source_pauses(local, remote)
        with closing(sqlite3.connect(local)) as db:
            self.assertEqual(db.execute('SELECT * FROM source_pauses ORDER BY company_key').fetchall(),
                             [('a', 300, 'local'), ('b', 400, 'published'),
                              ('c', 500, 'new published')])

    def test_bad_source_fields_do_not_abort_the_remaining_report(self):
        bad = Source('bad', 'company_sources', 'fixture', 'Fixture', 'workday', 'https://example.test',
                     {'tenant': 'fixture'})
        output = self.root / 'validation.csv'
        session = SimpleNamespace(headers={})
        calls = []
        original = validate_sources.validate
        def probe(item, client):
            calls.append(item.source_id)
            if item.source_id == 'bad':
                return original(item, client)
            result = original(bad, client)
            result['source_id'] = item.source_id
            return result
        with patch.object(validate_sources, 'load_sources', return_value=[bad, self.source]), \
             patch.object(validate_sources.requests, 'Session', return_value=session), \
             patch.object(validate_sources, 'OUT_CSV', output), \
             patch.object(validate_sources, 'validate', side_effect=probe), redirect_stdout(io.StringIO()):
            self.assertEqual(validate_sources.main(), 0)
        self.assertEqual(calls, ['bad', self.source.source_id])
        self.assertIn('KeyError', output.read_text())
        self.assertIn(self.source.source_id, output.read_text())

    def test_empty_catalog_writes_a_valid_empty_report(self):
        output = self.root / 'validation.csv'
        output.write_text('prior report')
        with patch.object(validate_sources, 'load_sources', return_value=[]), \
             patch.object(validate_sources, 'OUT_CSV', output), redirect_stdout(io.StringIO()):
            self.assertEqual(validate_sources.main(), 0)
        self.assertEqual(len(output.read_text().splitlines()), 1)
        self.assertIn('source_id', output.read_text())

    def test_nested_apple_title_is_usable(self):
        result = self.probe('<a class="job-title" href="/en-us/details/123/rtl"><span>RTL Engineer</span></a>')
        self.assertEqual((result['verdict'], result['item_count']), ('usable', 1))

    def test_cdn_branding_does_not_pause_a_source(self):
        result = self.probe('<script src="https://example.test/akamai/metrics.js"></script>Careers', 'google_jobs')
        self.assertNotEqual(result['verdict'], 'paused')
        with closing(sqlite3.connect(self.root / 'pause.sqlite')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM source_pauses').fetchone()[0], 0)

    def test_challenge_precedes_successful_link_extraction(self):
        result = self.probe('<h1>Human verification</h1><a class="link-inline" href="/en-us/details/123/rtl">RTL</a>')
        self.assertEqual(result['verdict'], 'paused')
        with closing(sqlite3.connect(self.root / 'pause.sqlite')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM source_pauses').fetchone()[0], 1)

    def test_all_pattern_groups_reject_scalar_and_mixed_values(self):
        path = self.root / 'plan.toml'
        for group in ('exclude_employer_patterns', 'exclude_title_patterns', 'reject_title_patterns',
                      'keep_title_patterns', 'evidence_title_patterns', 'strong_terms', 'common_terms'):
            for value in ('"senior"', '["senior", 3]', '{bad="senior"}'):
                with self.subTest(group=group, value=value):
                    path.write_text(f'[filter]\n{group} = {value}\n')
                    with self.assertRaises(ValueError):
                        jsearch.load_plan(path)
        path.write_text('[filter]\nexclude_title_patterns = ["senior"]\n')
        self.assertFalse(jsearch.excluded('RTL Engineer', jsearch.load_plan(path)[0]['filter']))

    def test_query_migration_backups_are_per_database(self):
        paths = [self.root / 'first.sqlite', self.root / 'second.sqlite']
        with patch.object(query_catalog, 'ROOT', self.root):
            for path in paths:
                with closing(sqlite3.connect(path)) as db:
                    db.execute('CREATE TABLE companies (name TEXT)')
                query_catalog.migrate(path)
                self.assertEqual(len(query_catalog.load_queries(path)), 18)
        self.assertEqual(len(list((self.root / '.local/backups').glob('*before-search-queries.sqlite'))), 2)

    def assert_move(self, reverse):
        earlier = self.stamp - timedelta(days=10)
        a = self.row('A', 'https://example.test/shared', posted_at=earlier.isoformat(),
                     raw={'description': 'Requires 5 years of professional experience.'})
        self.persist([a], earlier)
        incoming = [self.row('A', 'https://example.test/new'), self.row('B', a['url'])]
        delta = self.persist(incoming[::-1] if reverse else incoming)
        self.assertEqual(delta['new'], 1)
        for path in (self.path, self.make_database('replay.sqlite')):
            if path != self.path:
                store.rebuild(path)
            with closing(store.connect(path)) as db:
                found = dict(db.execute('SELECT * FROM jobs WHERE source_job_id="A" AND closed_at IS NULL').fetchone())
                self.assertEqual(found['first_seen'], earlier.isoformat())
                self.assertEqual(found['posted_at'], earlier.isoformat())
                self.assertIn('5 years', found['raw'])
                b = db.execute('SELECT raw FROM jobs WHERE source_job_id="B"').fetchone()[0]
                self.assertNotIn('5 years', b)

    def test_moved_requisition_preserves_history_before_replacement(self):
        self.assert_move(False)

    def test_moved_requisition_preserves_history_after_replacement(self):
        self.assert_move(True)

    def test_rebuild_does_not_restore_stale_acceptance_over_new_rejection(self):
        before = self.stamp - timedelta(hours=2)
        self.persist([self.row('J', provider_key='jsearch')], before)
        seen = dict(provider_key='jsearch', source_job_id='J', url='https://example.test/J',
                    title='RTL Design Engineer', employer='Fixture', decision='', confidence=70)
        store.record_seen(self.db, [seen], before.isoformat())
        self.db.commit()
        store.export_seen(self.db)
        store.record_seen(self.db, [dict(seen, decision='required_experience_over_2_years')], self.stamp.isoformat())
        self.db.commit()
        store.rebuild(self.path)
        found = self.db.execute('SELECT decision, last_seen, first_seen FROM seen_jobs').fetchone()
        self.assertEqual(tuple(found), ('required_experience_over_2_years', self.stamp.isoformat(), before.isoformat()))
        state = applications.queue(self.path, self.root / 'decisions.ndjson')
        self.assertEqual(state['pending'] + state['backlog'], [])

    def test_partial_sharded_rescore_remains_verifiable_and_replayable(self):
        rng = random.Random(15)
        jobs = [self.row(str(i), 'https://example.test/' + ''.join(rng.choices(string.ascii_letters, k=120)))
                for i in range(20)]
        self.persist(jobs)
        before = list(map(tuple, self.db.execute('SELECT url, relevance FROM jobs ORDER BY url')))
        real_sync = store.os.fsync
        calls = 0
        def fail_second(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected second member failure')
            real_sync(fd)
        with patch.object(store, 'MAX_DAILY_LOG_BYTES', 300), patch.object(store, 'calculate_score', return_value=99), \
             patch.object(store, 'now', return_value=self.stamp.isoformat()), patch.object(store.os, 'fsync', side_effect=fail_second):
            with self.assertRaises(OSError):
                store.rescore(self.path)
        self.assertEqual(list(map(tuple, self.db.execute('SELECT url, relevance FROM jobs ORDER BY url'))), before)
        self.assertTrue(all(state == 'ok' for _, state in store.verify()), store.verify())
        with patch.object(store, 'calculate_score', return_value=99), \
             patch.object(store, 'now', return_value=(self.stamp + timedelta(days=1)).isoformat()):
            store.rescore(self.path)
        store.rebuild(self.path)
        self.assertEqual(self.db.execute('SELECT MIN(relevance), MAX(relevance) FROM jobs').fetchone()[:], (99, 99))

    def test_review_refresh_reloads_changed_filter_rules(self):
        self.persist([self.row('A')])
        plan = self.root / 'plan.toml'
        plan.write_text('[filter]\nexclude_title_patterns = []\n')
        real_load = jsearch.load_plan
        with patch.object(jsearch, 'load_plan', side_effect=lambda: real_load(plan)):
            server = review.make_server(self.path, self.root / 'decisions.ndjson', port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def get():
                with urlopen(f'http://127.0.0.1:{server.server_port}/api/queue', timeout=10) as response:
                    return json.load(response)
            try:
                self.assertEqual(len(get()['pending']), 1)
                plan.write_text('[filter]\nexclude_title_patterns = ["RTL"]\n')
                self.assertEqual(get()['pending'], [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
