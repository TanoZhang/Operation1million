"""Five defects from an external review of 7c7ff44, 2026-10-16.

Each was reproduced here before its fix; the review's numbers are its own, and
the ones measured on this machine are in docs/handoff.md.
"""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from operation1million import applications, jsearch, manual_intake as intake, store
from operation1million.jsearch_access import AccountPaused, QuotaExhausted, RequestGuard
from operation1million.location import country

SEARCH = {'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
          'connection': {'auth_header': 'x-api-key'}}


def empty():
    return {name: [] for name in ('pending', 'backlog', 'applied', 'skipped')}


class RequisitionIndexTests(unittest.TestCase):
    def test_alias_lookup_by_requisition_uses_an_index(self):
        """record_source looks up every requisition's other URLs; with only
        (company_key, closed_at) indexed, a direct board's pass grew with the
        square of its size."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
                db.commit()
            store.migrate(path)
            with closing(sqlite3.connect(path)) as db:
                plan = ' '.join(row[-1] for row in db.execute(
                    '''EXPLAIN QUERY PLAN SELECT url FROM jobs WHERE provider_key=? AND source_job_id=?
                       AND url<>? AND closed_at IS NULL AND company_key=?''', ('workday', '1', 'u', 'c')))
        self.assertIn('jobs_requisition', plan)


class DamagedImportLineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.ledger = Path(temporary.name) / 'decisions.ndjson'
        group = intake.create_group('https://company.example/R1', intake.posting_metadata(
            '', {'title': 'RTL Design Engineer', 'company': 'Example'}))
        intake.save_manual(self.ledger, group)
        applications.append_decision(self.ledger, group, 'applied', 'Applied by Muse')
        self.group = group
        path = intake.path_for(self.ledger)
        with path.open('a', encoding='utf-8') as handle:
            handle.write('{broken\n')

    def test_review_page_still_loads(self):
        state = intake.augment_queue(empty(), self.ledger)
        self.assertEqual([g['id'] for g in state['applied']], [self.group['id']])

    def test_decided_postings_still_read(self):
        self.assertIn(self.group['jobs'][0]['url'], intake.decided_urls(self.ledger, None))


class RetriedQueryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        p = patch('operation1million.jsearch_access.time.sleep', Mock())
        p.start()
        self.addCleanup(p.stop)
        p = patch.dict('os.environ', {'JSEARCH_API_KEY': 'offline-test-placeholder'})
        p.start()
        self.addCleanup(p.stop)
        self.settings, _ = jsearch.load_plan()
        guard = RequestGuard(Path(temporary.name) / 'usage.sqlite', daily_limit=320, target_limit=9600)
        self.session = Mock()
        self.client = jsearch.Client(SEARCH, self.settings, guard, session=self.session)

    def response(self, status=200, jobs=()):
        response = Mock(status_code=status, headers={})
        response.json.return_value = {'status': 'OK', 'data': {'jobs': list(jobs), 'cursor': None}}
        return response

    def test_a_retry_that_succeeded_is_not_the_query_s_failure(self):
        job = {'job_id': 'a', 'job_title': 'RTL Design Engineer', 'employer_name': 'Analog Devices',
               'job_apply_link': 'https://jobs.example/a',
               'job_description': 'Full responsibilities and qualifications. ' * 500}
        self.session.get.side_effect = [self.response(504), self.response(jobs=[job])]
        _, stats = jsearch.collect([jsearch.Query('RTL Design Engineer', 5, 'A')],
                                   self.client, self.settings, {}, lambda *args: None)
        detail = stats['jsearch_queries'][0]
        self.assertEqual(self.session.get.call_count, 2)
        self.assertNotEqual(detail['status'], 'failed')
        self.assertNotIn('504', detail['reason'])


class PausedAccountTests(unittest.TestCase):
    def test_a_pause_is_reported_as_a_pause_even_with_the_day_spent(self):
        """A provider refusal is a failure, not budget completion (AGENTS.md)."""
        with tempfile.TemporaryDirectory() as folder:
            guard = RequestGuard(Path(folder) / 'usage.sqlite', daily_limit=2, interval=0)
            session = Mock()
            session.get.return_value = Mock(status_code=200, headers={})
            guard.get(session, 'https://example.com')
            guard.get(session, 'https://example.com')
            guard.pause(3600)
            with self.assertRaises(AccountPaused):
                guard.get(session, 'https://example.com')

    def test_the_month_counts_the_baseline_once(self):
        with tempfile.TemporaryDirectory() as folder:
            guard = RequestGuard(Path(folder) / 'usage.sqlite', target_limit=3, interval=0)
            session = Mock()
            session.get.return_value = Mock(status_code=200, headers={})
            with closing(sqlite3.connect(guard.path)) as db, db:
                db.execute('INSERT INTO credit_baseline VALUES (?, 2)', (guard.period()[0],))
            guard.get(session, 'https://example.com')
            with self.assertRaises(QuotaExhausted) as raised:
                guard.get(session, 'https://example.com')
            self.assertNotIsInstance(raised.exception, AccountPaused)


class GeorgiaTests(unittest.TestCase):
    def test_the_country_is_abroad_and_the_state_is_not(self):
        for text in ('Tbilisi, Georgia', 'Tbilisi', 'Batumi, Georgia'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'foreign')
        for text in ('Atlanta, Georgia', 'Atlanta, GA', 'Savannah, Georgia', 'Georgia',
                     'Georgia, United States'):
            with self.subTest(text=text):
                self.assertEqual(country(text), 'us')



class SecondRoundTests(unittest.TestCase):
    """The same reviewer's second round, 2026-10-16."""

    def test_a_company_s_decade_is_not_a_requirement(self):
        from operation1million.experience import evaluate
        for blurb in ('Acme brings a decade of experience shipping chips.',
                      'Acme boasts over 10 years of experience shipping chips.'):
            with self.subTest(blurb=blurb):
                found = evaluate('RTL Design Engineer',
                                 blurb + '\n\nRequirements:\n- 1+ years of RTL design experience.')
                self.assertEqual(found['hard_pass_reason'], '')
        # Asked of the applicant it is still ten years (#259).
        found = evaluate('RTL Design Engineer', 'Requirements: a decade of experience in RTL design.')
        self.assertEqual(found['effective_experience_years'], 10)

    def test_remote_us_names_no_city(self):
        for place in ('Remote - US', 'US - Remote', 'Remote (US)', 'United States (Remote)',
                      'Remote, US', 'Remote - USA'):
            with self.subTest(place=place):
                self.assertTrue(applications._vague(place))
        self.assertFalse(applications._vague('Austin, TX'))

    def test_students_are_early_career_on_the_review_page(self):
        from operation1million import ranking
        self.assertTrue(ranking.EARLY_CAREER.search('ASIC Summer Students 2027'))

    def test_a_text_date_with_a_time_is_a_date(self):
        from datetime import date
        from operation1million import ranking
        for text in ('Oct 1, 2026 12:00:00 PM', 'October 1, 2026 12:00 PM', 'Oct 1, 2026 14:05'):
            with self.subTest(text=text):
                self.assertEqual(ranking.posted_day(text), date(2026, 10, 1))

    def test_a_mail_date_without_a_zone_is_utc(self):
        from operation1million import gmail_outcomes
        raw = (b'From: HR <hr@example.com>\r\nSubject: Update\r\n'
               b'Date: Thu, 01 Oct 2026 12:00:00 -0000\r\n\r\nThank you.\r\n')
        self.assertEqual(gmail_outcomes.parse(raw, '1')['at'], '2026-10-01T12:00:00+00:00')


