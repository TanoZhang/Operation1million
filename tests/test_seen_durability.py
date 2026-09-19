"""The memory of having seen a job must outlive the machine that saw it.

`seen_jobs` lives in the derived index, which is gitignored and dies with the
box. Without a snapshot in the data repository a rebuilt machine treats every
previously rejected posting as new, and the whole point of recording them --
not re-deciding the same job every day -- is lost at exactly the moment it
matters most.

It is snapshotted under `operational/` rather than into the daily log, because
the log is a fourteen-day rolling backup and this memory has to outlast it.
"""
from contextlib import closing
from pathlib import Path
import gzip
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jobdisco import prune, store


class SeenSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store_root = self.root / 'store'
        (self.store_root / 'operational').mkdir(parents=True)
        patcher = patch.object(store, 'LOG', self.store_root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = self.make_db('catalog.sqlite')

    def make_db(self, name):
        path = self.root / name
        with closing(sqlite3.connect(path)) as raw:
            raw.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(path)
        db = store.connect(path)
        self.addCleanup(db.close)
        return db

    def row(self, ident, **extra):
        return dict({'provider_key': 'jsearch', 'source_job_id': ident,
                     'url': f'https://example.test/{ident}', 'title': 'RTL Design Engineer',
                     'employer': 'Example Semiconductor', 'decision': '',
                     'confidence': 70, 'filter_version': 'v1'}, **extra)

    def seen_of(self, db):
        return {r['source_job_id']: dict(r) for r in db.execute('SELECT * FROM seen_jobs')}

    def test_the_snapshot_survives_losing_the_machine_entirely(self):
        """The question the whole change exists to answer, after a total rebuild."""
        with self.db:
            store.record_seen(self.db, [self.row('kept'),
                                        self.row('binned', decision='title_mismatch')],
                              stamp='2026-09-01T00:00:00+00:00')
            store.export_seen(self.db)

        # A different machine: a brand new index that has never seen anything.
        fresh = self.make_db('rebuilt.sqlite')
        self.assertEqual(self.seen_of(fresh), {})
        with fresh:
            restored = store.import_seen(fresh)
        self.assertEqual(restored, 2)
        recovered = self.seen_of(fresh)
        self.assertEqual(recovered['binned']['decision'], 'title_mismatch')
        self.assertEqual(recovered['kept']['first_seen'], '2026-09-01T00:00:00+00:00')

    def test_the_snapshot_lands_where_pruning_can_never_reach_it(self):
        """Under operational/, so a fourteen-day window does not erase it."""
        with self.db:
            store.record_seen(self.db, [self.row('j')])
            store.export_seen(self.db)
        snapshot = self.store_root / store.SEEN_SNAPSHOT
        self.assertTrue(snapshot.exists())

        (self.store_root / 'runs').mkdir(exist_ok=True)
        (self.store_root / 'manifests').mkdir(exist_ok=True)
        (self.store_root / 'runs' / '2020-01-01.ndjson.gz').write_bytes(b'x')
        (self.store_root / 'manifests' / '2020-01-01.json').write_text('{}', encoding='utf-8')
        prune.prune(self.store_root, keep_days=1, today='2026-09-19')
        self.assertTrue(snapshot.exists(), 'pruning reached the seen snapshot')

    def test_the_snapshot_is_a_snapshot_not_an_append(self):
        """last_seen moves and decisions flip, so yesterday's rows must not linger."""
        with self.db:
            store.record_seen(self.db, [self.row('j')], stamp='2026-09-01T00:00:00+00:00')
            store.export_seen(self.db)
            store.record_seen(self.db, [self.row('j', decision='title_mismatch')],
                              stamp='2026-09-19T00:00:00+00:00')
            store.export_seen(self.db)
        with gzip.open(self.store_root / store.SEEN_SNAPSHOT, 'rt', encoding='utf-8') as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['decision'], 'title_mismatch')
        self.assertEqual(rows[0]['first_seen'], '2026-09-01T00:00:00+00:00')
        self.assertEqual(rows[0]['last_seen'], '2026-09-19T00:00:00+00:00')

    def test_a_rebuild_restores_the_seen_table_without_being_asked(self):
        """`job-store --bootstrap` is the whole recovery path; it must carry this."""
        with self.db:
            store.record_seen(self.db, [self.row('a'), self.row('b', decision='excluded')])
            store.export_seen(self.db)
        (self.store_root / 'runs').mkdir(exist_ok=True)
        (self.store_root / 'manifests').mkdir(exist_ok=True)

        path = self.root / 'replayed.sqlite'
        with closing(sqlite3.connect(path)) as raw:
            raw.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        counts = store.rebuild(path)
        self.assertEqual(counts['seen'], 2)
        with closing(store.connect(path)) as rebuilt:
            recovered = {r['source_job_id']: dict(r)
                         for r in rebuilt.execute('SELECT * FROM seen_jobs')}
        self.assertEqual(recovered['b']['decision'], 'excluded')

    def test_an_absent_snapshot_is_not_an_error(self):
        fresh = self.make_db('nosnapshot.sqlite')
        with fresh:
            self.assertEqual(store.import_seen(fresh), 0)


class DedupKeyTests(unittest.TestCase):
    """The identity must be indexed, and must prefer a stable id over a url."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(path)) as raw:
            raw.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(path)
        self.db = store.connect(path)
        self.addCleanup(self.db.close)

    def test_the_identity_is_unique_and_indexed(self):
        """Without an index, asking "seen before" gets slower with every pass."""
        plan = self.db.execute(
            'EXPLAIN QUERY PLAN SELECT 1 FROM seen_jobs '
            'WHERE provider_key=? AND source_job_id=?', ('jsearch', 'x')).fetchall()
        detail = ' '.join(str(row['detail']) for row in plan)
        self.assertNotIn('SCAN', detail, f'the dedup key is not indexed: {detail}')
        self.assertIn('sqlite_autoindex_seen_jobs_1', detail)

    def test_a_repeated_identity_cannot_become_a_second_row(self):
        with self.db:
            store.record_seen(self.db, [{'provider_key': 'jsearch', 'source_job_id': 'dup',
                                         'url': 'https://example.test/one'}])
            store.record_seen(self.db, [{'provider_key': 'jsearch', 'source_job_id': 'dup',
                                         'url': 'https://example.test/moved'}])
        rows = self.db.execute('SELECT url FROM seen_jobs').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://example.test/moved')

    def test_the_url_is_only_a_fallback_for_a_provider_with_no_id(self):
        with self.db:
            store.record_seen(self.db, [
                {'provider_key': 'jsearch', 'source_job_id': 'has-id',
                 'url': 'https://example.test/has-id'},
                {'provider_key': 'jsearch', 'source_job_id': '',
                 'url': 'https://example.test/no-id'}])
        keys = {r['source_job_id'] for r in self.db.execute('SELECT source_job_id FROM seen_jobs')}
        self.assertEqual(keys, {'has-id', 'https://example.test/no-id'})


if __name__ == '__main__':
    unittest.main()
