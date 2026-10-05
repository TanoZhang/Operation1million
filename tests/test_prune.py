"""The log is a rolling backup, and pruning it must not take anything else."""
from pathlib import Path
import gzip
import json
import tempfile
import unittest

from jobdisco import prune


class PruneTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = Path(temporary.name)
        (self.store / 'runs').mkdir()
        (self.store / 'manifests').mkdir()
        (self.store / 'operational').mkdir()

    def day(self, stamp, shard=None):
        name = f'{stamp}-{shard}' if shard else stamp
        (self.store / 'runs' / f'{name}.ndjson.gz').write_bytes(gzip.compress(b''))
        (self.store / 'manifests' / f'{name}.json').write_text('{}', encoding='utf-8')

    def names(self, folder):
        return sorted(p.name for p in (self.store / folder).iterdir())

    def test_a_day_outside_the_window_goes_with_its_manifest(self):
        """Dropping one without the other leaves a store that fails verification."""
        for stamp in ('2026-09-01', '2026-09-18', '2026-09-19'):
            self.day(stamp)
        prune.prune(self.store, keep_days=14, today='2026-09-19')
        self.assertEqual(self.names('runs'),
                         ['2026-09-18.ndjson.gz', '2026-09-19.ndjson.gz'])
        self.assertEqual(self.names('manifests'),
                         ['2026-09-18.json', '2026-09-19.json'])

    def test_a_day_and_all_of_its_shards_go_together(self):
        self.day('2026-09-01')
        self.day('2026-09-01', '0001')
        self.day('2026-09-19')
        result = prune.prune(self.store, keep_days=7, today='2026-09-19')
        self.assertEqual(result['removed_days'], ['2026-09-01'])
        self.assertEqual(self.names('runs'), ['2026-09-19.ndjson.gz'])

    def test_the_window_counts_today_as_one_of_its_days(self):
        for stamp in ('2026-09-16', '2026-09-17', '2026-09-18', '2026-09-19'):
            self.day(stamp)
        kept, _ = prune.plan(self.store, keep_days=3, today='2026-09-19')
        self.assertEqual(kept, ['2026-09-17', '2026-09-18', '2026-09-19'])

    def test_operational_state_is_never_touched(self):
        """Money and decisions, not the world. Nothing regenerates these."""
        for name in ('applications.ndjson', 'jsearch_usage.sqlite', 'source_access.sqlite'):
            (self.store / 'operational' / name).write_text('keep me', encoding='utf-8')
        self.day('2026-01-01')
        self.day('2026-09-19')
        prune.prune(self.store, keep_days=1, today='2026-09-19')
        self.assertEqual(self.names('operational'),
                         ['applications.ndjson', 'jsearch_usage.sqlite', 'source_access.sqlite'])
        for path in (self.store / 'operational').iterdir():
            self.assertEqual(path.read_text(encoding='utf-8'), 'keep me')

    def test_pruning_never_empties_the_store(self):
        """An empty window is a clock or configuration mistake, not an intention."""
        self.day('2020-01-01')
        result = prune.prune(self.store, keep_days=14, today='2026-09-19')
        self.assertEqual(result['kept_days'], ['2020-01-01'])
        self.assertEqual(result['removed'], [])
        self.assertEqual(self.names('runs'), ['2020-01-01.ndjson.gz'])

    def test_a_dry_run_reports_without_removing(self):
        self.day('2026-01-01')
        self.day('2026-09-19')
        result = prune.prune(self.store, keep_days=1, today='2026-09-19', dry_run=True)
        self.assertEqual(result['removed_days'], ['2026-01-01'])
        self.assertEqual(len(self.names('runs')), 2)

    def test_files_that_are_not_day_logs_are_left_alone(self):
        self.day('2026-09-19')
        (self.store / 'runs' / 'notes.txt').write_text('x', encoding='utf-8')
        (self.store / 'manifests' / 'index.json').write_text('{}', encoding='utf-8')
        prune.prune(self.store, keep_days=1, today='2026-09-19')
        self.assertIn('notes.txt', self.names('runs'))
        self.assertIn('index.json', self.names('manifests'))

    def test_the_cli_refuses_a_window_of_nothing(self):
        with self.assertRaises(SystemExit):
            prune.main(['--store', str(self.store), '--keep', '0'])


