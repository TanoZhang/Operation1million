"""Ranking decides what is read first, and is never allowed to decide more.

Two properties carry the weight here. Relevance is asked before seniority, so
an internship that is not the trade cannot climb over the trade; and a date the
employer published is never interchangeable with the day we happened to find
the posting, because the first collection pass gave forty thousand postings the
same `first_seen` and treating that as a publication date would have read every
one of them as breaking news.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jobdisco import applications, ranking


class BucketTests(unittest.TestCase):
    def test_the_trade_is_recognised_by_phrase_not_by_loose_word(self):
        for title in ('RTL Design Engineer', 'ASIC Design Engineer', 'FPGA Engineer',
                      'SoC Design Verification Engineer', 'Digital Design Engineer',
                      'Physical Design Engineer', 'Logic Design Engineer',
                      'DFT Engineer', 'VLSI Engineer', 'Silicon Validation Engineer',
                      'Pre-Silicon Verification Engineer', 'Static Timing Analysis Engineer',
                      'Design for Testability Engineer', 'Microarchitecture Engineer'):
            with self.subTest(title=title):
                self.assertEqual(ranking.bucket(title), 2, title)

    def test_loose_trade_words_land_in_the_adjacent_band_not_the_core(self):
        for title in ('Hardware Engineer', 'Embedded Engineer', 'Firmware Engineer',
                      'Validation Engineer', 'Semiconductor Engineer', 'Memory Engineer',
                      'Electrical Engineer', 'Silicon Test Engineer', 'PCIe Engineer'):
            with self.subTest(title=title):
                self.assertEqual(ranking.bucket(title), 3, title)

    def test_everything_else_sinks(self):
        for title in ('Program Coordinator', 'Software Marketing Intern',
                      'Account Executive', 'Warehouse Associate', ''):
            with self.subTest(title=title):
                self.assertEqual(ranking.bucket(title), 4, title)

    def test_early_career_leads_both_bands_but_rescues_neither_outsider(self):
        self.assertEqual(ranking.bucket('RTL Design Intern'), 0)
        self.assertEqual(ranking.bucket('ASIC Design Engineer, New Grad'), 0)
        self.assertEqual(ranking.bucket('Hardware Engineering Intern'), 1)
        # An adjacent internship is an opening this search can take; a
        # principal RTL role is not, so it comes first despite being less
        # squarely the trade.
        self.assertLess(ranking.bucket('Hardware Engineering Intern'),
                        ranking.bucket('Principal RTL Design Engineer'))
        # The example the whole ordering exists for: "Intern" is not a lift out
        # of the last band when nothing else in the title qualifies.
        self.assertLess(ranking.bucket('RTL Design Engineer'),
                        ranking.bucket('Software Marketing Intern'))
        self.assertEqual(ranking.bucket('Software Marketing Intern'), 4)

    def test_the_early_career_vocabulary_the_search_is_written_around(self):
        for title in ('Design Verification Intern', 'RTL Internship',
                      'ASIC Co-op', 'FPGA Co Op Engineer', 'SoC New Grad Engineer',
                      'New Graduate ASIC Engineer', 'University Graduate, RTL',
                      'Graduate Engineer - Digital Design', 'Entry Level FPGA Engineer',
                      'Entry-Level VLSI Engineer', 'Early Career DFT Engineer',
                      'Campus Hire: Physical Design', 'RTL Design Student Researcher',
                      '2027 Grads - ASIC Design'):
            with self.subTest(title=title):
                self.assertEqual(ranking.bucket(title), 0, title)

    def test_soc_the_security_desk_is_not_soc_the_chip(self):
        for title in ('SOC Analyst', 'SOC Operations Engineer', 'SOC 2 Compliance Lead'):
            with self.subTest(title=title):
                self.assertNotIn(ranking.bucket(title), (0, 2), title)


class PostedDayTests(unittest.TestCase):
    def test_every_shape_the_providers_actually_send(self):
        for value in ('2026-09-14T12:00:00+00:00', '2026-09-14T12:00:00+0000',
                      '2026-09-14T12:00:00.000+0000', '2026-09-14T12:00:00.000Z',
                      '2026-09-14T12:00:00', '2026-09-14'):
            with self.subTest(value=value):
                self.assertEqual(ranking.posted_day(value).isoformat(), '2026-09-14')
        # Amazon publishes this, and no ISO parser takes it.
        self.assertEqual(ranking.posted_day('September 14, 2026').isoformat(), '2026-09-14')
        self.assertEqual(ranking.posted_day('September  9, 2026').isoformat(), '2026-09-09')

    def test_nothing_usable_is_said_so_rather_than_guessed(self):
        for value in (None, '', '   ', 'Posted recently', '2026-13-45', 'yesterday'):
            with self.subTest(value=value):
                self.assertIsNone(ranking.posted_day(value))


def group(title, bucket=None, confidence=0, posted=None, seen='2026-09-19T00:00:00+00:00', id='x'):
    return {'id': id, 'title': title, 'confidence': confidence,
            'jobs': [{'posted_at': posted, 'first_seen': seen}]}


class OrderTests(unittest.TestCase):
    def test_the_band_outranks_everything_below_it(self):
        ordered = ranking.order([
            group('Hardware Engineer', confidence=100, posted='2026-09-19', id='related'),
            group('RTL Design Engineer', confidence=1, posted='2026-01-01', id='core'),
            group('Warehouse Associate', confidence=100, posted='2026-09-19', id='other'),
            group('Hardware Engineering Intern', confidence=0, posted='2025-01-01',
                  id='related-intern'),
            group('RTL Design Intern', confidence=0, posted='2025-01-01', id='intern'),
        ])
        self.assertEqual([g['id'] for g in ordered],
                         ['intern', 'related-intern', 'core', 'related', 'other'])

    def test_an_adjacent_internship_leads_a_core_role_it_could_not_apply_for(self):
        """Both early-career bands come before either regular one."""
        ordered = ranking.order([
            group('Principal RTL Design Engineer', confidence=100, posted='2026-09-19',
                  id='core-senior'),
            group('Embedded Firmware Intern', confidence=0, posted='2025-01-01',
                  id='adjacent-intern'),
        ])
        self.assertEqual([g['id'] for g in ordered], ['adjacent-intern', 'core-senior'])

    def test_inside_a_band_the_newest_posting_comes_first(self):
        ordered = ranking.order([
            group('RTL Engineer A', posted='2026-09-10', confidence=100, id='old'),
            group('RTL Engineer B', posted='2026-09-18', confidence=1, id='new'),
        ])
        self.assertEqual([g['id'] for g in ordered], ['new', 'old'])

    def test_relevance_breaks_a_tie_within_one_day(self):
        ordered = ranking.order([
            group('RTL Engineer A', posted='2026-09-18', confidence=40, id='low'),
            group('RTL Engineer B', posted='2026-09-18', confidence=90, id='high'),
        ])
        self.assertEqual([g['id'] for g in ordered], ['high', 'low'])

    def test_a_stated_date_outranks_one_inferred_from_first_seen(self):
        """`first_seen` is a fallback, never a synonym."""
        ordered = ranking.order([
            group('RTL Engineer A', posted=None, seen='2026-09-18T23:00:00+00:00',
                  confidence=100, id='inferred'),
            group('RTL Engineer B', posted='2026-09-18', seen='2026-09-18T01:00:00+00:00',
                  confidence=0, id='stated'),
        ])
        self.assertEqual([g['id'] for g in ordered], ['stated', 'inferred'])

    def test_an_old_posting_found_today_does_not_read_as_todays_news(self):
        ordered = ranking.order([
            group('RTL Engineer A', posted='2026-07-01', seen='2026-09-19T00:00:00+00:00', id='july'),
            group('RTL Engineer B', posted='2026-09-18', seen='2026-09-19T00:00:00+00:00', id='sept'),
        ])
        self.assertEqual([g['id'] for g in ordered], ['sept', 'july'])

    def test_a_group_carries_the_newest_date_any_of_its_listings_states(self):
        several = {'id': 'many', 'title': 'RTL Engineer', 'confidence': 0,
                   'jobs': [{'posted_at': '2026-09-01', 'first_seen': '2026-09-19T00:00:00+00:00'},
                            {'posted_at': '2026-09-18', 'first_seen': '2026-09-19T00:00:00+00:00'}]}
        ordered = ranking.order([group('RTL Other', posted='2026-09-10', id='single'), several])
        self.assertEqual([g['id'] for g in ordered], ['many', 'single'])

    def test_it_is_a_total_order_so_a_queue_never_reshuffles_itself(self):
        groups = [group('RTL Engineer', posted='2026-09-18', id=str(n)) for n in range(20)]
        self.assertEqual([g['id'] for g in ranking.order(groups)],
                         [g['id'] for g in ranking.order(list(reversed(groups)))])

    def test_a_group_without_dates_or_a_bucket_still_sorts(self):
        self.assertEqual(len(ranking.order([{'id': 'a', 'title': None, 'jobs': []},
                                            {'id': 'b'}])), 2)


class SummaryTests(unittest.TestCase):
    def test_both_early_career_bands_report_as_one_number(self):
        counts = ranking.summarize([
            group('RTL Design Intern'), group('Hardware Engineering Intern'),
            group('RTL Design Engineer'), group('Hardware Engineer'),
            group('Warehouse Associate')])
        self.assertEqual(counts, {'intern_ng': 2, 'core_vlsi': 1,
                                  'related_hardware': 1, 'low_relevance': 1})

    def test_a_label_exists_for_every_band(self):
        self.assertEqual(len(ranking.LABELS), 5)
        for title in ('RTL Design Intern', 'RTL Design Engineer', 'Hardware Intern',
                      'Hardware Engineer', 'Warehouse Associate'):
            self.assertTrue(ranking.LABELS[ranking.bucket(title)])


class QueueOrderTests(unittest.TestCase):
    """The ordering has to survive the round trip through the real queue."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / 'jobs.sqlite'
        self.ledger = Path(temporary.name) / 'applications.ndjson'
        now = datetime.now(timezone.utc)
        self.rows = [
            ('rtl-intern', 'RTL Design Intern', 30, (now - timedelta(days=2)).isoformat()),
            ('rtl', 'RTL Design Engineer', 100, (now - timedelta(days=2)).isoformat()),
            ('hw', 'Hardware Engineer', 100, now.isoformat()),
            ('misc', 'Program Coordinator', 100, now.isoformat()),
            ('rf-weak', 'RF Engineer', 0, now.isoformat()),
            ('rf-strong', 'RFIC Digital Verification Engineer', 90, now.isoformat()),
        ]
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample');
                CREATE TABLE jobs(url TEXT, company_key TEXT, title TEXT, location TEXT,
                    source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                    relevance INTEGER, closed_at TEXT, raw TEXT);''')
            for key, title, score, posted in self.rows:
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)',
                           (f'https://example.test/{key}', 'sample', title, 'Austin', key,
                            now.isoformat(), posted, 'jsearch', score, '{}'))

    def queue(self):
        return applications.queue(self.db, self.ledger)['pending']

    def test_the_queue_is_ordered_by_band_before_score(self):
        queued = self.queue()
        bands = [group['bucket'] for group in queued]
        self.assertEqual(bands, sorted(bands), 'a band must never follow a weaker one')
        titles = [group['title'] for group in queued]
        # Each of these outranks the one after it on band alone, against a
        # score and a date that all point the other way.
        self.assertEqual(titles[0], 'RTL Design Intern')
        self.assertLess(titles.index('RTL Design Engineer'), titles.index('Hardware Engineer'))
        self.assertLess(titles.index('Program Coordinator'), titles.index('RF Engineer'))

    def test_every_group_carries_its_band_and_evidence_mark(self):
        for group in self.queue():
            self.assertIn(group['bucket'], range(5))
            self.assertIsInstance(group['flagged'], bool)
        flagged = {g['title']: g['flagged'] for g in self.queue()}
        self.assertTrue(flagged['RFIC Digital Verification Engineer'])
        self.assertFalse(flagged['RTL Design Engineer'])

    def test_missing_description_does_not_hide_an_evidence_title(self):
        """A zero score with no prose is missing data, not negative evidence."""
        titles = [g['title'] for g in self.queue()]
        self.assertIn('RF Engineer', titles)
        self.assertIn('RFIC Digital Verification Engineer', titles)

    def test_supplied_off_domain_prose_still_filters_an_evidence_title(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET raw=? WHERE source_job_id='rf-weak'", (
                '{"description":"Antenna tuning and spectrum planning."}',))
        self.assertNotIn('RF Engineer', [g['title'] for g in self.queue()])


if __name__ == '__main__':
    unittest.main()
