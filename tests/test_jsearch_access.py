"""Exercise quota persistence and network failure accounting without paid calls."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import requests
from jobdisco.jsearch_access import RequestGuard, QuotaExhausted


class GuardTests(unittest.TestCase):
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