class PrunedStoreStillVerifies(unittest.TestCase):
    """A pruned store must remain self-consistent, or the next pass refuses to publish."""

    def test_every_remaining_run_file_still_has_its_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory)
            (store / 'runs').mkdir()
            (store / 'manifests').mkdir()
            for stamp in ('2026-08-01', '2026-09-05', '2026-09-18', '2026-09-19'):
                (store / 'runs' / f'{stamp}.ndjson.gz').write_bytes(gzip.compress(b''))
                (store / 'manifests' / f'{stamp}.json').write_text(
                    json.dumps({'day': stamp}), encoding='utf-8')
            prune.prune(store, keep_days=14, today='2026-09-19')
            runs = {prune.day_of(p) for p in (store / 'runs').iterdir()}
            manifests = {prune.day_of(p) for p in (store / 'manifests').iterdir()}
            self.assertEqual(runs, manifests)
            self.assertTrue(runs)


if __name__ == '__main__':
    unittest.main()


class CarryForwardTests(unittest.TestCase):
    """#318: a rebuild from the window must still hold every open posting."""

    def setUp(self):
        from contextlib import closing
        import sqlite3
        from unittest.mock import patch
        from jobdisco import store
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'store'
        patcher = patch.object(store, 'LOG', self.log)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db_path = self.root / 'jobs.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.commit()
        store.migrate(self.db_path)
        self.store = store

    def posting(self, db, url, first_seen, closed_at=None):
        db.execute('INSERT INTO jobs (url, company_key, provider_key, title, first_seen, last_seen, '
                   'closed_at, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                   (url, 'micron', 'eightfold', 'Intern - DRAM Design Engineer', first_seen,
                    first_seen, closed_at, '{}'))

    def test_an_open_posting_from_a_pruned_day_survives_a_rebuild_with_its_first_seen(self):
        from contextlib import closing
        store = self.store
        old, today = '2026-09-01T11:00:00+00:00', store.now()
        with closing(store.connect(self.db_path)) as db:
            self.posting(db, 'https://careers.micron.com/careers/job/1', old)
            self.posting(db, 'https://careers.micron.com/careers/job/2', old,
                         closed_at='2026-09-02T11:00:00+00:00')
            self.posting(db, 'https://careers.micron.com/careers/job/3', today)
            db.commit()
            store.append_log(db, ['https://careers.micron.com/careers/job/1',
                                  'https://careers.micron.com/careers/job/2'], [], old,
                             allow_sealed=True)
            store.append_log(db, ['https://careers.micron.com/careers/job/3'], [], today)
        result = prune.prune(self.log, keep_days=14, db_path=self.db_path)
        self.assertEqual(result['removed_days'], ['2026-09-01'])
        self.assertEqual(result['carried'], 1)
        rebuilt = self.root / 'rebuilt.sqlite'
        store.bootstrap(rebuilt)
        with closing(store.connect(rebuilt)) as db:
            rows = dict(db.execute('SELECT url, first_seen FROM jobs').fetchall())
        self.assertEqual(rows, {'https://careers.micron.com/careers/job/1': old,
                                'https://careers.micron.com/careers/job/3': today})

    def test_postings_are_carried_into_the_store_being_pruned(self):
        """History compaction prunes a staged copy, not the store JOBDISCO_STORE names."""
        from contextlib import closing
        import shutil
        store = self.store
        old = '2026-09-01T11:00:00+00:00'
        with closing(store.connect(self.db_path)) as db:
            self.posting(db, 'https://careers.micron.com/careers/job/1', old)
            db.commit()
            store.append_log(db, ['https://careers.micron.com/careers/job/1'], [], old,
                             allow_sealed=True)
            store.append_log(db, [], [], store.now(), seen_urls=['https://careers.micron.com/careers/job/1'])
        staged = self.root / 'staged'
        shutil.copytree(self.log, staged)
        before = sorted(p.name for p in (self.log / 'runs').iterdir())
        result = prune.prune(staged, keep_days=14, db_path=self.db_path)
        self.assertEqual(result['carried'], 1)
        self.assertEqual(sorted(p.name for p in (self.log / 'runs').iterdir()), before)
        self.assertIn('https://careers.micron.com/careers/job/1',
                      prune.job_urls((staged / 'runs').glob('*.ndjson.gz')))

    def test_without_an_index_nothing_is_pruned(self):
        from contextlib import closing
        store = self.store
        old = '2026-09-01T11:00:00+00:00'
        with closing(store.connect(self.db_path)) as db:
            self.posting(db, 'https://careers.micron.com/careers/job/1', old)
            db.commit()
            store.append_log(db, ['https://careers.micron.com/careers/job/1'], [], old,
                             allow_sealed=True)
            store.append_log(db, [], [], store.now(), seen_urls=['https://careers.micron.com/careers/job/1'])
        with self.assertRaises(FileNotFoundError):
            prune.prune(self.log, keep_days=14, db_path=self.root / 'absent.sqlite')
        self.assertTrue((self.log / 'runs' / '2026-09-01.ndjson.gz').exists())