class ApplicationLimitsCacheTests(unittest.TestCase):
    def test_editing_the_caps_rebuilds_the_queue(self):
        """review.queue_key tracked every input but application_limits.toml."""
        import json, threading
        from urllib.request import urlopen
        from operation1million import application_limits, review
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            limits = folder / 'application_limits.toml'
            limits.write_text('', encoding='utf-8')
            db = folder / 'index.sqlite'
            with closing(sqlite3.connect(db)) as con:
                con.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
                con.commit()
            builds = []

            def queue(*args, **kwargs):
                builds.append(1)
                return empty()
            with patch.object(application_limits, 'PATH', limits), \
                 patch.object(review.applications, 'queue', side_effect=queue):
                server = review.make_server(db, folder / 'decisions.ndjson', port=0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = f'http://127.0.0.1:{server.server_port}'
                    json.load(urlopen(base + '/api/queue'))
                    json.load(urlopen(base + '/api/queue'))
                    self.assertEqual(len(builds), 1)
                    limits.write_text('# changed\n', encoding='utf-8')
                    json.load(urlopen(base + '/api/queue'))
                    self.assertEqual(len(builds), 2)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()


class EmployerVoiceTests(unittest.TestCase):
    """Round two, bug 1, finished (the user, 2026-10-16): the parser is given
    the employer's name, so the employer describing itself is not a requirement."""

    def evaluate(self, description, employer='Acme'):
        return jsearch.experience_debug({'title': 'RTL Design Engineer', 'company_name': employer},
                                        description)

    def test_the_employer_s_own_years_are_not_required(self):
        for blurb in ('Acme: a decade of experience shipping chips.',
                      'Acme: 10 years of experience shipping chips.',
                      'Acme has a decade of experience shipping chips.',
                      'ACME has over 15 years of experience in mixed-signal design.'):
            with self.subTest(blurb=blurb):
                found = self.evaluate(blurb + '\n\nRequirements:\n- 1+ years of RTL design experience.')
                self.assertEqual(found['hard_pass_reason'], '')
                self.assertEqual(found['effective_experience_years'], 1)
        found = self.evaluate('Acme: a decade of experience shipping chips.\n\nRequirements:\n'
                              '- 1+ years of RTL design experience.', employer='Acme, Inc.')
        self.assertEqual(found['hard_pass_reason'], '')

    def test_an_applicant_s_years_still_count(self):
        for text in ('Requirements:\n- Has 5+ years of RTL design experience.',
                     'Requirements: a decade of experience in RTL design.',
                     'Acme is hiring. Requirements: 5+ years of RTL design experience.'):
            with self.subTest(text=text):
                self.assertEqual(self.evaluate(text)['hard_pass_reason'], 'required_experience_over_2_years')

    def test_the_review_queue_passes_the_employer(self):
        """The queue's filter row carried only title and raw."""
        rules = jsearch.load_plan()[0]['filter']
        row = {'title': 'RTL Design Engineer', 'company_name': 'Acme',
               'raw': {'description': 'Acme: a decade of experience shipping chips. '
                                      'Requirements: 1+ years of RTL design experience.'}}
        reason, _ = jsearch.eligibility_rejection(row, rules)
        self.assertEqual(reason, '')


class ByteDanceReferableTests(unittest.TestCase):
    """Round two, bug 9: ByteDance is referable as TikTok is (the user, 2026-10-16)."""

    def test_bytedance_is_marked_and_a_namesake_is_not(self):
        from operation1million import export
        for name in ('ByteDance', 'Bytedance Inc.', 'TikTok', 'NVIDIA'):
            with self.subTest(name=name):
                self.assertTrue(export.referalble(name))
        for name in ('NVIDIA Staffing', 'Other Semiconductor', ''):
            with self.subTest(name=name):
                self.assertFalse(export.referalble(name))

    def test_the_page_reads_the_server_s_mark(self):
        """The page kept its own list of six display names (third round)."""
        from operation1million import review
        state = {'pending': [{'id': 'a', 'company': 'ByteDance', 'jobs': []},
                             {'id': 'b', 'company': 'NVIDIA Staffing', 'jobs': []}],
                 'backlog': [], 'applied': [], 'skipped': []}
        slim = review.slim(state)['pending']
        self.assertEqual([group.get('referalble', False) for group in slim], [True, False])


if __name__ == '__main__':
    unittest.main()
