"""A local ledger may be ahead of the published one. It may never be behind.

Behind means it has lost charges the provider has already counted, and the
whole point of the ledger is that it never undercounts.
"""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from jobdisco import jsearch, ledger_guard
from jobdisco.jsearch_access import RequestGuard


class BudgetDayAcrossTheCycleTests(unittest.TestCase):
    """B64: the budget day and the billing cycle turn over at different moments."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = jsearch.load_plan()[0]

    def guard(self, name):
        guard = RequestGuard(path=self.root / name, target_limit=self.settings['monthly_target'],
                             daily_limit=self.settings['daily_budget'],
                             cycle_start=self.settings['cycle_start'],
                             cycle_days=self.settings['cycle_days'],
                             day_zone=self.settings['budget_timezone'],
                             day_resets_at=self.settings['budget_day_resets_at'])
        guard.interval = 0
        return guard

    def test_a_ledger_that_lost_todays_spend_is_refused_after_the_cycle_rolls(self):
        """Zero against zero on the new cycle; sixty against zero today."""
        at = lambda stamp: patch('jobdisco.jsearch_access.time.time',
                                 return_value=datetime.fromisoformat(stamp).timestamp())
        published = self.guard('published.sqlite')
        session = Mock()
        session.get.return_value = Mock(status_code=200, headers={})
        with at('2026-10-15T23:59:59+00:00'):
            for _ in range(3):
                published.get(session, 'https://example.test', credits=20)
        self.guard('local.sqlite')
        with at('2026-10-16T00:00:01+00:00'):
            here, there, ok = ledger_guard.compare(self.root / 'local.sqlite',
                                                   self.root / 'published.sqlite', self.settings)
            self.assertEqual((here, there), (0, 0), 'both ledgers agree on the new cycle')
            self.assertFalse(ok, 'the local ledger has lost spend that still counts today')

    def test_a_ledger_ahead_on_both_clocks_still_passes(self):
        """The legitimate case: a pass whose push failed leaves the local copy ahead."""
        at = lambda stamp: patch('jobdisco.jsearch_access.time.time',
                                 return_value=datetime.fromisoformat(stamp).timestamp())
        session = Mock()
        session.get.return_value = Mock(status_code=200, headers={})
        local, published = self.guard('local.sqlite'), self.guard('published.sqlite')
        with at('2026-10-15T23:59:59+00:00'):
            local.get(session, 'https://example.test', credits=2)
            published.get(session, 'https://example.test', credits=1)
        with at('2026-10-16T00:00:01+00:00'):
            self.assertTrue(ledger_guard.compare(self.root / 'local.sqlite',
                                                 self.root / 'published.sqlite', self.settings)[2])


class LedgerGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = jsearch.load_plan()[0]

    def ledger(self, name, credits=0):
        """Build a ledger recording that many credits spent this period.

        `baseline` is how the ledger records credits the provider counted, so a
        ledger built this way is indistinguishable, to everything downstream,
        from one that spent them a page at a time.
        """
        path = self.root / name
        guard = RequestGuard(path=path, target_limit=self.settings['monthly_target'],
                             cycle_start=self.settings['cycle_start'],
                             cycle_days=self.settings['cycle_days'])
        if credits:
            guard.baseline(credits)
        return path

    def test_an_equal_ledger_is_the_ordinary_case(self):
        used_here, used_there, ok = ledger_guard.compare(
            self.ledger('a', 40), self.ledger('b', 40), self.settings)
        self.assertEqual((used_here, used_there), (40, 40))
        self.assertTrue(ok)

    def test_a_local_ledger_ahead_of_the_published_one_is_allowed(self):
        """A pass whose push failed leaves exactly this state."""
        _, _, ok = ledger_guard.compare(self.ledger('a', 55), self.ledger('b', 40), self.settings)
        self.assertTrue(ok)

    def test_a_local_ledger_behind_the_published_one_is_refused(self):
        used_here, used_there, ok = ledger_guard.compare(
            self.ledger('a', 10), self.ledger('b', 40), self.settings)
        self.assertEqual((used_here, used_there), (10, 40))
        self.assertFalse(ok)

    def test_a_schema_only_ledger_is_refused_though_it_is_a_valid_file(self):
        """The failure this exists for: not missing, not empty, just forgetful.

        A diagnostic that opened the path, an interrupted run, a restore from
        the wrong place -- each leaves several kilobytes of valid SQLite that
        `[ -s ]` accepts and that knows nothing about what was spent.
        """
        empty = self.ledger('fresh', 0)
        self.assertGreater(empty.stat().st_size, 0, 'the file is not empty, which is the point')
        _, _, ok = ledger_guard.compare(empty, self.ledger('published', 351), self.settings)
        self.assertFalse(ok)

    def test_the_cli_fails_loudly_and_names_the_repair(self):
        local, published = self.ledger('a', 1), self.ledger('b', 40)
        self.assertEqual(ledger_guard.main([str(local), str(published)]), 1)
        self.assertEqual(ledger_guard.main([str(published), str(local)]), 0)

    def test_a_check_never_creates_the_ledger_it_is_asking_about(self):
        """Opening a ledger creates it, which is right for a pass and wrong here.

        A published ledger conjured out of nothing reads as zero credits spent,
        compares at or below whatever the local one says, and reports that all
        is well -- the guard manufacturing exactly the silence it exists to
        break.
        """
        missing = self.root / 'absent.sqlite'
        with self.assertRaises(FileNotFoundError):
            ledger_guard.credits_recorded(missing, self.settings)
        self.assertFalse(missing.exists(), 'a read-only check wrote to disk')

    def test_a_missing_ledger_is_refused_rather_than_invented(self):
        missing = self.root / 'absent.sqlite'
        published = self.ledger('published', 351)
        self.assertEqual(ledger_guard.main([str(missing), str(published)]), 1)
        self.assertFalse(missing.exists())
        self.assertEqual(ledger_guard.main([str(published), str(missing)]), 1)
        self.assertFalse(missing.exists())

    def test_the_cli_refuses_the_wrong_number_of_arguments(self):
        self.assertEqual(ledger_guard.main([]), 64)
        self.assertEqual(ledger_guard.main(['only-one']), 64)


if __name__ == '__main__':
    unittest.main()
