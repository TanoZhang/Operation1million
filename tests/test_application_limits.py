"""Capped employers keep only postings worth a slot (2026-10-08)."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from operation1million import application_limits as limits


RULES = {'filter': {'min_confidence': 40},
         'limit': [{'provider': 'ashby', 'applications': 5, 'days': 180},
                   {'employer': 'Amazon', 'active': 10},
                   {'employer': 'Google', 'applications': 3, 'days': 30}]}
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def group(company, title, confidence, bucket, provider='workday', **extra):
    return dict({'id': f'{company}/{title}', 'company': company, 'title': title, 'confidence': confidence,
                 'bucket': bucket, 'jobs': [{'url': f'https://{company}.example/{title}', 'provider_key': provider}]},
                **extra)


def state(pending=(), backlog=(), applied=()):
    return {'pending': list(pending), 'backlog': list(backlog), 'applied': list(applied), 'skipped': []}


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


class Filtering(unittest.TestCase):
    def kept(self, queue, db=None):
        limits.apply(queue, db, RULES, now=NOW)
        return [item['title'] for name in ('pending', 'backlog') for item in queue[name]]

    def test_a_capped_employer_keeps_only_postings_worth_a_slot(self):
        queue = state([group('Google', 'RTL Design Engineer, TPU', 62, 2),
                       group('Google', 'Camera Electrical Engineer', 21, 3),
                       group('Google', 'Software Engineer III, YouTube', 55, 4)],
                      [group('Amazon', 'MLA IP Design Verification Engineer', 42, 2),
                       group('Amazon', 'Controls Integration Engineer', 12, 4),
                       group('Amazon', 'Hardware Validation Engineer, NPD Hardware', 25, 2)])
        self.assertEqual(self.kept(queue), ['RTL Design Engineer, TPU', 'MLA IP Design Verification Engineer'])

    def test_an_uncapped_employer_is_untouched(self):
        queue = state([group('Apple', 'Camera Electrical Engineer', 21, 3),
                       group('Apple', 'Store Leader', 0, 4)])
        self.assertEqual(len(self.kept(queue)), 2)

    def test_an_employer_on_ashby_is_capped_wherever_its_posting_was_found(self):
        queue = state([group('OpenAI', 'Camera Software Engineer', 52, 4, provider='ashby'),
                       group('OpenAI', 'Network Engineer', 17, 3, provider='jsearch'),
                       group('OpenAI', 'Software Engineer, AI for Chip Design', 62, 2, provider='jsearch')])
        self.assertEqual(self.kept(queue), ['Software Engineer, AI for Chip Design'])

    def test_the_index_names_employers_on_ashby(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'index.sqlite'
            with closing(sqlite3.connect(db)) as con, con:
                con.executescript('CREATE TABLE companies(company_key TEXT, name TEXT);'
                                  'CREATE TABLE jobs(url TEXT, company_key TEXT, provider_key TEXT, raw TEXT);'
                                  "INSERT INTO companies VALUES ('etched', 'Etched');"
                                  "INSERT INTO jobs VALUES ('https://jobs.ashbyhq.com/etched/1', 'etched', 'ashby', '{}');")
            queue = state([group('Etched', 'Firmware Engineer', 25, 3, provider='jsearch')])
            self.assertEqual(self.kept(queue, db), [])

    def test_a_pasted_posting_is_the_users_choice(self):
        queue = state([group('Google', 'Camera Electrical Engineer', 21, 3, manual_import=True)])
        self.assertEqual(self.kept(queue), ['Camera Electrical Engineer'])

    def test_aliases_are_one_employer(self):
        queue = state([group('Annapurna Labs', 'Robotics Field Engineer', 6, 4)])
        self.assertEqual(self.kept(queue), [])


class Slots(unittest.TestCase):
    def label(self, queue):
        limits.apply(queue, None, RULES, now=NOW)
        return queue['pending'][0]['application_limit']

    def test_applications_inside_the_window_are_counted(self):
        queue = state([group('Google', 'RTL Design Engineer', 62, 2)], applied=[
            group('Google', 'A', 62, 2, at=ago(3)), group('Google', 'B', 62, 2, at=ago(29)),
            group('Google', 'C', 62, 2, at=ago(31)), group('Apple', 'D', 62, 2, at=ago(1))])
        self.assertEqual(self.label(queue), 'Google allows 3 applications per 30 days; 2 used')

    def test_active_applications_are_those_not_declined(self):
        queue = state([group('Amazon', 'ASIC Engineer', 76, 0)], applied=[
            group('AWS', 'A', 62, 2, at=ago(100)), group('Amazon', 'B', 62, 2, at=ago(3), outcome='declined'),
            group('Annapurna Labs', 'C', 62, 2, at=ago(1))])
        self.assertEqual(self.label(queue), 'Amazon allows 10 active applications; 2 applied and not declined')

    def test_a_full_employer_says_so(self):
        queue = state([group('Google', 'RTL Design Engineer', 62, 2)],
                      applied=[group('Google', name, 62, 2, at=ago(1)) for name in 'ABC'])
        self.assertTrue(self.label(queue).endswith('3 used -- full'))

    def test_ashby_names_the_employer(self):
        queue = state([group('OpenAI', 'RTL Engineer', 62, 2, provider='ashby')],
                      applied=[group('OpenAI', 'A', 62, 2, at=ago(170))])
        self.assertEqual(self.label(queue), 'OpenAI allows 5 applications per 180 days; 1 used')


class Configuration(unittest.TestCase):
    def test_the_shipped_configuration_loads(self):
        rules = limits.load()
        self.assertGreaterEqual(rules['filter']['min_confidence'], 1)
        self.assertTrue(all(('employer' in item) != ('provider' in item) for item in rules['limit']))
        self.assertTrue(all(('active' in item) != ('applications' in item and 'days' in item)
                            for item in rules['limit']))


if __name__ == '__main__':
    unittest.main()
