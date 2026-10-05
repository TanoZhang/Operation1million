"""An eighth twenty, found on 2026-09-27, each red on 90f2f4b.

Numbered 141-160 in `docs/bug-tracker.md`; the last batch of the hundred the
user asked for after #60.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from operation1million import applications, jsearch, ranking, store
from operation1million.collection_policy import crawl_delay
from operation1million.collector import posted_from_text
from operation1million.experience import evaluate
from operation1million.job_text import clean_title

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


def day(text):
    found = ranking.posted_day(text)
    return found.isoformat() if found else None


def us_person(text):
    return jsearch.us_person_required(text, RULES)


class DateTests(unittest.TestCase):
    def test_141_a_two_digit_year(self):
        self.assertEqual(day('09/07/26'), '2026-09-07')

    def test_142_year_first_with_slashes_or_points(self):
        self.assertEqual(day('2026/09/07'), '2026-09-07')
        self.assertEqual(day('2026.09.07'), '2026-09-07')

    def test_143_day_first(self):
        self.assertEqual(day('07.09.2026'), '2026-09-07')
        self.assertEqual(day('7-Sep-2026'), '2026-09-07')
        self.assertEqual(day('07-Sep-2026'), '2026-09-07')

    def test_144_ordinals_weekdays_and_no_comma(self):
        for text in ('September 7th, 2026', 'Sep 7th, 2026', 'Sunday, September 7, 2026',
                     'Sep 7 2026', '7 Sep, 2026'):
            with self.subTest(text=text):
                self.assertEqual(day(text), '2026-09-07')

    def test_145_a_board_row_reads_every_format_the_queue_does(self):
        for text in ('Posted 09/07/26', 'Posted 2026/09/07', 'Posted September 7th, 2026',
                     'Posted Sunday, September 7, 2026'):
            with self.subTest(text=text):
                self.assertEqual(posted_from_text(text), '2026-09-07')


class ExperienceTests(unittest.TestCase):
    def test_146_new_grads_invited(self):
        found = evaluate('RTL Design Engineer', '5+ years of experience in chip design; '
                         'new grads encouraged to apply')
        self.assertTrue(found['entry_override'])

    def test_148_the_companys_other_programmes(self):
        for boilerplate in ('We also run a summer internship program for students.',
                            'Ask about our internship program.',
                            'Acme also offers new grad and internship opportunities.',
                            'Students may apply to our internship roles separately.',
                            'Internship and co-op opportunities are posted separately.'):
            with self.subTest(boilerplate=boilerplate):
                found = evaluate('ASIC Design Engineer', '8+ years of experience in ASIC design.\n' + boilerplate)
                self.assertFalse(found['entry_override'])
        self.assertTrue(evaluate('Hardware Engineer', 'This role is also open to new grads.')['entry_override'])

    def test_153_working_as_the_intern(self):
        for body in ('You will work as an intern on the DV team.', 'Work as a co-op in our ASIC group.',
                     'Collaborate as a new grad with our RTL team.', 'You will be working as an intern.'):
            with self.subTest(body=body):
                self.assertTrue(evaluate('Hardware Engineer', body + ' 3+ years of hands-on experience.')['entry_override'])
        self.assertFalse(evaluate('Staff Engineer', 'You will work with our interns. 8+ years.')['entry_override'])

    def test_154_a_duration_or_term(self):
        for line in ('Position duration: 3 years', 'Contract length: 3 years', 'Assignment term: 3 years',
                     'Must commit to 3 years'):
            with self.subTest(line=line):
                self.assertIsNone(years('Requirements:\n- BS in EE\n- ' + line))

    def test_156_the_length_of_a_degree(self):
        self.assertIsNone(years("Requirements:\n- Bachelor's degree (4-year)"))
        self.assertIsNone(years("Bachelor's degree (4 year) in EE required"))


class RobotsTests(unittest.TestCase):
    def test_147_another_crawlers_name_containing_part_of_ours(self):
        self.assertEqual(crawl_delay('User-agent: Job\nCrawl-delay: 600\n\nUser-agent: *\nCrawl-delay: 2\n'), 2)
        self.assertEqual(crawl_delay('User-agent: collector\nCrawl-delay: 600\n\nUser-agent: *\nCrawl-delay: 2\n'), 2)
        self.assertEqual(crawl_delay('User-agent: JobSourceCollector\nCrawl-delay: 5\n\nUser-agent: *\nCrawl-delay: 2\n'), 5)
        self.assertEqual(crawl_delay('User-agent: jobsourcecollector/1.0\nCrawl-delay: 5\n'), 5)


class LedgerTests(unittest.TestCase):
    def ledger(self, content):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'applications.ndjson'
        path.write_bytes(content.encode('utf-8'))
        return path

    line = json.dumps({'id': '1', 'url': 'https://x/1', 'at': '2026-09-27T00:00:00+00:00',
                       'status': 'skipped'}) + '\n'

    def test_149_a_blank_line(self):
        self.assertEqual(len(applications.read_events(self.ledger(self.line + '\n' + self.line))), 2)
        with self.assertRaises(ValueError):
            applications.read_events(self.ledger(self.line + '{"torn": '))

    def test_150_a_byte_order_mark(self):
        self.assertEqual(len(applications.read_events(self.ledger('﻿' + self.line))), 1)


class TitleRuleTests(unittest.TestCase):
    def test_151_senior_as_a_students_year(self):
        for title in ('Hardware Engineering Intern (Junior/Senior)', 'ASIC Intern - Rising Senior',
                      'Senior Year Internship - RTL', 'Undergraduate Intern (Senior standing)',
                      'Senior Design Project Intern'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, RULES))
        self.assertTrue(jsearch.excluded('Senior ASIC Engineer', RULES))


class CitizenshipTests(unittest.TestCase):
    def test_152_under_a_preferred_heading(self):
        self.assertFalse(us_person('Preferred: Must be a US citizen'))
        self.assertFalse(us_person('Preferred Qualifications:\n- Must be a U.S. citizen'))
        self.assertTrue(us_person('Preferred Qualifications:\n- Python\nRequirements:\n- Must be a U.S. citizen'))

    def test_157_a_condition_after_it(self):
        for text in ('Must be a U.S. citizen if working on ITAR projects', 'U.S. citizenship is required where applicable',
                     'Must be a U.S. citizen when required by the customer', 'Must be a US citizen, depending on the program'):
            with self.subTest(text=text):
                self.assertFalse(us_person(text))

    def test_158_an_export_licence_instead(self):
        self.assertFalse(us_person('U.S. citizenship required unless an export license is obtained'))
        self.assertFalse(us_person('Must be a U.S. citizen, or eligible for an export license'))


class StoreTests(unittest.TestCase):
    def test_155_since_compares_instants(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'jobs.sqlite'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  provider_key TEXT, posted_at TEXT, posted_relative TEXT,
                                  first_seen TEXT, relevance REAL, closed_at TEXT);''')
            # A space where the log writes "T": the same instant, a smaller string.
            db.execute("INSERT INTO jobs VALUES ('https://x/1', 'acme', 'RTL Engineer', 'Austin, TX', "
                       "'direct', NULL, NULL, '2026-09-20 10:00:00', 80, NULL)")
        self.assertEqual(len(store.ranked(path, since='2026-09-20T00:00:00+00:00')), 1)
        self.assertEqual(len(store.ranked(path, since='2026-09-21')), 0)


class ReviewTests(unittest.TestCase):
    def test_159_the_ipv6_loopback(self):
        from operation1million import review
        self.assertTrue(review.local_host('[::1]:8765'))
        self.assertTrue(review.local_host('localhost:8765'))
        self.assertTrue(review.local_host('127.0.0.1'))
        self.assertFalse(review.local_host('evil.example:8765'))
        self.assertFalse(review.local_host('127.0.0.1.evil.example'))


class CleanTitleTests(unittest.TestCase):
    def test_160_a_location_joined_with_a_dash(self):
        self.assertEqual(clean_title('RTL Engineer - Remote - US', 'Remote, US'), 'RTL Engineer')
        self.assertEqual(clean_title('RTL Engineer (Remote - US)', 'Remote, US'), 'RTL Engineer')


if __name__ == '__main__':
    unittest.main()
