"""Job store and incremental strategy selection.

The incremental paths decide what a run is allowed to skip, so a bug here loses
postings silently. Each strategy is covered together with the rule that only a
complete pass may retire a posting.
"""
import gzip
import io
import json
import sqlite3
import types
import ast
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
import re
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from jobdisco import jsearch
from jobdisco import store
from jobdisco.collector import Collector
from jobdisco.validate_sources import Source

SOURCE = Source('ashby:matx', 'company_sources', 'matx', 'MatX', 'ashby',
                'https://api.ashbyhq.com/posting-api/job-board/matx', {})


def row(url, title='Engineer', posted=None, raw=None):
    return {'company_key': 'matx', 'company_name': 'MatX', 'provider_key': 'ashby',
            'title': title, 'location': 'Mountain View', 'url': url,
            'source_job_id': url.rsplit('/', 1)[-1], 'posted_at': posted,
            'raw': raw if raw is not None else {'id': url}}


class StoreTests(unittest.TestCase):
    def test_verify_cli_fails_on_an_invalid_manifest(self):
        with patch.object(store, 'verify', return_value=[('2026-09-18', 'MISMATCH')]), \
             patch.object(store, 'summary', return_value={}), \
             patch('sys.argv', ['job-store', '--verify']):
            self.assertEqual(store.main(), 1)

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        log_patcher = patch.object(store, 'LOG', Path(self.dir.name) / 'store')
        log_patcher.start()
        self.addCleanup(log_patcher.stop)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)

    def open_db(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        return db

    def test_the_whole_ranking_is_printed_when_no_limit_is_given(self):
        """`--ranked 0` means every open posting, and printed none of them.

        `ranked` reads a falsy limit as no limit, and that is the form the
        deployment notes hand an operator watching per-source outcomes. The CLI
        asked whether the number was truthy, so zero read as "not asked for":
        the one invocation meaning "show me everything" printed nothing, which
        looks exactly like a store holding no open postings.
        """
        db = self.open_db()
        store.record_source(db, SOURCE, [row(f'https://x/{i}', title=f'RTL Engineer {i}')
                                         for i in range(3)], 'complete', 'full', 1)
        db.commit()
        with patch('sys.argv', ['job-store', '--db', str(self.db_path), '--ranked', '0']), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(store.main(), 0)
        printed = out.getvalue()
        for i in range(3):
            self.assertIn(f'https://x/{i}', printed)

    def test_a_check_does_not_create_the_index_it_is_asked_about(self):
        """`--verify` reads the log; a restored copy may have no index at all.

        Opening one creates it, so the documented restore check left an empty
        database behind and then ended in a traceback about a missing `jobs`
        table, with its own verification result scrolled off above it.
        """
        absent = Path(self.dir.name) / 'absent.sqlite'
        with patch('sys.argv', ['job-store', '--db', str(absent), '--verify']), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(store.main(), 0)
        self.assertFalse(absent.exists(), 'the check created the database it checked')
        self.assertIn('no job index', out.getvalue())

    def test_first_pass_is_a_full_download_for_every_source(self):
        self.assertEqual(store.plan(SOURCE, {}), ('full', None))
        # A pass that did not complete must not become an incremental watermark.
        self.assertEqual(
            store.plan(SOURCE, {'ashby:matx': {'last_success_at': None, 'etag': 'W/"x"'}}),
            ('full', None))

    def test_strategy_follows_what_the_board_supports(self):
        done = {'last_success_at': '2026-09-16T00:00:00+00:00'}
        self.assertEqual(store.plan(SOURCE, {'ashby:matx': dict(done, etag='W/"x"')}),
                         ('conditional', 'W/"x"'))
        eightfold = replace(SOURCE, source_id='ef:q', provider_key='eightfold')
        # A newest-first board reads incrementally only while its last full
        # pass is recent; with none on record it is read in full (B51).
        recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.assertEqual(store.plan(eightfold, {'ef:q': done})[0], 'full')
        self.assertEqual(store.plan(eightfold, {'ef:q': dict(done, last_full_at=recent)})[0],
                         'since')
        sitemap = replace(SOURCE, source_id='rn', provider_key='renesas_careers')
        self.assertEqual(store.plan(sitemap, {'rn': done})[0], 'lastmod')
        # An unrecognised board is read in full rather than guessed at.
        self.assertEqual(store.plan(replace(SOURCE, provider_key='workday'),
                                    {'ashby:matx': done})[0], 'full')

    def test_new_then_unchanged_then_closed(self):
        db = self.open_db()
        baseline = [row(f'https://x/{i}') for i in range(1, 5)]
        # Explicit stamps rather than the wall clock. Three passes in a test
        # finish inside one clock tick on a platform whose now() is coarser
        # than a microsecond, and then first_seen == last_seen and an assertion
        # about time fails for a reason that has nothing to do with the store.
        first = store.record_source(db, SOURCE, baseline, 'complete', 'full', 2,
                                    stamp='2026-09-17T00:00:00+00:00')
        self.assertEqual((first['seen'], first['new'], first['closed']), (4, 4, 0))
        again = store.record_source(db, SOURCE, baseline, 'complete', 'full', 2,
                                    stamp='2026-09-18T00:00:00+00:00')
        self.assertEqual((again['seen'], again['new'], again['closed']), (4, 0, 0))
        gone = store.record_source(db, SOURCE, baseline[:3], 'complete', 'full', 1,
                                   stamp='2026-09-19T00:00:00+00:00')
        self.assertEqual((gone['new'], gone['closed']), (0, 1))
        self.assertIsNotNone(
            db.execute("SELECT closed_at FROM jobs WHERE url='https://x/4'").fetchone()[0])
        # first_seen records when we observed it, and survives later passes.
        seen = db.execute("SELECT first_seen, last_seen FROM jobs WHERE url='https://x/1'").fetchone()
        self.assertLess(seen['first_seen'], seen['last_seen'])

    def test_incomplete_pass_never_closes_a_posting(self):
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                            'complete', 'full', 2)
        first_success = db.execute('SELECT last_success_at FROM source_state').fetchone()[0]
        for status in ('partial', 'failed', 'paused', 'fallback'):
            with self.subTest(status=status):
                delta = store.record_source(db, SOURCE, [row('https://x/1')], status, 'full', 1)
                self.assertEqual(delta['closed'], 0)
                self.assertIsNone(db.execute(
                    "SELECT closed_at FROM jobs WHERE url='https://x/2'").fetchone()[0])
        # The watermark still points at the one complete pass, not at these.
        state = dict(db.execute('SELECT last_success_at, last_status FROM source_state').fetchone())
        self.assertEqual(state['last_status'], 'fallback')
        self.assertEqual(state['last_success_at'], first_success)

    def test_partial_pass_does_not_make_its_etag_a_completed_inventory(self):
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1')], 'complete', 'full', 1,
                            etag='old')
        store.record_source(db, SOURCE, [row('https://x/1')], 'partial', 'conditional', 1,
                            etag='new', note='Job cap reached')
        state = dict(db.execute('SELECT * FROM source_state').fetchone())
        self.assertNotEqual(store.plan(SOURCE, {SOURCE.source_id: state}),
                            ('conditional', 'new'))
        self.assertEqual(state['etag'], 'old')

    def test_partial_pass_closes_only_stale_urls_with_the_same_identity(self):
        db = self.open_db()
        old = dict(row('https://x/old'), source_job_id='stable-id')
        distinct = dict(row('https://x/distinct'), source_job_id='other-id')
        store.record_source(db, SOURCE, [old, distinct], 'complete', 'full', 1)
        db.execute('DELETE FROM job_identities WHERE source_job_id=?', ('stable-id',))
        current = dict(row('https://x/current'), source_job_id='stable-id')
        store.record_source(db, SOURCE, [current], 'partial', 'full', 1)

        states = {r['url']: r['closed_at'] for r in db.execute(
            'SELECT url, closed_at FROM jobs ORDER BY url')}
        self.assertIsNotNone(states['https://x/old'])
        self.assertIsNone(states['https://x/current'])
        self.assertIsNone(states['https://x/distinct'])

    def test_skipping_a_fetch_does_not_retire_a_listed_posting(self):
        db = self.open_db()
        baseline = [row(f'https://x/{i}') for i in range(1, 9)]
        store.record_source(db, SOURCE, baseline, 'complete', 'full', 2)
        self.assertEqual(store.known_urls(db, 'matx'), {r['url'] for r in baseline})
        # The board still lists all eight, but only the new one was downloaded.
        listed = {r['url'] for r in baseline} | {'https://x/9'}
        delta = store.record_source(db, SOURCE, [row('https://x/9')], 'complete', 'lastmod', 1,
                                    listed=listed)
        self.assertEqual((delta['seen'], delta['new'], delta['closed']), (9, 1, 0))
        self.assertEqual(db.execute('SELECT job_count FROM source_state WHERE source_id=?',
                                    (SOURCE.source_id,)).fetchone()[0], 9)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL')
                         .fetchone()[0], 9)
        # Skipped-but-listed postings still count as seen this pass.
        self.assertEqual(len({r[0] for r in db.execute('SELECT last_seen FROM jobs')}), 1)
        # Dropping out of the listing is what closes a posting.
        gone = store.record_source(db, SOURCE, [], 'complete', 'lastmod', 1,
                                   listed={f'https://x/{i}' for i in range(3, 10)})
        self.assertEqual(gone['closed'], 2)
        self.assertNotIn('https://x/1', store.known_urls(db, 'matx'),
                         'a relisted closed URL must be fetched and reopened')

    def open_db_for(self, company, name='catalog2.sqlite'):
        """A catalog holding one company, for a source that is not MatX."""
        path = Path(self.dir.name) / f'{company}-{name}'
        with closing(sqlite3.connect(path)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            blank.execute('INSERT INTO companies VALUES (?, ?)', (company, company.title()))
        store.migrate(path)
        db = store.connect(path)
        self.addCleanup(db.close)
        return db

    def test_relisted_skipped_job_reopens_and_survives_fresh_replay(self):
        db = self.open_db()
        baseline = [row(f'https://x/{i}') for i in range(4)]

        def persist(rows, listed=None):
            delta = store.record_source(db, SOURCE, rows, 'complete', 'lastmod', 1,
                                        listed=listed)
            store.append_log(db, delta['new_urls'] + delta['changed_urls'],
                             delta['closed_urls'], delta['stamp'], seen_urls=delta['seen_urls'])
            store.write_manifest(db, delta['stamp'], [])
            db.commit()
            return delta

        persist(baseline)
        first_seen = db.execute("SELECT first_seen FROM jobs WHERE url='https://x/3'").fetchone()[0]
        self.assertEqual(persist(baseline[:3])['closed'], 1)
        delta = persist([], {r['url'] for r in baseline})
        held = db.execute("SELECT closed_at, first_seen FROM jobs WHERE url='https://x/3'").fetchone()
        self.assertIsNone(held['closed_at'])
        self.assertEqual(held['first_seen'], first_seen)
        self.assertIn('https://x/3', delta['changed_urls'])
        rebuilt = Path(self.dir.name) / 'relisted.sqlite'
        with closing(sqlite3.connect(rebuilt)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.rebuild(rebuilt)
        with closing(store.connect(rebuilt)) as fresh:
            self.assertEqual(fresh.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL')
                             .fetchone()[0], 4)

    def test_partial_or_fused_pass_cannot_install_conditional_validators(self):
        db = self.open_db()
        baseline = [row(f'https://x/{i}') for i in range(4)]
        store.record_source(db, SOURCE, baseline, 'complete', 'full', 1,
                            etag='old', last_modified='old-date')
        for status in ('partial', 'failed', 'paused', 'complete'):
            with self.subTest(status=status):
                # "complete" is downgraded by the closure fuse for this empty board.
                delta = store.record_source(db, SOURCE, [], status, 'full', 1,
                                            etag='incomplete', last_modified='incomplete-date')
                state = dict(db.execute('SELECT * FROM source_state').fetchone())
                self.assertNotEqual(delta['status'], 'complete')
                self.assertEqual(state['etag'], 'old')
                self.assertEqual(state['last_modified'], 'old-date')
                self.assertEqual(store.plan(SOURCE, {SOURCE.source_id: state}), ('full', None))
        store.record_source(db, SOURCE, baseline, 'complete', 'full', 1,
                            etag='finished', last_modified='finished-date')
        self.assertEqual(db.execute('SELECT etag FROM source_state').fetchone()[0], 'finished')

    def test_listing_does_not_reopen_other_sources_or_identity_aliases(self):
        db = self.open_db()
        original = row('https://x/old')
        store.record_source(db, SOURCE, [original], 'partial', 'full', 1)
        db.execute('DELETE FROM job_identities')
        replacement = dict(original, url='https://x/current')
        foreign = dict(row('https://x/search-only'), provider_key='jsearch')
        store.record_source(db, replace(SOURCE, provider_key='jsearch'), [foreign],
                            'query_limited', 'full', 1)
        db.execute("UPDATE jobs SET closed_at='closed' WHERE url='https://x/search-only'")
        delta = store.record_source(db, SOURCE, [replacement], 'partial', 'full', 1,
                                    listed={'https://x/old', 'https://x/current', 'https://x/search-only'})
        self.assertEqual(delta['closed_urls'], ['https://x/old'])
        # The next pass may skip all details; durable identity mappings must
        # still prevent reopening the alias closed by the preceding pass.
        store.record_source(db, SOURCE, [], 'partial', 'full', 1,
                            listed={'https://x/old', 'https://x/current', 'https://x/search-only'})
        for url in ('https://x/old', 'https://x/search-only'):
            self.assertIsNotNone(db.execute('SELECT closed_at FROM jobs WHERE url=?', (url,)).fetchone()[0])

    def test_a_requisition_keeps_one_posting_through_an_edit(self):
        """Identity and content are separate questions, and both must hold.

        A board may retitle a posting, move it, rewrite its description and
        change the slug its URL is built from, all while it remains the same
        opening. Recognising it requires the requisition; keeping it current
        requires the write to update rather than ignore. Renesas publishes no
        id of its own, so before the requisition was read out of the URL this
        read as one arrival beside a posting nothing would list again.
        """
        source = Source('renesas', 'company_direct_sources', 'renesas', 'Renesas',
                        'renesas_careers', '', {})

        def posting(url, title, location, description, requisition):
            return {'url': url, 'company_key': 'renesas', 'company_name': 'Renesas',
                    'provider_key': 'renesas_careers', 'title': title,
                    'location': location, 'source_job_id': requisition,
                    'posted_at': None, 'raw': {'description': description}}

        db = self.open_db_for('renesas')
        before = posting('https://jobs.renesas.com/job/-in-tokyo-japan-jid-6866',
                         'RTL Engineer', 'Tokyo', 'Original text', '6866')
        store.record_source(db, source, [before], 'complete', 'full', 1)
        after = posting('https://jobs.renesas.com/job/senior-rtl-engineer-in-osaka-japan-jid-6866',
                        'Senior RTL Engineer', 'Osaka', 'Rewritten text', '6866')
        delta = store.record_source(db, source, [after], 'complete', 'full', 1,
                                    listed={after['url']})

        self.assertEqual((delta['new'], delta['closed']), (0, 0))
        self.assertEqual(delta['status'], 'complete')
        self.assertEqual(delta['closure_candidates'], 0)
        held = db.execute('SELECT url, title, location, raw FROM jobs').fetchall()
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]['title'], 'Senior RTL Engineer')
        self.assertEqual(held[0]['location'], 'Osaka')
        self.assertEqual(json.loads(held[0]['raw'])['description'], 'Rewritten text')

        # Without the requisition the same edit is two postings, one of them
        # no longer listed -- which is what reading it out of the URL prevents.
        blind = self.open_db_for('renesas', name='blind.sqlite')
        store.record_source(blind, source, [dict(before, source_job_id=None)],
                            'complete', 'full', 1)
        store.record_source(blind, source, [dict(after, source_job_id=None)],
                            'complete', 'full', 1)
        self.assertEqual(blind.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 2)

    def test_renesas_identity_is_its_requisition_not_its_slug(self):
        """Renesas publishes no id of its own and ends the slug with one.

        Without reading it the identity is the whole slug, which carries the
        title and the location, so a retitled or relocated posting reads as one
        withdrawal and one arrival -- the shape that once retired 48% of
        Apple's board. All 899 open Renesas postings carry the number.
        """
        from jobdisco.collector import html_job_id
        moved = 'https://jobs.renesas.com/job/senior-rtl-engineer-in-tokyo-japan-jid-6866'
        original = 'https://jobs.renesas.com/job/-in-hitachinaka-ibaraki-japan-jid-6866'
        self.assertEqual(html_job_id(original, 'renesas_careers'), '6866')
        self.assertEqual(html_job_id(moved, 'renesas_careers'), '6866')
        # A URL without one keeps the old behaviour rather than losing its id.
        plain = 'https://jobs.renesas.com/job/no-number-here'
        self.assertEqual(html_job_id(plain, 'renesas_careers'), 'no-number-here')
        # Another board's URLs are untouched.
        self.assertEqual(
            html_job_id('https://jobs.apple.com/en-us/details/200612345/us-manager', 'apple_jobs'),
            '200612345')

    def test_nothing_imports_what_the_package_does_not_declare(self):
        """A runner installs what the package declares and nothing else.

        Tests run before collection so that a broken build cannot reach the
        boards. A test that imported PyYAML -- present on the machine it was
        written on, absent from the package's dependencies -- failed the suite
        on the runner, and the first scheduled pass collected nothing at all.
        """
        root = Path(__file__).resolve().parents[1]
        declared = set()
        with (root / 'pyproject.toml').open('rb') as handle:
            project = tomllib.load(handle)['project']
        specs = list(project['dependencies'])
        for extra in project.get('optional-dependencies', {}).values():
            specs.extend(extra)
        for spec in specs:
            declared.add(re.split(r'[<>=!;\[ ]', spec)[0].lower())
        # A distribution may install a module under another name.
        declared |= {'bs4' if d == 'beautifulsoup4' else d for d in set(declared)}
        declared |= {'curl_cffi' if d == 'curl-cffi' else d for d in set(declared)}

        outside = {}
        for path in list((root / 'src').rglob('*.py')) + list((root / 'tests').rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    top = name.split('.')[0]
                    # tomllib is standard on 3.11+; guarded imports use tomli
                    # on 3.10, which this project also supports.
                    if top in sys.stdlib_module_names or top in {'jobdisco', 'tomllib'}:
                        continue
                    # Python 3.10 uses the declared tomli fallback; tomllib is
                    # standard-library code on the newer supported runtimes.
                    if top == 'tomllib' and 'tomli' in declared:
                        continue
                    if top.lower() not in declared:
                        outside.setdefault(top, set()).add(path.name)
        self.assertEqual(outside, {}, 'imported but not declared as a dependency')

    def test_documented_module_entry_points_actually_run(self):
        """`python -m jobdisco.store` is how a fresh machine is recovered.

        Without a `__main__` guard the module imports, runs nothing and exits
        zero, so the documented recovery step looked like it had worked and
        left an empty database behind.
        """
        # Only the modules that parse arguments; `validate_sources` takes none
        # and would contact every configured board.
        for module in ('jobdisco.store', 'jobdisco.collector'):
            done = subprocess.run([sys.executable, '-m', module, '--help'],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, module)
            self.assertIn('usage', done.stdout.lower(), module)

    def test_a_relative_age_does_not_rewrite_a_posting(self):
        """A board that recomputes an age must not restate the whole posting.

        Amazon publishes `updated_time` as "8 days", which becomes "9 days"
        with nothing about the posting having changed. A differing row is
        rewritten into the log in full, description and all: 9,993 rows and
        about 92 MB in a single pass, for a string `posted_at` already states.
        """
        db = self.open_db()
        first = row('https://x/1', raw={'description': 'Verification work',
                                        'posted_date': 'September 16, 2026',
                                        'updated_time': '8 days'})
        store.record_source(db, SOURCE, [first], 'complete', 'full', 1)
        aged = row('https://x/1', raw={'description': 'Verification work',
                                       'posted_date': 'September 16, 2026',
                                       'updated_time': '9 days'})
        self.assertEqual(
            store.record_source(db, SOURCE, [aged], 'complete', 'full', 1)['changed_urls'], [])
        self.assertNotIn('updated_time', store.slim({'updated_time': '9 days'}))
        # A real edit to the posting still counts.
        edited = row('https://x/1', raw={'description': 'Physical design work',
                                         'posted_date': 'September 16, 2026',
                                         'updated_time': '9 days'})
        self.assertEqual(
            store.record_source(db, SOURCE, [edited], 'complete', 'full', 1)['changed_urls'],
            ['https://x/1'])

    def test_a_rebuilt_database_keeps_the_scores(self):
        """A runner rebuilds from the log every run and never rescores.

        The score is computed on write, so replaying rows without it left every
        posting unscored -- a ranked view on a fresh machine was simply empty,
        and recomputing costs two minutes for the postings already held.
        """
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1', title='ASIC Design Verification Engineer')],
                            'complete', 'full', 1)
        scored = db.execute('SELECT relevance FROM jobs WHERE url=?', ('https://x/1',)).fetchone()[0]
        self.assertGreater(scored, 0)
        stamp = store.now()
        store.append_log(db, ['https://x/1'], [], stamp)
        store.write_manifest(db, stamp, [])
        rebuilt = Path(self.dir.name) / 'rebuilt.sqlite'
        with closing(sqlite3.connect(rebuilt)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(rebuilt)
        store.rebuild(rebuilt)
        with closing(store.connect(rebuilt)) as fresh:
            self.assertEqual(
                fresh.execute('SELECT relevance FROM jobs WHERE url=?', ('https://x/1',)).fetchone()[0],
                scored)

    def test_a_legacy_log_without_scores_is_scored_during_replay(self):
        import gzip
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1', title='ASIC Design Verification Engineer')],
                            'complete', 'full', 1)
        store.append_log(db, ['https://x/1'], [], store.now())
        path = store.daily_log(store.now())
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            records = [json.loads(line) for line in handle]
        for record in records:
            record.pop('relevance', None)
        path.write_bytes(gzip.compress(
            ''.join(json.dumps(record) + '\n' for record in records).encode('utf-8'),
            mtime=0))
        store.write_manifest(db, store.now(), [])

        rebuilt = Path(self.dir.name) / 'legacy-rebuilt.sqlite'
        with closing(sqlite3.connect(rebuilt)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(rebuilt)
        store.rebuild(rebuilt)

        with closing(store.connect(rebuilt)) as fresh:
            self.assertGreater(
                fresh.execute('SELECT relevance FROM jobs WHERE url=?', ('https://x/1',)).fetchone()[0],
                0)

    def test_unchanged_board_refreshes_without_closing(self):
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                            'complete', 'full', 2, etag='W/"one"',
                            stamp='2026-09-18T00:00:00+00:00')
        before = db.execute('SELECT MAX(last_seen) FROM jobs').fetchone()[0]
        delta = store.touch_source(db, SOURCE, 'conditional', 1,
                                   stamp='2026-09-19T00:00:00+00:00')
        self.assertEqual((delta['seen'], delta['new'], delta['closed']), (2, 0, 0))
        self.assertGreater(db.execute('SELECT MIN(last_seen) FROM jobs').fetchone()[0], before)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL')
                         .fetchone()[0], 2)
        # A 304 carries no validator of its own, so the stored one is kept.
        self.assertEqual(db.execute('SELECT etag FROM source_state').fetchone()[0], 'W/"one"')

    def test_every_persist_path_returns_the_same_delta_shape(self):
        """A 304 is the ordinary daily pass, not a rare one.

        The collector reads the returned status to see whether the closure fuse
        downgraded a source. When the unchanged path returned a shorter dict the
        whole run died on the first board that answered 304 -- after the boards
        were already stored, so the data survived and only the report was lost.
        """
        db = self.open_db()
        recorded = store.record_source(db, SOURCE, [row('https://x/1')],
                                       'complete', 'full', 1, etag='W/"one"')
        touched = store.touch_source(db, SOURCE, 'conditional', 1)
        self.assertEqual(set(recorded), set(touched))
        self.assertEqual(touched['status'], 'unchanged')
        self.assertFalse(touched['closure_fused'])

    def test_relative_and_lastmod_values_are_kept_verbatim(self):
        db = self.open_db()
        store.record_source(db, SOURCE, [
            row('https://x/1', raw={'postedOn': 'Posted 7 Days Ago'}),
            row('https://x/2', raw={'lastmod': '2026-09-16T07:05:26Z'}),
        ], 'complete', 'full', 1)
        kept = dict(db.execute(
            "SELECT posted_relative, posted_at FROM jobs WHERE url='https://x/1'").fetchone())
        self.assertEqual(kept['posted_relative'], 'Posted 7 Days Ago')
        # A relative phrase is never promoted into an absolute timestamp.
        self.assertIsNone(kept['posted_at'])
        self.assertEqual(db.execute("SELECT lastmod FROM jobs WHERE url='https://x/2'")
                         .fetchone()[0], '2026-09-16T07:05:26Z')


