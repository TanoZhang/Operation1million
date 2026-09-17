"""Job store and incremental strategy selection.

The incremental paths decide what a run is allowed to skip, so a bug here loses
postings silently. Each strategy is covered together with the rule that only a
complete pass may retire a posting.
"""
import json
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

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
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db_path = Path(self.dir.name) / 'catalog.sqlite'
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        store.migrate(self.db_path)

    def open_db(self):
        db = store.connect(self.db_path)
        self.addCleanup(db.close)
        return db

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
        self.assertEqual(store.plan(eightfold, {'ef:q': done})[0], 'since')
        sitemap = replace(SOURCE, source_id='rn', provider_key='renesas_careers')
        self.assertEqual(store.plan(sitemap, {'rn': done})[0], 'lastmod')
        # An unrecognised board is read in full rather than guessed at.
        self.assertEqual(store.plan(replace(SOURCE, provider_key='workday'),
                                    {'ashby:matx': done})[0], 'full')

    def test_new_then_unchanged_then_closed(self):
        db = self.open_db()
        first = store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                                    'complete', 'full', 2)
        self.assertEqual((first['seen'], first['new'], first['closed']), (2, 2, 0))
        again = store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                                    'complete', 'full', 2)
        self.assertEqual((again['seen'], again['new'], again['closed']), (2, 0, 0))
        gone = store.record_source(db, SOURCE, [row('https://x/1')], 'complete', 'full', 1)
        self.assertEqual((gone['new'], gone['closed']), (0, 1))
        self.assertIsNotNone(
            db.execute("SELECT closed_at FROM jobs WHERE url='https://x/2'").fetchone()[0])
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

    def test_skipping_a_fetch_does_not_retire_a_listed_posting(self):
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                            'complete', 'full', 2)
        self.assertEqual(store.known_urls(db, 'matx'), {'https://x/1', 'https://x/2'})
        # The board still lists both, but only the new one was downloaded.
        delta = store.record_source(db, SOURCE, [row('https://x/3')], 'complete', 'lastmod', 1,
                                    listed={'https://x/1', 'https://x/2', 'https://x/3'})
        self.assertEqual((delta['new'], delta['closed']), (1, 0))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL')
                         .fetchone()[0], 3)
        # Skipped-but-listed postings still count as seen this pass.
        self.assertEqual(len({r[0] for r in db.execute('SELECT last_seen FROM jobs')}), 1)
        # Dropping out of the listing is what closes a posting.
        gone = store.record_source(db, SOURCE, [], 'complete', 'lastmod', 1,
                                   listed={'https://x/3'})
        self.assertEqual(gone['closed'], 2)

    def test_unchanged_board_refreshes_without_closing(self):
        db = self.open_db()
        store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                            'complete', 'full', 2, etag='W/"one"')
        before = db.execute('SELECT MAX(last_seen) FROM jobs').fetchone()[0]
        delta = store.touch_source(db, SOURCE, 'conditional', 1)
        self.assertEqual((delta['seen'], delta['new'], delta['closed']), (2, 0, 0))
        self.assertGreater(db.execute('SELECT MIN(last_seen) FROM jobs').fetchone()[0], before)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL')
                         .fetchone()[0], 2)
        # A 304 carries no validator of its own, so the stored one is kept.
        self.assertEqual(db.execute('SELECT etag FROM source_state').fetchone()[0], 'W/"one"')

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
        first = store.record_source(db, SOURCE, [row('https://x/1'), row('https://x/2')],
                                    'complete', 'full', 2)
        store.append_log(db, first['new_urls'], first['closed_urls'], first['stamp'])
        gone = store.record_source(db, SOURCE, [row('https://x/1')], 'complete', 'full', 1)
        store.append_log(db, gone['new_urls'], gone['closed_urls'], gone['stamp'])
        store.export_state(db)
        db.commit()
        expected = self.snapshot(self.db_path)
        self.assertEqual(len(expected), 2)

        # A fresh runner: the catalog exists, the collected data does not.
        fresh = Path(self.dir.name) / 'fresh.sqlite'
        with closing(sqlite3.connect(fresh)) as blank:
            blank.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            blank.execute("INSERT INTO companies VALUES ('matx', 'MatX')")
        counts = store.rebuild(fresh)
        self.assertEqual(counts, {'jobs': 2, 'events': 1, 'sources': 1})
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


class EarlyStopTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()


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
        delta = store.record_source(self.db, SOURCE, [row('https://x/1')],
                                    'complete', 'full', 1)
        self.assertEqual(delta['closed'], 1)
        self.assertEqual(self.open_count(), 1)


class EmptyBoardTests(unittest.TestCase):
    """An empty listing is only trusted when the board confirms it.

    'complete' is what permits the store to retire a company's whole inventory, so
    a blank first page must not claim it on its own: that is also what a board
    looks like mid-deploy, or after a schema change we failed to parse.
    """

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
        c = self.collector('eightfold', 'https://careers.x.com/api/pcsx/search?domain=x.com')
        position = {'id': '1', 'name': 'Engineer', 'positionUrl': '/careers/job/1'}
        c.session.request.side_effect = [
            self.response({'data': {'positions': [position], 'count': 99}}),
            self.response({'data': {'positions': [], 'count': 99}}),
        ]
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(), ('complete', ''))
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

    def test_enough_strong_terms_is_certain(self):
        loaded = self.posting('Engineer', job_description=(
            'RTL, UVM, SystemVerilog, AXI, testbench, tape-out, PrimeTime.'))
        self.assertEqual(self.jsearch.relevance(loaded, self.rules)[0], 100)

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

    def test_individual_contributor_titles_are_untouched(self):
        for title in ('RTL Design Engineer', 'Senior Design Verification Engineer',
                      'Principal Engineer, SoC', 'Staff FPGA Engineer'):
            with self.subTest(title=title):
                self.assertFalse(self.jsearch.excluded(title, self.rules))
