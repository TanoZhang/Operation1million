"""Exercise quota persistence and network failure accounting without paid calls."""
import tempfile
import unittest
import sqlite3
from contextlib import closing
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from jobdisco.jsearch_access import RequestGuard, QuotaExhausted


class GuardTests(unittest.TestCase):
    def test_existing_utc_history_is_split_at_pacific_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'usage.sqlite'
            guard = RequestGuard(path, daily_limit=320)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DELETE FROM credit_usage')
                db.execute("INSERT INTO credit_usage VALUES ('2026-09-16', '2026-09-19', 320)")
                for at, credits in [('2026-09-19T01:05:00+00:00', 296),
                                    ('2026-09-19T11:55:00+00:00', 24)]:
                    db.execute('INSERT INTO credit_events(at, period, day, credits) VALUES (?, ?, ?, ?)',
                               (datetime.fromisoformat(at).timestamp(), '2026-09-16', '2026-09-19', credits))
            with patch('jobdisco.jsearch_access.time.time', return_value=datetime.fromisoformat(
                    '2026-09-19T12:00:00+00:00').timestamp()):
                restarted = RequestGuard(path, daily_limit=320)
                balance = restarted.balance()
                self.assertEqual(balance['day_used'], 24)
                self.assertEqual(balance['day_remaining'], 296)
                self.assertEqual(balance['period_used'], 320)

    def test_untimestamped_residual_belongs_to_its_recorded_budget_day(self):
        """A residual must not reduce two consecutive scheduled passes.

        Older aggregate rows lack the instant of each credit, but their `day`
        column is the budget-day key that was active when they were recorded.
        Matching it against the UTC dates overlapped by a Pacific window makes
        the same row appear in both adjacent windows.
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'usage.sqlite'
            guard = RequestGuard(path, daily_limit=320)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DELETE FROM credit_usage')
                db.execute('DELETE FROM credit_events')
                db.execute("INSERT INTO credit_usage VALUES ('2026-09-16', '2026-09-20', 4)")
            balances = []
            for stamp in ('2026-09-19T12:00:00+00:00', '2026-09-20T12:00:00+00:00'):
                with patch('jobdisco.jsearch_access.time.time',
                           return_value=datetime.fromisoformat(stamp).timestamp()):
                    balances.append(guard.balance()['day_used'])
            self.assertEqual(balances, [0, 4])

    def test_reset_boundary_and_daylight_saving(self):
        with tempfile.TemporaryDirectory() as folder:
            guard = RequestGuard(Path(folder) / 'usage.sqlite')
            for stamp, expected in [
                    ('2026-09-19T11:37:59+00:00', '2026-09-18'),
                    ('2026-09-19T11:38:00+00:00', '2026-09-19'),
                    ('2026-12-19T12:37:59+00:00', '2026-12-18'),
                    ('2026-12-19T12:38:00+00:00', '2026-12-19')]:
                with self.subTest(stamp=stamp), patch('jobdisco.jsearch_access.time.time',
                        return_value=datetime.fromisoformat(stamp).timestamp()):
                    self.assertEqual(guard.daily_window()[0], expected)
            for stamp, hours in [('2026-03-08T10:00:00+00:00', 23),
                                  ('2026-11-01T10:00:00+00:00', 25)]:
                with patch('jobdisco.jsearch_access.time.time',
                           return_value=datetime.fromisoformat(stamp).timestamp()):
                    _, start, end = guard.daily_window()
                    self.assertEqual(end - start, hours * 3600)

    def test_daily_limit_reopens_at_reset_without_refunding_month(self):
        with tempfile.TemporaryDirectory() as folder:
            guard = RequestGuard(Path(folder) / 'usage.sqlite', daily_limit=1)
            guard.interval = 0
            session = Mock()
            session.get.return_value = Mock(status_code=200, headers={})
            with patch('jobdisco.jsearch_access.time.time', return_value=datetime.fromisoformat(
                    '2026-09-19T11:37:59+00:00').timestamp()):
                guard.get(session, 'https://example.com')
                with self.assertRaises(QuotaExhausted):
                    guard.get(session, 'https://example.com')
            with patch('jobdisco.jsearch_access.time.time', return_value=datetime.fromisoformat(
                    '2026-09-19T11:38:00+00:00').timestamp()):
                guard.get(session, 'https://example.com')
                self.assertEqual(guard.balance()['day_used'], 1)
                self.assertEqual(guard.balance()['period_used'], 2)

    def test_legacy_aggregate_without_events_is_not_erased(self):
        with tempfile.TemporaryDirectory() as folder:
            guard = RequestGuard(Path(folder) / 'usage.sqlite', daily_limit=320)
            with closing(sqlite3.connect(guard.path)) as db, db:
                db.execute('DELETE FROM credit_usage')
                db.execute("INSERT INTO credit_usage VALUES ('2026-09-16', '2026-09-19', 320)")
            with patch('jobdisco.jsearch_access.time.time', return_value=datetime.fromisoformat(
                    '2026-09-19T12:00:00+00:00').timestamp()):
                self.assertEqual(guard.balance()['day_remaining'], 0)
                with self.assertRaises(QuotaExhausted):
                    guard.get(Mock(), 'https://example.com')

    def test_restart_cap_and_failed_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'usage.sqlite'
            session = Mock()
            session.get.side_effect = requests.Timeout()
            with self.assertRaises(requests.Timeout):
                RequestGuard(path, limit=1).get(session, 'https://example.com')
            guard = RequestGuard(path, limit=1)
            self.assertEqual(guard.used(), 1)
            with self.assertRaises(QuotaExhausted):
                guard.get(session, 'https://example.com')
            self.assertEqual(session.get.call_count, 1)

    def test_concurrent_last_request_is_reserved_once(self):
        with tempfile.TemporaryDirectory() as folder:
            guard = RequestGuard(Path(folder) / 'usage.sqlite', limit=1)
            session = Mock()
            def call(_):
                try:
                    guard.get(session, 'https://example.com')
                    return True
                except QuotaExhausted:
                    return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(call, range(4))), 1)
            self.assertEqual(guard.used(), 1)
            session.get.assert_called_once_with('https://example.com', allow_redirects=False)


if __name__ == '__main__':
    unittest.main()