class LogRoundTripTests(unittest.TestCase):
    def test_reused_url_does_not_redirect_old_requisition_over_its_replacement(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        stamp = store.now()
        old = dict(row('https://x/shared', raw={'description': 'Old requirements'}),
                   source_job_id='old')
        new = dict(row('https://x/shared', raw={'summary': 'New requirements'}),
                   source_job_id='new')
        for posting in (old, new):
            delta = store.record_source(db, SOURCE, [posting], 'partial', 'full', 1, stamp=stamp)
            store.append_log(db, delta['new_urls'] + delta['changed_urls'], [], stamp)
        stored = db.execute('SELECT raw FROM jobs WHERE url=?', (new['url'],)).fetchone()
        self.assertNotIn('Old requirements', stored[0])
        store.write_manifest(db, stamp, [])
        db.commit()
        fresh = Path(self.dir.name) / 'replacement.sqlite'
        store.bootstrap(fresh)
        rebuilt = store.connect(fresh)
        self.addCleanup(rebuilt.close)
        for index in (db, rebuilt):
            with self.subTest(rebuilt=index is rebuilt):
                self.assertIsNone(index.execute(
                    "SELECT url FROM job_identities WHERE source_job_id='old'").fetchone())
                moved = dict(old, url='https://x/moved-old')
                store.record_source(index, SOURCE, [moved], 'partial', 'full', 1)
                self.assertEqual(index.execute(
                    "SELECT source_job_id FROM jobs WHERE url='https://x/shared'").fetchone()[0], 'new')
                self.assertEqual(index.execute(
                    "SELECT source_job_id FROM jobs WHERE url='https://x/moved-old'").fetchone()[0], 'old')

    """The log is what survives between runs, so replaying it must restore the store.

    A scheduled runner starts with no database at all. If a replay lost or altered
    a posting, every run would rediscover it as new and the incremental strategies
    would be built on a false baseline.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)
        self.log = Path(self.dir.name) / 'store'
        patcher = patch.object(store, 'LOG', self.log)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_day(self):
        import gzip
        path = next(iter((self.log / 'runs').glob('*.ndjson.gz')))
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return [l for l in f.read().splitlines() if l.strip()]

    def snapshot(self, path):
        with closing(store.connect(path)) as db:
            return [tuple(r) for r in db.execute(
                'SELECT url, company_key, title, location, posted_at, posted_relative,'
                ' lastmod, first_seen, closed_at FROM jobs ORDER BY url')]

    def test_replaying_the_log_restores_every_posting_and_closure(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        baseline = [row(f'https://x/{i}') for i in range(1, 5)]
        first = store.record_source(db, SOURCE, baseline, 'complete', 'full', 2)
        store.append_log(db, first['new_urls'], first['closed_urls'], first['stamp'])
        gone = store.record_source(db, SOURCE, baseline[:3], 'complete', 'full', 1)
        store.append_log(db, gone['new_urls'], gone['closed_urls'], gone['stamp'])
        store.export_state(db)
        store.write_manifest(db, first['stamp'], [])
        db.commit()
        expected = self.snapshot(self.db_path)
        self.assertEqual(len(expected), 4)

        # A fresh runner: the catalog exists, the collected data does not.
        fresh = Path(self.dir.name) / 'fresh.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            blank.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        counts = store.rebuild(fresh)
        # `seen` counts rows restored from the snapshot under operational/,
        # which a log-only fixture does not carry.
        self.assertEqual(counts, {'jobs': 4, 'events': 1, 'sources': 1, 'seen': 0})
        self.assertEqual(self.snapshot(fresh), expected)

    def test_log_keeps_the_whole_posting_and_drops_only_noise(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        raw = {'id': 'abc', 'department': 'Hardware', 'employmentType': 'FULL_TIME',
               # Worth keeping however long it is: this is the job.
               'descriptionPlain': 'x' * 12000, 'requirements': 'r' * 4000,
               'salary_min_value': 180000, 'payTransparencyMaxSalary': 240000,
               # Says nothing about the job.
               'descriptionHtml': '<p>' + 'x' * 12000 + '</p>', 'benefits': 'y' * 900,
               'employer_logo': 'https://cdn/logo.png', 'employer_reviews': 4.2,
               'meta_data': {'icims': {'jps_is_public': True}}, 'solrScore': 0.8,
               'html': '<tr>row markup</tr>'}
        delta = store.record_source(db, SOURCE, [row('https://x/1', raw=raw)],
                                    'complete', 'full', 1)
        store.append_log(db, delta['new_urls'], delta['closed_urls'], delta['stamp'])
        logged = json.loads(self.read_day()[0])['raw']
        # The description survives at full length; a length rule would have cut it.
        self.assertEqual(len(logged['descriptionPlain']), 12000)
        self.assertEqual(len(logged['requirements']), 4000)
        self.assertEqual(logged['salary_min_value'], 180000)
        self.assertEqual(logged['payTransparencyMaxSalary'], 240000)
        self.assertEqual(logged['department'], 'Hardware')
        for noise in ('descriptionHtml', 'benefits', 'employer_logo', 'employer_reviews',
                      'meta_data', 'solrScore', 'html'):
            self.assertNotIn(noise, logged)
        # An uncatalogued field is kept rather than silently dropped.
        self.assertEqual(store.slim({'someNewProviderField': 'v'}),
                         {'someNewProviderField': 'v'})

    def test_explicit_empty_identities_do_not_replace_the_canonical_url(self):
        import gzip
        base = {
            'type': 'job', 'company_key': 'matx', 'provider_key': 'ashby',
            'title': 'Engineer', 'location': 'Mountain View',
            'source_job_id': 'same-id', 'posted_at': None,
            'posted_relative': None, 'lastmod': None,
            'first_seen': '2026-09-17T00:00:00+00:00',
            'last_seen': '2026-09-18T00:00:00+00:00',
            'closed_at': None, 'raw': {'id': 'same-id'},
        }
        canonical = dict(base, url='https://x/current', identities=[{
            'provider_key': 'ashby', 'scope': 'matx',
            'source_job_id': 'same-id',
        }])
        stale = dict(base, url='https://x/stale', identities=[])
        # Today, not a literal: a manifest may only be written for a day that
        # has not ended, so a fixed date here is a fuse with a known burn time.
        today = store.now()[:10]
        path = self.log / 'runs' / f'{today}.ndjson.gz'
        path.parent.mkdir(parents=True)
        with gzip.open(path, 'wt', encoding='utf-8') as handle:
            handle.write(json.dumps(canonical) + '\n')
            handle.write(json.dumps(stale) + '\n')
        with closing(store.connect(self.db_path)) as db:
            store.write_manifest(db, f'{today}T00:00:00+00:00', [])

        store.rebuild(self.db_path)

        with closing(store.connect(self.db_path)) as db:
            mapped = db.execute(
                'SELECT url FROM job_identities WHERE provider_key=? AND scope=? AND source_job_id=?',
                ('ashby', 'matx', 'same-id')).fetchone()
        self.assertEqual(mapped['url'], 'https://x/current')

    def test_compact_score_events_override_legacy_scores_on_replay(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        delta = store.record_source(db, SOURCE, [row('https://x/1', title='Accountant')],
                                    'complete', 'full', 1)
        store.append_log(db, delta['new_urls'], [], delta['stamp'])
        db.execute("UPDATE jobs SET relevance=77 WHERE url='https://x/1'")
        self.assertEqual(store.append_scores(db, delta['stamp']), 1)
        store.write_manifest(db, delta['stamp'], [])
        db.commit()

        fresh = Path(self.dir.name) / 'score-events.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as rebuilt:
            self.assertEqual(rebuilt.execute(
                "SELECT relevance FROM jobs WHERE url='https://x/1'").fetchone()[0], 77)

    def test_large_current_day_log_rolls_to_a_verified_shard(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        first = store.record_source(db, SOURCE, [row('https://x/1')],
                                    'complete', 'full', 1)
        with patch.object(store, 'MAX_DAILY_LOG_BYTES', 1):
            store.append_log(db, first['new_urls'], [], first['stamp'])
            store.write_manifest(db, first['stamp'], [])
            second = store.record_source(db, SOURCE, [row('https://x/2')],
                                         'partial', 'full', 1)
            store.append_log(db, second['new_urls'], [], second['stamp'])
            store.write_manifest(db, second['stamp'], [])
        db.commit()

        self.assertEqual(store.verify(), [
            (first['stamp'][:10] + '-0001', 'ok'),
            (first['stamp'][:10], 'ok'),
        ])
        fresh = Path(self.dir.name) / 'sharded.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as rebuilt:
            self.assertEqual(rebuilt.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 2)

    def test_a_shard_replays_before_the_day_it_was_cut_from(self):
        """A shard holds the earlier records, so it has to be replayed first.

        The order comes from sorting the file names, where `2026-09-18-0001`
        precedes `2026-09-18` only because `-` sorts below `.`. Replaying them
        the other way round would resurrect what the rest of the day closed.
        """
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        live = [row(f'https://x/{i}') for i in range(5)]
        opened = store.record_source(db, SOURCE, live, 'complete', 'full', 1)
        with patch.object(store, 'MAX_DAILY_LOG_BYTES', 1):
            store.append_log(db, opened['new_urls'], [], opened['stamp'])
            store.write_manifest(db, opened['stamp'], [])
            # One posting drops off the board, so its closure lands in the day's
            # file, after the shard holding the row that opened it was cut.
            closed = store.record_source(db, SOURCE, live[:4], 'complete', 'full', 1)
            store.append_log(db, [], closed['closed_urls'], closed['stamp'])
            store.write_manifest(db, closed['stamp'], [])
        db.commit()
        self.assertEqual(closed['closed_urls'], ['https://x/4'])

        fresh = Path(self.dir.name) / 'ordered.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as rebuilt:
            self.assertIsNotNone(rebuilt.execute(
                'SELECT closed_at FROM jobs WHERE url=?', ('https://x/4',)).fetchone()[0])

    def test_a_second_shard_numbers_and_orders_after_the_first(self):
        """A busy day cuts more than one shard, and order still has to hold."""
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        stamps = []
        with patch.object(store, 'MAX_DAILY_LOG_BYTES', 1):
            for i in range(3):
                delta = store.record_source(db, SOURCE, [row(f'https://x/{i}')],
                                            'complete', 'full', 1)
                store.append_log(db, delta['new_urls'], [], delta['stamp'])
                store.write_manifest(db, delta['stamp'], [])
                stamps.append(delta['stamp'])
        db.commit()
        day = stamps[0][:10]
        names = sorted(p.name for p in (self.log / 'runs').glob('*.ndjson.gz'))
        self.assertEqual(names, [f'{day}-0001.ndjson.gz', f'{day}-0002.ndjson.gz',
                                 f'{day}.ndjson.gz'])
        self.assertTrue(all(state == 'ok' for _, state in store.verify()), store.verify())

        fresh = Path(self.dir.name) / 'two.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as rebuilt:
            self.assertEqual(rebuilt.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 3)

    def test_replay_applies_the_current_noise_policy(self):
        """A rebuild must hold what a live pass would, not what the log recorded.

        A runner rebuilds from the log every run. A line written before a field
        became noise still carries it, so replaying it verbatim put the field
        back, the next pass saw a difference that was only the policy, and the
        posting was rewritten -- every run, for ever. Amazon restated 15,148
        postings and 88 MB the pass after the field was dropped.
        """
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        store.record_source(db, SOURCE, [row('https://x/1', raw={'description': 'Work'})],
                            'complete', 'full', 1)
        db.commit()
        store.append_log(db, ['https://x/1'], [], store.now())
        # Rewrite the logged line as one recorded before the field was noise.
        log = store.daily_log(store.now())
        lines = gzip.decompress(log.read_bytes()).decode('utf-8').splitlines()
        aged = []
        for line in lines:
            record = json.loads(line)
            if record.get('type', 'job') == 'job':
                record['raw'] = dict(record['raw'], updated_time='8 days')
            aged.append(json.dumps(record, sort_keys=True))
        body = ''.join(line + chr(10) for line in aged)
        log.write_bytes(gzip.compress(body.encode('utf-8'), mtime=0))
        store.write_manifest(db, store.now(), [])

        fresh = Path(self.dir.name) / 'policy.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(fresh)
        store.rebuild(fresh)
        with closing(store.connect(fresh)) as rebuilt:
            stored = json.loads(rebuilt.execute(
                'SELECT raw FROM jobs WHERE url=?', ('https://x/1',)).fetchone()[0])
        self.assertNotIn('updated_time', stored)

    def test_verify_reports_a_log_without_a_manifest(self):
        path = self.log / 'runs' / '2026-09-18.ndjson.gz'
        path.parent.mkdir(parents=True)
        path.write_bytes(gzip.compress(b'', mtime=0))
        self.assertEqual(store.verify(), [('2026-09-18', 'missing-manifest')])

    def test_bootstrap_atomically_replaces_an_existing_derived_database(self):
        db = self.open_existing_db()
        db.execute("ALTER TABLE jobs ADD COLUMN impossible_stale_column TEXT")
        db.commit()
        db.close()

        counts = store.bootstrap(self.db_path)

        self.assertEqual(counts, {'jobs': 0, 'events': 0, 'sources': 0, 'seen': 0})
        with closing(store.connect(self.db_path)) as rebuilt:
            columns = {r['name'] for r in rebuilt.execute('PRAGMA table_info(jobs)')}
        self.assertIn('relevance', columns)
        self.assertNotIn('impossible_stale_column', columns)

    def open_existing_db(self):
        return store.connect(self.db_path)


class EarlyStopTests(unittest.TestCase):
    def setUp(self):
        robots = patch('jobdisco.collection_policy.robots_delay', return_value=None)
        robots.start()
        self.addCleanup(robots.stop)

    def test_sitemap_refetches_changed_known_and_missing_old_postings(self):
        source = replace(SOURCE, provider_key='renesas_careers')
        c = self.collector(source, 'lastmod', '2026-09-20T12:00:00+00:00')
        c.known = {'https://x/changed', 'https://x/stable', 'https://x/undated'}
        entries = [('changed', '2026-09-20T13:00:00Z'),
                   ('stable', '2026-09-19T00:00:00Z'),
                   ('missing', '2026-09-19T00:00:00Z'), ('undated', None)]
        xml = '<urlset>' + ''.join('<url><loc>https://x/' + name + '</loc>'
                                  + (f'<lastmod>{stamp}</lastmod>' if stamp else '')
                                  + '</url>' for name, stamp in entries) + '</urlset>'
        def fetch(url):
            return Mock(content=xml.encode()) if url == source.access_url else Mock(
                text='<h1>RTL Engineer</h1>')
        c.fetch = Mock(side_effect=fetch)
        self.assertEqual(c.collect_sitemap()[0], 'complete')
        self.assertEqual({r['url'] for r in c.jobs},
                         {'https://x/changed', 'https://x/missing', 'https://x/undated'})
        self.assertEqual(c.fetch.call_count, 4)

    def collector(self, source, strategy, watermark):
        args = Namespace(max_jobs=1000, max_pages=10, delay=0, timeout=1, retries=0,
                         source_state=Path(tempfile.gettempdir()) / 'unused_pauses.sqlite')
        c = Collector(source, args)
        c.session.request = Mock()
        self.addCleanup(c.session.close)
        c.strategy, c.watermark = strategy, watermark
        return c

    def response(self, data=None, status=200):
        r = Mock(status_code=status, text='',
                 headers={'content-type': 'application/json'})
        r.json.return_value = data or {}
        return r

    def position(self, ident, ts):
        return {'id': ident, 'name': 'Engineer', 'positionUrl': f'/careers/job/{ident}',
                'postedTs': ts, 'locations': ['San Diego']}

    def test_eightfold_stops_at_the_watermark_and_keeps_newer_rows(self):
        source = Source('ef:q', 'company_sources', 'qualcomm', 'Qualcomm', 'eightfold',
                        'https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com', {})
        # 1789516800 is newer than the watermark; 1600000000 is far older.
        c = self.collector(source, 'since', '2026-09-01T00:00:00+00:00')
        c.session.request.side_effect = [
            self.response({'data': {'count': 40, 'positions': [
                self.position('1', 1789516800), self.position('2', 1789516800)]}}),
            self.response({'data': {'count': 40, 'positions': [
                self.position('3', 1789516800), self.position('4', 1600000000)]}}),
            self.response({'data': {'count': 40, 'positions': [
                self.position('5', 1600000000)]}}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            status, _ = c.run()
        self.assertEqual(status, 'complete')
        # Stopped on the page that crossed the watermark; page 3 was never requested.
        self.assertEqual(c.session.request.call_count, 2)
        self.assertEqual([j['source_job_id'] for j in c.jobs], ['1', '2', '3'])

    def test_full_strategy_reads_every_page(self):
        source = Source('ef:q', 'company_sources', 'qualcomm', 'Qualcomm', 'eightfold',
                        'https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com', {})
        c = self.collector(source, 'full', None)
        c.session.request.side_effect = [
            self.response({'data': {'count': 3, 'positions': [
                self.position('1', 1789516800), self.position('2', 1600000000)]}}),
            self.response({'data': {'count': 3, 'positions': [self.position('3', 1600000000)]}}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            c.run()
        self.assertEqual(len(c.jobs), 3)

    def test_conditional_probe_short_circuits_on_304(self):
        c = self.collector(SOURCE, 'conditional', 'W/"stored"')
        c.session.request.return_value = self.response(status=304)
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('unchanged', ''))
        self.assertEqual(c.session.request.call_count, 1)
        self.assertEqual(c.jobs, [])
        self.assertNotIn('If-None-Match', c.session.headers)

    def test_a_post_board_is_not_probed_with_a_get(self):
        """The probe dropped the method, and a refused method is a day's pause.

        Workday answers a POST and carries an ETag like any other board, so it
        earns a conditional strategy and was then probed with a GET it refuses.
        A 405 pauses the source for 24 hours. A POST probe would cost as much as
        the pass it precedes, so such a board simply reads in full instead.
        """
        source = Source('wd:test', 'company_sources', 'sample', 'Sample', 'workday',
                        'https://sample.wd1.myworkdayjobs.com/External',
                        {'tenant': 'sample', 'site': 'External', 'workday_host': 'wd1'})
        c = self.collector(source, 'conditional', 'W/"stored"')
        c.session.request.return_value = self.response(
            {'total': 1, 'jobPostings': [{'title': 'Engineer',
                                          'externalPath': '/job/Engineer_R1'}]})
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(c.session.request.call_count, 1)
        self.assertEqual(c.session.request.call_args.args[0], 'POST')
        self.assertNotIn('If-None-Match', c.session.headers)
        self.assertEqual(len(c.jobs), 1)

    def test_a_renesas_posting_keeps_its_requisition_when_its_slug_changes(self):
        """The sitemap path never asked for the requisition the URL carries.

        `html_job_id` knows that Renesas ends its slug with the requisition, and
        knows it because a retitled or relocated posting otherwise reads as one
        withdrawal and one arrival. The sitemap collector never called it.
        """
        source = replace(SOURCE, provider_key='renesas_careers',
                         access_url='https://x/sitemap.xml')

        def pass_over(location):
            c = self.collector(source, 'full', None)
            sitemap = f'<urlset><url><loc>{location}</loc></url></urlset>'
            c.fetch = Mock(side_effect=lambda url: (
                Mock(content=sitemap.encode()) if url == source.access_url
                else Mock(text='<h1>RTL Design Engineer</h1>')))
            self.assertEqual(c.run()[0], 'complete')
            return c.jobs[0]

        first = pass_over('https://x/job/rtl-design-engineer-in-tokyo-japan-jid-6866')
        moved = pass_over('https://x/job/senior-rtl-engineer-in-osaka-japan-jid-6866')
        self.assertEqual(first['source_job_id'], '6866')
        self.assertEqual(moved['source_job_id'], '6866')
        self.assertNotEqual(first['url'], moved['url'])

    def test_sitemap_refetches_changed_known_and_discovers_old_unknown_urls(self):
        source = replace(SOURCE, provider_key='renesas_careers', access_url='https://x/sitemap.xml')
        c = self.collector(source, 'lastmod', '2026-09-18T00:00:00+00:00')
        c.known = {'https://x/unchanged', 'https://x/changed', 'https://x/undated'}
        entries = [('unchanged', '2026-09-17T00:00:00+00:00'),
                   ('changed', '2026-09-19T00:00:00+00:00'),
                   ('old-unknown', '2026-09-01T00:00:00+00:00'), ('undated', None)]
        sitemap = '<urlset>' + ''.join(
            f'<url><loc>https://x/{name}</loc>' + (f'<lastmod>{stamp}</lastmod>' if stamp else '')
            + '</url>' for name, stamp in entries) + '</urlset>'
        asked = []

        def fetch(url):
            asked.append(url)
            return Mock(content=sitemap.encode(), text='<h1>Updated RTL Engineer</h1>')

        with patch.object(c, 'fetch', side_effect=fetch):
            status, _ = c.collect_sitemap()
        self.assertEqual(status, 'complete')
        self.assertEqual(set(asked[1:]), {'https://x/changed', 'https://x/old-unknown', 'https://x/undated'})
        self.assertEqual(len(c.jobs), 3)

    def test_sitemap_lastmod_compares_instants_and_refetches_invalid_dates(self):
        source = replace(SOURCE, provider_key='renesas_careers', access_url='https://x/sitemap.xml')
        c = self.collector(source, 'lastmod', '2026-09-18T00:00:00+00:00')
        c.known = {'https://x/newer', 'https://x/older', 'https://x/invalid'}
        dates = {'newer': '2026-09-17T23:00:00-07:00',
                 'older': '2026-09-18T01:00:00+02:00', 'invalid': '0000-invalid'}
        xml = '<urlset>' + ''.join(f'<url><loc>https://x/{name}</loc><lastmod>{stamp}</lastmod></url>'
                                   for name, stamp in dates.items()) + '</urlset>'
        asked = []

        def fetch(url):
            asked.append(url)
            return Mock(content=xml.encode(), text='<h1>RTL Engineer</h1>')

        with patch.object(c, 'fetch', side_effect=fetch):
            c.collect_sitemap()
        self.assertEqual(set(asked[1:]), {'https://x/newer', 'https://x/invalid'})

    def test_full_sitemap_recovery_does_not_skip_known_details(self):
        source = replace(SOURCE, provider_key='renesas_careers', access_url='https://x/sitemap.xml')
        c = self.collector(source, 'full', None)
        c.known = {'https://x/known'}
        xml = b'<urlset><url><loc>https://x/known</loc><lastmod>2020-01-01</lastmod></url></urlset>'
        with patch.object(c, 'fetch', return_value=Mock(content=xml, text='<h1>Updated role</h1>')) as fetch:
            self.assertEqual(c.collect_sitemap()[0], 'complete')
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(c.jobs[0]['title'], 'Updated role')


class ClosingGuardTests(unittest.TestCase):
    """What may retire a posting.

    Closing is the destructive direction: a wrong closure hides a live job from
    the person using this. Each guard here corresponds to a pass that did not, or
    could not, see the whole board.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)
        self.db = store.connect(self.db_path)
        self.addCleanup(self.db.close)
        store.record_source(self.db, SOURCE, [row('https://x/1'), row('https://x/2')],
                            'complete', 'full', 2)

    def open_count(self):
        return self.db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]

    def test_early_stop_pass_never_closes(self):
        # 'since' reads only postings newer than the last pass and stops; on a quiet
        # day that is zero rows, which says nothing about what is still listed.
        delta = store.record_source(self.db, SOURCE, [], 'complete', 'since', 1)
        self.assertEqual(delta['closed'], 0)
        self.assertEqual(self.open_count(), 2)


    def test_search_results_never_close(self):
        # Paid search returns a slice of one query, not a company's board.
        jsearch = replace(SOURCE, provider_key='jsearch')
        delta = store.record_source(self.db, jsearch, [row('https://x/9')],
                                    'complete', 'full', 1)
        self.assertEqual(delta['closed'], 0)
        self.assertEqual(self.open_count(), 3)

    def test_a_full_enumeration_still_closes_what_vanished(self):
        baseline = [row(f'https://x/{i}') for i in range(1, 5)]
        store.record_source(self.db, SOURCE, baseline, 'complete', 'full', 1)
        delta = store.record_source(self.db, SOURCE, baseline[:3],
                                    'complete', 'full', 1)
        self.assertEqual(delta['closed'], 1)
        self.assertEqual(self.open_count(), 3)

    def test_exactly_twenty_five_percent_may_close(self):
        baseline = [row(f'https://x/{i}') for i in range(1, 9)]
        store.record_source(self.db, SOURCE, baseline, 'complete', 'full', 1)
        delta = store.record_source(self.db, SOURCE, baseline[:6],
                                    'complete', 'full', 1)
        self.assertEqual(delta['status'], 'complete')
        self.assertFalse(delta['closure_fused'])
        self.assertEqual(delta['closed'], 2)
        self.assertEqual(self.open_count(), 6)

    def test_large_complete_closure_is_downgraded_and_blocked(self):
        baseline = [row(f'https://x/{i}') for i in range(1, 9)]
        store.record_source(self.db, SOURCE, baseline, 'complete', 'full', 1,
                            stamp='2026-09-16T00:00:00+00:00')
        delta = store.record_source(self.db, SOURCE, baseline[:5],
                                    'complete', 'full', 1,
                                    stamp='2026-09-17T00:00:00+00:00')
        self.assertEqual(delta['status'], 'partial')
        self.assertTrue(delta['closure_fused'])
        self.assertEqual(delta['closure_candidates'], 3)
        self.assertEqual(delta['closure_ratio'], 3 / 8)
        self.assertEqual(delta['closed'], 0)
        self.assertEqual(self.open_count(), 8)
        state = self.db.execute(
            'SELECT last_status, last_success_at, note FROM source_state WHERE source_id=?',
            (SOURCE.source_id,)).fetchone()
        self.assertEqual(state['last_status'], 'partial')
        self.assertEqual(state['last_success_at'], '2026-09-16T00:00:00+00:00')
        self.assertIn('Closure fuse blocked 3 of 8', state['note'])

    def test_reported_empty_board_cannot_retire_an_existing_inventory(self):
        baseline = [row(f'https://x/{i}') for i in range(1, 9)]
        store.record_source(self.db, SOURCE, baseline, 'complete', 'full', 1)
        delta = store.record_source(self.db, SOURCE, [], 'complete', 'full', 1)
        self.assertEqual(delta['status'], 'partial')
        self.assertEqual(delta['closed'], 0)
        self.assertEqual(delta['closure_candidates'], 8)
        self.assertEqual(self.open_count(), 8)


