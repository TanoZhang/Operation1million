"""Synthetic offline regressions for the review audit of b2c9340.

Run: python docs/review-audit-repro-2026-09-23.py
The three regression tests intentionally fail on the audited commit.
All database, log and ledger paths belong to temporary directories.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))

from jobdisco import applications, degree, jsearch, store
import test_review_description as fixtures

row = fixtures.row


class RefreshAudit(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DescriptionTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.rules = jsearch.load_plan()[0]['filter']

    def persist(self, raw):
        job = row('audit', 'https://example.test/audit', raw=raw)
        self.fixture.persist([job])
        return job

    def stored_raw(self):
        return json.loads(self.fixture.db.execute('SELECT raw FROM jobs').fetchone()[0])

    def pending_count(self):
        return len(applications.queue(self.fixture.path, self.fixture.ledger)['pending'])

    def test_empty_html_refresh_preserves_the_only_readable_description(self):
        teaser = 'RTL design role requiring 5 years of experience.'
        self.persist({'descriptionTeaser': teaser})
        self.assertEqual(self.pending_count(), 0)
        self.persist({'description': '<p></p>'})
        raw = self.stored_raw()
        with self.fixture.server() as get:
            detail = get(url='https://example.test/audit')
        actual = (raw.get('descriptionTeaser'), detail['description'], self.pending_count())
        self.assertEqual(actual, (teaser, teaser, 0))

    def test_null_teaser_does_not_keep_an_obsolete_requirement(self):
        old = 'RTL design role requiring 5 years of experience.'
        new = 'RTL design role requiring 1 year of experience.'
        self.persist({'descriptionTeaser': old})
        self.persist({'description': new, 'descriptionTeaser': None})
        raw = self.stored_raw()
        with self.fixture.server() as get:
            detail = get(url='https://example.test/audit')
        reason = jsearch.rejection_reason(row('audit', 'https://example.test/audit', raw=raw), self.rules)
        actual = (reason, old in detail['description'], self.pending_count())
        self.assertEqual(actual, ('', False, 1))

    def test_conditional_phd_instruction_does_not_exclude_other_applicants(self):
        description = ('Build RTL blocks. If you are pursuing a PhD, you must '
                       'return to your degree program after the internship.')
        self.persist({'description': description})
        raw = self.stored_raw()
        text = jsearch.description_text({'raw': raw}, structured=True)
        reason, _ = jsearch.eligibility_rejection(
            row('audit', 'https://example.test/audit', raw=raw), self.rules)
        self.assertEqual((degree.phd_only('RTL Design Engineer', text), reason, self.pending_count()),
                         (False, '', 1))

    def test_omitted_teaser_control_uses_the_new_requirement(self):
        self.persist({'descriptionTeaser': 'RTL role requiring 5 years of experience.'})
        self.persist({'description': 'RTL role requiring 1 year of experience.'})
        self.assertEqual(self.pending_count(), 1)

    def test_supplied_teaser_control_survives_empty_html(self):
        teaser = 'RTL role requiring 5 years of experience.'
        self.persist({'description': '<p></p>', 'descriptionTeaser': teaser})
        self.assertEqual(self.stored_raw()['descriptionTeaser'], teaser)
        self.assertEqual(self.pending_count(), 0)

    def test_unconditional_phd_requirement_control_is_excluded(self):
        self.persist({'description': 'Candidates must be pursuing a PhD in EE.'})
        self.assertEqual(self.pending_count(), 0)


if __name__ == '__main__':
    print('Source:', Path(store.__file__).resolve(), flush=True)
    unittest.main(verbosity=2)
