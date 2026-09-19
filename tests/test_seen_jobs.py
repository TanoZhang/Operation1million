"""Every job a provider returned leaves a trace, whatever was decided about it.

Before this, a rejected posting left nothing but a counter, so the same job was
fetched, normalized, scored and rejected again on every pass and nothing could
answer "have we seen this before". The record is deliberately light: it answers
that question and no other.

No lookup helper accompanies it, because nothing in the pipeline asks: every row
a provider returns is scored and decided again from scratch, so the table is
written to rather than consulted. A caller that needs to ask can query it.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jobdisco import store


class SeenJobsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        store.migrate(self.path)
        self.db = store.connect(self.path)
        self.addCleanup(self.db.close)

    def seen(self):
        return {r['source_job_id']: dict(r)
                for r in self.db.execute('SELECT * FROM seen_jobs')}

    def row(self, ident, decision='', **extra):
        return dict({'provider_key': 'jsearch', 'source_job_id': ident,
                     'url': f'https://example.test/{ident}', 'title': 'RTL Design Engineer',
                     'employer': 'Example Semiconductor', 'decision': decision,
                     'confidence': 70, 'filter_version': 'abc123'}, **extra)

    def test_a_rejected_job_is_recorded_rather_than_discarded(self):
        with self.db:
            store.record_seen(self.db, [self.row('r1', decision='title_mismatch')])
        kept = self.seen()['r1']
        self.assertEqual(kept['decision'], 'title_mismatch')
        self.assertEqual(kept['title'], 'RTL Design Engineer')
        self.assertEqual(kept['employer'], 'Example Semiconductor')

    def test_an_accepted_job_is_recorded_too_with_an_empty_decision(self):
        with self.db:
            store.record_seen(self.db, [self.row('a1')])
        self.assertEqual(self.seen()['a1']['decision'], '')

    def test_the_record_holds_no_description_and_no_raw_payload(self):
        """A rejected posting is worth recognising, not worth storing."""
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(seen_jobs)')}
        self.assertNotIn('raw', columns)
        self.assertNotIn('description', columns)
        self.assertEqual(columns, {'provider_key', 'source_job_id', 'url', 'title',
                                   'employer', 'first_seen', 'last_seen', 'decision',
                                   'confidence', 'filter_version'})

    def test_first_seen_never_moves_and_last_seen_always_does(self):
        with self.db:
            store.record_seen(self.db, [self.row('j1')], stamp='2026-09-01T00:00:00+00:00')
            store.record_seen(self.db, [self.row('j1')], stamp='2026-09-19T00:00:00+00:00')
        kept = self.seen()['j1']
        self.assertEqual(kept['first_seen'], '2026-09-01T00:00:00+00:00')
        self.assertEqual(kept['last_seen'], '2026-09-19T00:00:00+00:00')

    def test_a_second_sighting_refreshes_the_decision(self):
        """A filter change can turn yesterday's rejection into today's keep."""
        with self.db:
            store.record_seen(self.db, [self.row('j2', decision='title_mismatch',
                                                 filter_version='old')])
            store.record_seen(self.db, [self.row('j2', decision='', filter_version='new')])
        kept = self.seen()['j2']
        self.assertEqual(kept['decision'], '')
        self.assertEqual(kept['filter_version'], 'new')

    def test_a_retitled_posting_stays_one_record(self):
        with self.db:
            store.record_seen(self.db, [self.row('j3', title='RTL Design Engineer')])
            store.record_seen(self.db, [self.row('j3', title='Senior RTL Design Engineer')])
        self.assertEqual(len(self.seen()), 1)
        self.assertEqual(self.seen()['j3']['title'], 'Senior RTL Design Engineer')

    def test_a_provider_with_no_id_is_keyed_by_its_url(self):
        with self.db:
            store.record_seen(self.db, [dict(self.row('ignored'), source_job_id='')])
        self.assertIn('https://example.test/ignored', self.seen())

    def test_a_row_with_neither_id_nor_url_is_skipped_rather_than_stored_blank(self):
        with self.db:
            written = store.record_seen(self.db, [dict(self.row('x'), source_job_id='', url='')])
        self.assertEqual(written, 0)
        self.assertEqual(self.seen(), {})

    def test_two_providers_may_use_the_same_id_without_colliding(self):
        with self.db:
            store.record_seen(self.db, [self.row('shared'),
                                        dict(self.row('shared'), provider_key='other')])
        self.assertEqual(
            self.db.execute('SELECT count(*) FROM seen_jobs').fetchone()[0], 2)

    def test_the_table_does_not_depend_on_a_jobs_row_existing(self):
        """`job_identities` could not serve here: its url references jobs(url)."""
        with self.db:
            store.record_seen(self.db, [self.row('orphan', decision='excluded_employer')])
        self.assertEqual(
            self.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.assertEqual(len(self.seen()), 1)


if __name__ == '__main__':
    unittest.main()
