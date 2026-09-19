"""One alternation must answer exactly what sixty patterns answered.

Asking "does any of these match" by trying each costs a pass over the string per
pattern; asking it once as an alternation costs one. That is worth doing only if
the answer never differs, so this checks the new form against the old one rather
than against examples -- on the shipped rules, on the shapes that make
alternation subtle, and on every title and employer the store actually holds.
"""
from pathlib import Path
import re
import sqlite3
import unittest

from jobdisco import jsearch

ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / 'data/db/job_discovery.sqlite'


def one_at_a_time(patterns, text):
    """What the code did before: try each pattern in turn."""
    return any(re.search(p, text or '', re.I) for p in patterns)


class EquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']
        self.titles = self.rules['exclude_title_patterns']
        self.employers = self.rules['exclude_employer_patterns']

    def assert_same(self, patterns, text):
        combined = jsearch.any_of(patterns)
        self.assertEqual(bool(combined and combined.search(text or '')),
                         one_at_a_time(patterns, text), repr(text))

    def test_the_shipped_title_rules_agree_on_the_obvious_cases(self):
        for title in ('Senior RTL Design Engineer', 'RTL Design Engineer',
                      'Director of Silicon', 'Data Center Technician',
                      'Analog IC Design Engineer', 'Staff Verification Engineer',
                      'Technical Sales Engineer', '', 'Engineer'):
            self.assert_same(self.titles, title)

    def test_anchored_patterns_keep_their_anchors(self):
        """`^\\s*RTX...$` must not start matching in the middle of a name."""
        for employer in ('RTX', 'RTX Corporation', 'NOT RTX Corporation',
                         'Raytheon', 'SAIC', 'Some SAIC Partner', 'Example Inc.'):
            self.assert_same(self.employers, employer)

    def test_an_empty_rule_list_excludes_nothing(self):
        self.assertIsNone(jsearch.any_of([]))
        self.assertFalse(jsearch.excluded('anything', {'exclude_title_patterns': []}))
        self.assertFalse(jsearch.excluded('anything', {}))

    def test_a_changed_rule_set_is_not_served_the_previous_answer(self):
        """The cache is keyed by the patterns, not by the rules object."""
        self.assertTrue(jsearch.excluded('Nurse', {'exclude_title_patterns': [r'\bnurse\b']}))
        self.assertFalse(jsearch.excluded('Nurse', {'exclude_title_patterns': [r'\bpilot\b']}))

    def test_alternation_precedence_cannot_leak_between_patterns(self):
        """Without non-capturing groups, `ab|c` and `d` would combine wrongly."""
        patterns = [r'^ab|c$', r'd']
        for text in ('ab', 'c', 'd', 'abd', 'xcx', 'xc', 'ax'):
            self.assert_same(patterns, text)

    def test_patterns_that_can_match_empty_behave_the_same(self):
        for patterns in ([r'x*'], [r'', r'\bzzz\b'], [r'(?:)']):
            for text in ('', 'anything'):
                self.assert_same(patterns, text)


@unittest.skipUnless(LIVE_DB.is_file(), 'no local store to check against')
class AgainstEveryRowTests(unittest.TestCase):
    """Examples are what a person thought of. This is what the provider sent."""

    def test_every_title_and_employer_in_the_store_gets_the_same_verdict(self):
        rules = jsearch.load_plan()[0]['filter']
        titles = rules['exclude_title_patterns']
        employers = rules['exclude_employer_patterns']
        con = sqlite3.connect(f'file:{LIVE_DB.as_posix()}?mode=ro', uri=True)
        try:
            rows = con.execute('SELECT DISTINCT title FROM jobs').fetchall()
            names = con.execute('SELECT DISTINCT name FROM companies').fetchall()
        finally:
            con.close()
        self.assertGreater(len(rows), 100, 'the store is too small to be a real check')
        combined = jsearch.any_of(titles)
        for (title,) in rows:
            if bool(combined.search(title or '')) != one_at_a_time(titles, title):
                self.fail(f'title verdict differs: {title!r}')
        combined = jsearch.any_of(employers)
        for (name,) in names:
            if bool(combined.search(name or '')) != one_at_a_time(employers, name):
                self.fail(f'employer verdict differs: {name!r}')


if __name__ == '__main__':
    unittest.main()