class EmptyBoardTests(unittest.TestCase):
    """An empty listing is only trusted when the board confirms it.

    'complete' is what permits the store to retire a company's whole inventory, so
    a blank first page must not claim it on its own: that is also what a board
    looks like mid-deploy, or after a schema change we failed to parse.
    """

    def setUp(self):
        robots = patch('jobdisco.collection_policy.robots_delay', return_value=None)
        robots.start()
        self.addCleanup(robots.stop)

    def collector(self, provider='greenhouse', url='https://boards-api.greenhouse.io/v1/boards/x/jobs'):
        args = Namespace(max_jobs=1000, max_pages=5, delay=0, timeout=1, retries=0,
                         source_state=Path(tempfile.gettempdir()) / 'unused_pauses.sqlite')
        c = Collector(replace(SOURCE, provider_key=provider, access_url=url), args)
        c.session.request = Mock()
        self.addCleanup(c.session.close)
        return c

    def response(self, data):
        r = Mock(status_code=200, text='', headers={'content-type': 'application/json'})
        r.json.return_value = data
        return r

    def test_blank_first_page_without_a_count_is_not_complete(self):
        c = self.collector()
        c.session.request.return_value = self.response({'jobs': []})
        with patch('jobdisco.collector.time.sleep'):
            status, reason = c.run()
        self.assertEqual(status, 'partial')
        self.assertIn('no count', reason)
        self.assertEqual(c.jobs, [])

    def test_a_board_reporting_zero_is_believed(self):
        c = self.collector('eightfold', 'https://careers.x.com/api/pcsx/search?domain=x.com')
        c.session.request.return_value = self.response({'data': {'positions': [], 'count': 0}})
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('complete', ''))

    def test_a_blank_later_page_just_ends_pagination(self):
        """Nothing here contradicts the blank page, so it is the end of the list.

        This board states no count. It used to state 99 while listing one
        posting, which made it a board disagreeing with itself rather than one
        ending, and the case below is what that actually is.
        """
        c = self.collector('eightfold', 'https://careers.x.com/api/pcsx/search?domain=x.com')
        position = {'id': '1', 'name': 'Engineer', 'positionUrl': '/careers/job/1'}
        c.session.request.side_effect = [
            self.response({'data': {'positions': [position]}}),
            self.response({'data': {'positions': []}}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('complete', ''))
        self.assertEqual(len(c.jobs), 1)

    def test_a_board_that_stops_short_of_its_own_count_is_not_complete(self):
        """99 advertised and one listed is a board that broke, not one that ended.

        Completeness is what retires everything the pass did not list, and the
        provider's own number is the evidence that the pass did not see the
        board. The same number is already believed in the other direction: it
        is what ends pagination early at `offset >= total`.
        """
        c = self.collector('eightfold', 'https://careers.x.com/api/pcsx/search?domain=x.com')
        position = {'id': '1', 'name': 'Engineer', 'positionUrl': '/careers/job/1'}
        c.session.request.side_effect = [
            self.response({'data': {'positions': [position], 'count': 99}}),
            self.response({'data': {'positions': [], 'count': 99}}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            status, reason = c.run()
        self.assertEqual(status, 'partial')
        self.assertIn('99', reason)
        self.assertEqual(len(c.jobs), 1)


class RelevanceScoringTests(unittest.TestCase):
    """Scoring only ever adds, and ranks what it keeps.

    The point of a score rather than a yes/no is that a reader can start at the
    top, so the ordering matters as much as the cutoff.
    """

    def setUp(self):
        from jobdisco import jsearch
        self.jsearch = jsearch
        self.rules = jsearch.load_plan()[0]['filter']

    def posting(self, title, **raw):
        return {'title': title, 'raw': dict(raw)}

    def test_absent_terms_never_deduct(self):
        sparse = self.posting('Engineer', job_description='UVM testbench work.')
        verbose = self.posting('Engineer', job_description='UVM testbench work. ' + 'x' * 4000)
        # The same evidence scores the same however much other prose surrounds it.
        self.assertEqual(self.jsearch.relevance(sparse, self.rules)[0],
                         self.jsearch.relevance(verbose, self.rules)[0])

    def test_more_trade_vocabulary_scores_higher(self):
        one = self.posting('Engineer', job_description='Work with RTL.')
        several = self.posting('Engineer', job_description='RTL, UVM, SystemVerilog, AXI.')
        self.assertLess(self.jsearch.relevance(one, self.rules)[0],
                        self.jsearch.relevance(several, self.rules)[0])

    def test_more_distinct_terms_scores_higher_without_a_ceiling(self):
        """The count has to keep meaning something past the first few terms.

        A short-circuit at a fixed number of strong terms stopped it exactly
        where it started being informative: 798 live postings all read 100, the
        terms behind them ranging from six distinct to thirty-four, and nothing
        scored between 70 and 99. With it off, a posting that uses more of the
        vocabulary outranks one that uses less.
        """
        self.assertEqual(self.rules['certain_strong_hits'], 0)
        few = self.posting('Engineer', job_description='RTL, UVM, SystemVerilog.')
        many = self.posting('Engineer', job_description=(
            'RTL, UVM, SystemVerilog, AXI, testbench, tape-out, PrimeTime, '
            'SerDes, floorplan, synthesis, scan chain, coverage closure.'))
        lean = self.jsearch.relevance(few, self.rules)[0]
        rich = self.jsearch.relevance(many, self.rules)[0]
        self.assertGreater(rich, lean)
        self.assertLess(rich, 100)

    def test_the_short_circuit_still_works_when_it_is_asked_for(self):
        """Turning it off is a setting, not the removal of the mechanism."""
        rules = dict(self.rules, certain_strong_hits=6)
        loaded = self.posting('Engineer', job_description=(
            'RTL, UVM, SystemVerilog, AXI, testbench, tape-out, PrimeTime.'))
        self.assertEqual(self.jsearch.relevance(loaded, rules)[0], 100)

    def test_a_title_term_outweighs_the_same_term_in_the_body(self):
        in_title = self.posting('RTL Engineer', job_description='General duties.')
        in_body = self.posting('Engineer', job_description='General duties with RTL.')
        self.assertGreater(self.jsearch.relevance(in_title, self.rules)[0],
                           self.jsearch.relevance(in_body, self.rules)[0])

    def test_vocabulary_counts_wherever_the_publisher_put_it(self):
        # Some publishers put the substance in a skills array, not the prose.
        in_skills = self.posting('Engineer', job_description='Responsibilities.',
                                 skills=['RTL', 'SystemVerilog'])
        self.assertGreater(self.jsearch.relevance(in_skills, self.rules)[0], 0)

    def test_an_off_domain_posting_with_a_full_description_is_dropped(self):
        pharma = self.posting('Validation - Engineer I / II',
                              job_description='Batch records and clean room. ' * 200)
        self.assertEqual(self.jsearch.rejection_reason(pharma, self.rules), 'off_domain')

    def test_a_truncated_description_is_never_evidence_against(self):
        excerpt = self.posting('Staff Engineer', job_description='See full posting.')
        self.assertEqual(self.jsearch.rejection_reason(excerpt, self.rules), '')

    def test_a_title_that_names_the_work_settles_it_either_way(self):
        # Analog mixed-signal *verification* is wanted; an analog *designer* is not.
        keep = self.posting('Analog Mixed-Signal Design Verification Engineer')
        drop = self.posting('Analog IC Designer', skills=['RTL', 'SystemVerilog'])
        self.assertEqual(self.jsearch.rejection_reason(keep, self.rules), '')
        self.assertEqual(self.jsearch.rejection_reason(drop, self.rules), 'title_mismatch')


class HardExclusionTests(unittest.TestCase):
    """Exclusions answer whether the job is acceptable, not how relevant it is.

    They are checked before everything else, so no amount of matching vocabulary
    can bring back a posting that was declined on principle.
    """

    def setUp(self):
        from jobdisco import jsearch
        self.jsearch = jsearch
        self.rules = jsearch.load_plan()[0]['filter']

    def posting(self, title, **raw):
        return {'title': title, 'raw': dict(raw)}

    def test_a_management_title_is_declined_despite_matching_work(self):
        # 'verification' is a keep pattern, which would otherwise settle this.
        for title in ('Senior Manager, Design Verification',
                      'Director of Silicon Engineering',
                      'Head of Verification', 'VP of Hardware Engineering',
                      'Distinguished Engineer, SoC Verification'):
            with self.subTest(title=title):
                posting = self.posting(title, skills=['RTL', 'UVM', 'SystemVerilog'])
                self.assertEqual(self.jsearch.rejection_reason(posting, self.rules), 'excluded')

    def test_a_defence_programme_is_declined_despite_matching_work(self):
        for title in ('FPGA Engineer - Radar Systems',
                      'RTL Design Engineer, Mission Systems',
                      'Verification Engineer - Electronic Warfare',
                      'ASIC Engineer, Missile Defense'):
            with self.subTest(title=title):
                posting = self.posting(title, skills=['RTL', 'UVM', 'SystemVerilog'])
                self.assertEqual(self.jsearch.rejection_reason(posting, self.rules), 'excluded')

    def test_an_excluded_posting_scores_zero(self):
        # A stored ranking reads the number, so the number has to agree.
        loaded = self.posting('Engineering Manager, RTL Design',
                              job_description='RTL UVM SystemVerilog AXI testbench tape-out.')
        self.assertEqual(self.jsearch.relevance(loaded, self.rules)[0], 0)

    def test_allowed_individual_contributor_titles_are_untouched(self):
        for title in ('RTL Design Engineer', 'Design Verification Engineer',
                      'Principal Engineer, SoC', 'Staff FPGA Engineer'):
            with self.subTest(title=title):
                self.assertFalse(self.jsearch.excluded(title, self.rules))


class ScoreOnceTests(unittest.TestCase):
    """A posting is scored when it arrives, not on every pass that sees it.

    Every pass re-reads the whole board, so re-scoring unchanged postings would
    spend a minute a day recomputing the same numbers.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        # A rescore now writes its corrections to the log as well as to the
        # database, so the log this class writes to has to be its own.
        log_patcher = patch.object(store, 'LOG', Path(self.dir.name) / 'store')
        log_patcher.start()
        self.addCleanup(log_patcher.stop)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)
        self.db = store.connect(self.db_path)
        self.addCleanup(self.db.close)

    def silicon(self, url, title='RTL Design Engineer'):
        return dict(row(url, title=title),
                    raw={'job_description': 'UVM SystemVerilog AXI testbench tape-out.'})

    def stored(self, url):
        return self.db.execute('SELECT relevance FROM jobs WHERE url=?', (url,)).fetchone()[0]

    def test_a_new_posting_is_scored_and_a_repeat_pass_keeps_that_score(self):
        store.record_source(self.db, SOURCE, [self.silicon('https://x/1')], 'complete', 'full', 1)
        scored = self.stored('https://x/1')
        self.assertGreater(scored, 0)
        with patch.object(store, 'score_row', side_effect=AssertionError('rescored')) as scorer:
            store.record_source(self.db, SOURCE, [self.silicon('https://x/1')],
                                'complete', 'full', 1)
            scorer.assert_not_called()
        self.assertEqual(self.stored('https://x/1'), scored)

    def test_a_posting_arriving_later_is_still_scored(self):
        store.record_source(self.db, SOURCE, [self.silicon('https://x/1')], 'complete', 'full', 1)
        store.record_source(self.db, SOURCE, [self.silicon('https://x/1'),
                                              self.silicon('https://x/2')],
                            'complete', 'full', 1)
        self.assertGreater(self.stored('https://x/2'), 0)

    def test_retitle_refreshes_score_instead_of_preserving_a_hard_reject(self):
        old = self.silicon('https://x/1', title='Senior RTL Design Engineer')
        store.record_source(self.db, SOURCE, [old], 'complete', 'full', 1)
        self.assertEqual(self.stored('https://x/1'), 0)
        current = self.silicon('https://x/1')
        store.record_source(self.db, SOURCE, [current], 'complete', 'full', 1)
        self.assertGreater(self.stored('https://x/1'), 0)

    def test_changed_description_ignores_old_embedded_score_and_survives_rebuild(self):
        old = dict(row('https://x/1', title='RF Engineer'),
                   raw={'job_description': 'UVM SystemVerilog AXI testbench tape-out.',
                        'relevance': {'confidence': 99}})
        store.record_source(self.db, SOURCE, [old], 'complete', 'full', 1)
        current = dict(old, raw={'job_description': 'Antenna calibration and radio propagation.'})
        delta = store.record_source(self.db, SOURCE, [current], 'complete', 'full', 1)
        self.assertEqual(self.stored('https://x/1'), 0)
        with patch.object(store, 'LOG', Path(self.dir.name) / 'store'):
            store.append_log(self.db, delta['changed_urls'], [], delta['stamp'])
            store.write_manifest(self.db, delta['stamp'], [])
            self.db.commit()
            rebuilt = Path(self.dir.name) / 'rebuilt.sqlite'
            with closing(sqlite3.connect(rebuilt)) as db:
                db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            store.rebuild(rebuilt)
            with closing(store.connect(rebuilt)) as db:
                self.assertEqual(db.execute('SELECT relevance FROM jobs').fetchone()[0], 0)

    def test_a_rescore_reaches_the_log_so_a_rebuild_keeps_it(self):
        """SQLite is derived, so a correction only it holds is undone by a rebuild.

        `--rescore` is run after a term-list edit, precisely to change the
        ranking. Writing the new scores only to the index left the next
        `--bootstrap` replaying the old ones, silently restoring the ranking the
        rescore was run to fix.
        """
        stale = dict(row('https://x/1', title='Accountant'),
                     raw={'job_description': 'General ledger and tax reporting.',
                          'relevance': {'confidence': 99}})
        delta = store.record_source(self.db, SOURCE, [stale], 'complete', 'full', 1)
        store.append_log(self.db, delta['new_urls'], [], delta['stamp'])
        store.write_manifest(self.db, delta['stamp'], [])
        self.db.commit()
        self.assertEqual(self.stored('https://x/1'), 99)

        store.rescore(self.db_path)
        self.assertEqual(self.stored('https://x/1'), 0)

        rebuilt = Path(self.dir.name) / 'rebuilt.sqlite'
        with closing(sqlite3.connect(rebuilt)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.rebuild(rebuilt)
        with closing(store.connect(rebuilt)) as db:
            self.assertEqual(db.execute('SELECT relevance FROM jobs').fetchone()[0], 0)
        # The day it appended to still matches the manifest that describes it.
        self.assertEqual([state for _, state in store.verify()], ['ok'])

    def test_a_rescore_the_log_refused_leaves_the_index_where_it_was(self):
        """The index must not end up holding a score the log never received.

        Written index-first, a failed append left the new score in SQLite and
        the old one in the log: the rebuild put the old score back, the manifest
        still matched its file so nothing said so, and running the command again
        found the index already holding the new value, counted nothing as
        changed and published nothing. The correction could not be recovered by
        repeating the command that made it.
        """
        stale = dict(row('https://x/1', title='Accountant'),
                     raw={'job_description': 'General ledger and tax reporting.',
                          'relevance': {'confidence': 99}})
        delta = store.record_source(self.db, SOURCE, [stale], 'complete', 'full', 1)
        store.append_log(self.db, delta['new_urls'], [], delta['stamp'])
        store.write_manifest(self.db, delta['stamp'], [])
        self.db.commit()

        with patch.object(store, 'append_scores', side_effect=OSError('no space left')):
            with self.assertRaises(OSError):
                store.rescore(self.db_path)
        self.assertEqual(self.stored('https://x/1'), 99)

        store.rescore(self.db_path)
        self.assertEqual(self.stored('https://x/1'), 0)
        rebuilt = Path(self.dir.name) / 'rebuilt.sqlite'
        with closing(sqlite3.connect(rebuilt)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.rebuild(rebuilt)
        with closing(store.connect(rebuilt)) as db:
            self.assertEqual(db.execute('SELECT relevance FROM jobs').fetchone()[0], 0)
        self.assertEqual([state for _, state in store.verify()], ['ok'])

    def test_a_rescore_that_changes_nothing_writes_nothing(self):
        store.record_source(self.db, SOURCE, [self.silicon('https://x/1')], 'complete', 'full', 1)
        self.db.commit()
        store.rescore(self.db_path)
        self.assertFalse(list((store.LOG / 'runs').glob('*.ndjson.gz')))

    def test_rescore_ignores_a_stale_score_embedded_in_raw(self):
        stale = dict(row('https://x/1', title='Accountant'),
                     raw={'job_description': 'General ledger and tax reporting.',
                          'relevance': {'confidence': 99, 'matched_terms': ['old']}})
        store.record_source(self.db, SOURCE, [stale], 'complete', 'full', 1)
        self.assertEqual(self.stored('https://x/1'), 99)
        self.db.commit()

        store.rescore(self.db_path)

        self.assertEqual(self.stored('https://x/1'), 0)


class IncrementalReconciliationTests(unittest.TestCase):
    """B51 and B52: what an incremental pass may skip, and what a validator covers."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        log = patch.object(store, 'LOG', Path(self.dir.name) / 'store')
        log.start()
        self.addCleanup(log.stop)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)
        self.db = store.connect(self.db_path)
        self.addCleanup(self.db.close)
        self.eightfold = replace(SOURCE, source_id='ef:q', provider_key='eightfold')

    def ago(self, days):
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def test_an_incremental_pass_reads_back_a_week_and_a_stale_one_reads_everything(self):
        """A posting can reach the index after its stated date, or be edited under it."""
        success = self.ago(0)
        strategy, watermark = store.plan(self.eightfold, {'ef:q': {
            'last_success_at': success, 'last_full_at': self.ago(1), 'last_status': 'complete'}})
        self.assertEqual(strategy, 'since')
        self.assertEqual(datetime.fromisoformat(success) - datetime.fromisoformat(watermark),
                         timedelta(days=store.RECONCILE_DAYS))
        self.assertEqual(store.plan(self.eightfold, {'ef:q': {
            'last_success_at': success, 'last_full_at': self.ago(8),
            'last_status': 'complete'}})[0], 'full')

    def test_only_a_complete_full_pass_is_recorded_as_one(self):
        store.record_source(self.db, self.eightfold, [row('https://x/1')], 'complete', 'full', 1)
        first = self.db.execute("SELECT last_full_at FROM source_state").fetchone()[0]
        self.assertIsNotNone(first)
        store.record_source(self.db, self.eightfold, [row('https://x/1')], 'complete', 'since', 1)
        store.record_source(self.db, self.eightfold, [row('https://x/1')], 'partial', 'full', 1)
        self.assertEqual(self.db.execute("SELECT last_full_at FROM source_state").fetchone()[0],
                         first)

    def test_a_complete_pass_without_a_validator_clears_the_stored_one(self):
        """B52, and the B26 claim it corrects.

        `COALESCE` kept a stored ETag whenever a pass supplied none, so a
        validator the collector had deliberately refused -- a TI shell's, the
        first page of a longer board -- stayed for ever and went on answering
        304 for the whole source.
        """
        store.record_source(self.db, SOURCE, [row('https://x/1')], 'complete', 'full', 1,
                            etag='W/"page-one"')
        self.db.commit()
        state = store.load_state(self.db_path)
        self.assertEqual(store.plan(SOURCE, state)[0], 'conditional')
        store.record_source(self.db, SOURCE, [row('https://x/1')], 'partial', 'full', 1)
        self.assertEqual(self.db.execute('SELECT etag FROM source_state').fetchone()[0],
                         'W/"page-one"')
        store.record_source(self.db, SOURCE, [row('https://x/1')], 'complete', 'full', 1,
                            etag=None)
        self.db.commit()
        self.assertIsNone(self.db.execute('SELECT etag FROM source_state').fetchone()[0])
        self.assertEqual(store.plan(SOURCE, store.load_state(self.db_path))[0], 'full')


class SitemapDetailTests(unittest.TestCase):
    """B57: a detail page read without JSON-LD keeps what it says."""

    def test_the_requirements_under_the_heading_are_kept(self):
        source = replace(SOURCE, provider_key='akeana_careers', access_url='https://x/sitemap.xml')
        args = Namespace(max_jobs=1000, max_pages=10, delay=0, timeout=1, retries=0,
                         source_state=Path(tempfile.gettempdir()) / 'unused_pauses.sqlite')
        c = Collector(source, args)
        self.addCleanup(c.session.close)
        sitemap = '<urlset><url><loc>https://x/job/rtl</loc></url></urlset>'
        page = '<h1>RTL Engineer</h1><section>5 years of experience required.</section>'
        c.fetch = Mock(side_effect=lambda url: (Mock(content=sitemap.encode())
                                                if url == source.access_url else Mock(text=page)))
        self.assertEqual(c.collect_sitemap()[0], 'complete')
        self.assertIn('5 years of experience required', c.jobs[0]['raw']['description'])
        self.assertEqual(jsearch.experience_debug(c.jobs[0])['hard_pass_reason'],
                         'required_experience_over_2_years')


class OneBatchOneUrlTests(unittest.TestCase):
    """Two requisitions at one address, in one batch, are not one posting."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        log = patch.object(store, 'LOG', Path(self.dir.name) / 'store')
        log.start()
        self.addCleanup(log.stop)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)
        self.db = store.connect(self.db_path)
        self.addCleanup(self.db.close)

    def test_the_later_posting_does_not_inherit_the_earlier_one(self):
        """The row already prepared is what the second one follows.

        Nothing is written until the whole batch is prepared, so a second row on
        the same URL read the index, found the requisition that was there before
        the pass, and merged with that instead. The description and identity of
        the posting it displaced were blended into it -- and the review queue
        then dropped it, because the description it was holding did not carry
        the vocabulary its title had to be justified by.
        """
        # Two providers' field names for the same thing: whichever key the
        # displaced posting used and this one does not is what survives a merge.
        old = dict(row('https://x/shared', title='Accountant'), source_job_id='R-1',
                   raw={'description': 'General ledger and tax reporting.'})
        new = dict(row('https://x/shared', title='RTL Design Engineer'), source_job_id='R-2',
                   raw={'job_description': 'UVM SystemVerilog AXI testbench tape-out.'})
        store.record_source(self.db, SOURCE, [old, new], 'complete', 'full', 1)
        held = self.db.execute('SELECT title, source_job_id, raw FROM jobs').fetchall()
        self.assertEqual(len(held), 1)
        self.assertEqual((held[0]['title'], held[0]['source_job_id']),
                         ('RTL Design Engineer', 'R-2'))
        self.assertNotIn('General ledger', held[0]['raw'])
        # The description the review queue reads is the one this posting has.
        self.assertIn('SystemVerilog', jsearch.description_text(
            {'raw': json.loads(held[0]['raw'])}))
        self.assertEqual([r['source_job_id'] for r in self.db.execute(
            'SELECT source_job_id FROM job_identities')], ['R-2'])

    def test_one_requisition_listed_twice_is_still_merged(self):
        """The same opening at one address is not two, and must not churn."""
        listing = dict(row('https://x/shared'), source_job_id='R-1',
                       raw={'job_description': 'UVM SystemVerilog AXI testbench.'})
        store.record_source(self.db, SOURCE, [listing, dict(listing)], 'complete', 'full', 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)


class BackfillExportTests(unittest.TestCase):
    """`--export` writes each posting into the day it was first seen.

    Those days are over by definition, which is exactly what the seal refuses.
    The seal protects a record that already exists; a backfill runs only against
    a store that holds none, which the emptiness check above it enforces.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        log = patch.object(store, 'LOG', Path(self.dir.name) / 'store')
        log.start()
        self.addCleanup(log.stop)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)
        self.db = store.connect(self.db_path)
        self.addCleanup(self.db.close)

    def test_it_exports_a_posting_first_seen_on_a_day_that_has_sealed(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        store.record_source(self.db, SOURCE, [row('https://x/1')], 'complete', 'full', 1,
                            stamp=yesterday)
        self.db.commit()
        with patch('sys.argv', ['job-store', '--export', '--db', str(self.db_path)]), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(store.main(), 0)
        self.assertIn('exported: 1 jobs', out.getvalue())
        self.assertTrue((store.LOG / 'runs' / (yesterday[:10] + '.ndjson.gz')).is_file())
        self.assertEqual([state for _, state in store.verify()], ['ok'])

        rebuilt = Path(self.dir.name) / 'rebuilt.sqlite'
        with closing(sqlite3.connect(rebuilt)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.rebuild(rebuilt)
        with closing(store.connect(rebuilt)) as db:
            self.assertEqual(db.execute('SELECT url FROM jobs').fetchone()[0], 'https://x/1')

    def test_it_writes_a_manifest_for_a_day_that_only_closed_a_posting(self):
        """A closure lands in the day it happened, which may have nothing else.

        The manifests were written for the days postings were first seen, so a
        day holding only closures produced a run file nothing described -- the
        export finished, and the store it produced failed its own integrity
        check and could not be rebuilt from.
        """
        first_seen = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        closed_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        store.record_source(self.db, SOURCE, [row('https://x/1')], 'complete', 'full', 1,
                            stamp=first_seen)
        self.db.execute('UPDATE jobs SET closed_at=? WHERE url=?', (closed_at, 'https://x/1'))
        self.db.commit()
        with patch('sys.argv', ['job-store', '--export', '--db', str(self.db_path)]), \
             patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(store.main(), 0)
        self.assertEqual({state for _, state in store.verify()}, {'ok'})
        self.assertTrue((store.LOG / 'manifests' / (closed_at[:10] + '.json')).is_file())

    def test_a_store_that_already_holds_history_is_still_refused(self):
        store.record_source(self.db, SOURCE, [row('https://x/1')], 'complete', 'full', 1)
        self.db.commit()
        store.append_log(self.db, ['https://x/1'], [], store.now())
        with patch('sys.argv', ['job-store', '--export', '--db', str(self.db_path)]), \
             patch('sys.stderr', new_callable=io.StringIO), \
             patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                store.main()


class LogReadingTests(unittest.TestCase):
    """A day file is read a line at a time, not gathered into memory first.

    Measured on a synthetic four-thousand-posting day: 9.4 MB peak to 1.1 MB,
    same rebuild.
    """

    def test_it_yields_records_lazily_and_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'day.ndjson.gz'
            path.write_bytes(gzip.compress(b'{"a": 1}\n\n   \n{"b": 2}\n', mtime=0))
            lines = store.log_lines(path)
            self.assertIsInstance(lines, types.GeneratorType)
            self.assertEqual([json.loads(line) for line in lines], [{'a': 1}, {'b': 2}])


class PackagingTests(unittest.TestCase):
    """What the package says it needs on the Python versions it supports."""

    def test_the_toml_reader_is_a_dependency_and_not_an_extra(self):
        """Every entry point reads the query plan, and 3.10 has no `tomllib`."""
        manifest = tomllib.loads(
            (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))
        required = manifest['project']['dependencies']
        self.assertTrue(any(item.startswith('tomli') and 'python_version < ' in item
                            for item in required), required)
        self.assertLessEqual(tuple(int(part) for part in
                                   manifest['project']['requires-python'].lstrip('>=').split('.')),
                             (3, 11))


class BoardRowIdentityTests(unittest.TestCase):
    """A board row's identity must be the requisition, not the words in its URL.

    Apple advertises one role at many stores: the slug is shared and the
    requisition differs. Identifying by slug merged those postings into one and
    the store then retired the rest as withdrawn -- 2,155 live Apple postings in
    a single pass.
    """

    def test_apple_rows_are_identified_by_requisition_not_slug(self):
        from jobdisco.collector import html_job_id
        same_slug = [
            'https://jobs.apple.com/en-us/details/114438158/us-manager',
            'https://jobs.apple.com/en-us/details/200683913/us-manager',
            '/en-us/details/200684352-0836/us-manager?team=RETAIL',
        ]
        ids = [html_job_id(u, 'apple_jobs') for u in same_slug]
        self.assertEqual(ids, ['114438158', '200683913', '200684352-0836'])
        self.assertEqual(len(set(ids)), len(ids))

    def test_other_boards_keep_the_trailing_segment(self):
        from jobdisco.collector import html_job_id
        self.assertEqual(
            html_job_id('https://jobs.teradyne.com/job/North-Reading-Eng/1310296400/', 'jobs2web'),
            '1310296400')
        self.assertEqual(
            html_job_id('https://careers.arrow.com/us/en/job/R245154/Design-Verification', 'jobs2web'),
            'Design-Verification')


if __name__ == '__main__':
    unittest.main()
