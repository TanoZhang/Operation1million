"""A fifth twenty, found on 2026-09-27, each red on 9451fbe.

Numbered 81-100 in `docs/bug-tracker.md`, continuing `test_fifth_bug_hunt.py`.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jobdisco import applications, jsearch, ranking
from jobdisco.experience import evaluate
from jobdisco.job_text import clean_title
from jobdisco.location import country

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


def verdict(title):
    if jsearch.excluded(title, RULES):
        return 'excluded'
    if jsearch.title_blocked(title, RULES):
        return 'blocked'
    return 'ok'


def us_person(text):
    return jsearch.us_person_required(text, RULES)


class QueueTests(unittest.TestCase):
    def test_81_a_posting_first_seen_after_the_clock_is_still_listed(self):
        """A pass on a machine whose clock runs ahead stamps first_seen in the
        review server's future; the posting was in neither tab."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        db, ledger = root / 'jobs.sqlite', root / 'operational/applications.ndjson'
        now = datetime.now(timezone.utc)
        ahead = (now + timedelta(minutes=5)).isoformat()
        with closing(sqlite3.connect(db)) as con, con:
            con.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample Semiconductor');
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
            con.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('https://example.test/ahead', 'sample', 'RTL Engineer', 'Austin, TX', 'req-1',
                         ahead, None, 'direct', 80, None,
                         json.dumps({'description': '<p>Design hardware.</p>'}), ahead))
        state = applications.queue(db, ledger, now)
        self.assertEqual([g['jobs'][0]['url'] for g in state['pending']], ['https://example.test/ahead'])


class TitleRuleTests(unittest.TestCase):
    def test_82_low_power_design(self):
        self.assertEqual(verdict('Low Power Design Engineer'), 'ok')
        self.assertEqual(verdict('Low-Power SoC Design Intern'), 'ok')
        self.assertEqual(verdict('Power Integrity Engineer'), 'ok')

    def test_83_mixed_signal_verification(self):
        self.assertEqual(verdict('Analog Mixed Signal Verification Engineer'), 'ok')
        self.assertEqual(verdict('AMS Verification Engineer'), 'ok')
        self.assertEqual(verdict('Analog Design Engineer'), 'ok')

    def test_84_a_recruiter_is_not_the_trade(self):
        for title in ('Technical Recruiter - Silicon', 'Talent Acquisition Partner, ASIC'):
            with self.subTest(title=title):
                self.assertEqual(verdict(title), 'excluded')

    def test_85_security_operations_soc(self):
        for title in ('SOC Analyst', 'Cybersecurity SOC Engineer',
                      'Security Operations Center (SOC) Engineer', 'SOC Intern (Security Operations)'):
            with self.subTest(title=title):
                self.assertEqual(jsearch.rejection_reason({'title': title, 'raw': {}}, RULES), 'excluded')
                self.assertNotIn(ranking.bucket(title), (0, 2))
        self.assertEqual(jsearch.rejection_reason({'title': 'SoC Design Intern', 'raw': {}}, RULES), '')
        self.assertEqual(ranking.bucket('SoC Design Intern'), 0)


class ExperienceTests(unittest.TestCase):
    def test_86_full_width_characters(self):
        self.assertEqual(years('5＋ years of experience'), 5)
        self.assertEqual(years('５+ years of experience'), 5)

    def test_90_a_tilde_range(self):
        self.assertEqual(years('3~5 years of experience'), 3)
        self.assertEqual(years('3 ~ 5 years of experience'), 3)

    def test_91_through(self):
        self.assertEqual(years('3 through 5 years of experience'), 3)
        self.assertEqual(years('3 thru 5 years of experience'), 3)

    def test_92_a_hyphenated_spelled_range(self):
        self.assertEqual(years('three-to-five years of experience'), 3)

    def test_93_either_of_two_counts(self):
        self.assertEqual(years('2 or 3 years of experience'), 2)
        self.assertEqual(years('2/3 years of experience'), 2)
        self.assertEqual(years('3 or more years of experience'), 3)

    def test_94_more_form_labels(self):
        for text in ('Years experience: 3+', 'Yrs of experience: 3', 'Experience (years): 3',
                     '# of years experience: 3'):
            with self.subTest(text=text):
                self.assertEqual(years(text), 3)


class CitizenshipTests(unittest.TestCase):
    def test_87_an_html_entity_or_a_no_break_space(self):
        self.assertTrue(us_person('U.S.&nbsp;citizenship is required'))
        self.assertTrue(us_person('Must be a U.S. citizen'))

    def test_95_some_positions(self):
        for text in ('Some positions require U.S. citizenship.', 'Certain roles require US citizenship',
                     'Many of our positions require US citizenship', 'Most positions require U.S. citizenship',
                     'In some cases, US citizenship is required'):
            with self.subTest(text=text):
                self.assertFalse(us_person(text))

    def test_96_positions_that_require_it(self):
        for text in ('For positions requiring access to classified information, U.S. citizenship is required.',
                     'Applicants for positions that require U.S. citizenship must be U.S. citizens'):
            with self.subTest(text=text):
                self.assertFalse(us_person(text))

    def test_97_scoped_to_other_work(self):
        for text in ('U.S. citizenship is required for positions supporting government contracts.',
                     'US citizenship required only for defense programs'):
            with self.subTest(text=text):
                self.assertFalse(us_person(text))
        self.assertTrue(us_person('U.S. citizenship is required for this position.'))

    def test_100_a_work_visa_as_the_other_way_in(self):
        for text in ('Candidates must be U.S. citizens or hold a valid work visa',
                     'Must be a US citizen or have valid work authorization',
                     'Must be a U.S. citizen or H-1B holder'):
            with self.subTest(text=text):
                self.assertFalse(us_person(text))
        self.assertTrue(us_person('Must be a U.S. citizen or permanent resident'))


class LocationTests(unittest.TestCase):
    def test_88_diacritics(self):
        for place in ('Gdańsk', 'Timișoara', 'Iași'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'foreign')

    def test_89_semiconductor_sites_abroad(self):
        for place in ('Pyeongtaek', 'Giheung', 'Taoyuan', 'Wuxi, Jiangsu', 'Xiamen, Fujian',
                      'Cyberjaya', 'Rousset'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'foreign')


class RankingTests(unittest.TestCase):
    def test_98_a_campus_that_is_a_place(self):
        self.assertFalse(ranking.early_career('Campus Network Engineer'))
        self.assertFalse(ranking.early_career('Campus Security Officer'))
        self.assertTrue(ranking.early_career('Campus Hire - RTL Engineer'))
        self.assertTrue(ranking.early_career('RTL Engineer (Campus)'))


class CleanTitleTests(unittest.TestCase):
    def test_99_a_state_named_the_other_way(self):
        self.assertEqual(clean_title('RTL Engineer - San Jose, California', 'San Jose, CA, US'), 'RTL Engineer')
        self.assertEqual(clean_title('RTL Engineer - San Jose, CA', 'San Jose, California, United States'),
                         'RTL Engineer')


if __name__ == '__main__':
    unittest.main()
