"""Four new offline eligibility regressions on source b2c9340.

Run: python docs/review-audit-repro-round2-2026-09-23.py
Four regression tests fail on the audited source; four controls pass.
Only temporary fixture databases, logs and ledgers are used.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from jobdisco import applications, jsearch
import test_review_description as fixtures


class EligibilityAudit(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DescriptionTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.rules = jsearch.load_plan()[0]['filter']

    def verdict(self, raw):
        job = fixtures.row('audit2', 'https://example.test/audit2', raw=raw)
        self.fixture.persist([job])
        stored = json.loads(self.fixture.db.execute('SELECT raw FROM jobs').fetchone()[0])
        reason, facts = jsearch.eligibility_rejection(dict(job, raw=stored), self.rules)
        pending = len(applications.queue(self.fixture.path, self.fixture.ledger)['pending'])
        return reason, facts['effective_experience_years'], pending

    def test_r4_negated_citizenship_requirement_keeps_the_posting(self):
        actual = self.verdict({'description': 'This position does not require US citizenship.'})
        self.assertEqual(actual, ('', None, 1))

    def test_r4_positive_citizenship_control(self):
        self.assertEqual(self.verdict({'description': 'This position requires US citizenship.'}),
                         ('us_person_required', None, 0))

    def test_r5_requirements_field_keeps_its_required_meaning(self):
        self.assertEqual(self.verdict({'requirements': ['PhD in Electrical Engineering']}),
                         ('phd_only', None, 0))

    def test_r5_required_qualifications_control(self):
        self.assertEqual(self.verdict({'required_qualifications': ['PhD in Electrical Engineering']}),
                         ('phd_only', None, 0))

    def test_r6_unrelated_preference_does_not_suppress_experience(self):
        self.assertEqual(self.verdict({'description': 'Python preferred.\n5 years of experience.'}),
                         ('required_experience_over_2_years', 5, 0))

    def test_r6_standalone_experience_control(self):
        self.assertEqual(self.verdict({'description': '5 years of experience.'}),
                         ('required_experience_over_2_years', 5, 0))

    def test_r7_inline_required_heading_ends_a_preferred_section(self):
        self.assertEqual(self.verdict({'description': 'Preferred qualifications:\nPython\nRequired: PhD in EE'}),
                         ('phd_only', None, 0))

    def test_r7_separate_required_heading_control(self):
        self.assertEqual(self.verdict({'description': 'Preferred qualifications:\nPython\nRequired:\nPhD in EE'}),
                         ('phd_only', None, 0))


if __name__ == '__main__':
    print('Source:', Path(jsearch.__file__).resolve(), flush=True)
    unittest.main(verbosity=2)
