"""The monitor observes the pass and never changes it.

Nothing here touches the network. The transport is injected, and the shell
contract is exercised against the file that actually ships, with a stub
standing in for the pinger.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from jobdisco import heartbeat

ROOT = Path(__file__).resolve().parents[1]
SHELL_HELPER = ROOT / 'deploy/vps/heartbeat.sh'


class Opener:
    """Stands in for urlopen. Records every URL and never leaves the process."""

    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False

    def read(self):
        return b'OK'


class EndpointTests(unittest.TestCase):
    def test_each_event_maps_to_the_path_the_checker_reads(self):
        base = 'https://example.test/uuid'
        self.assertEqual(heartbeat.endpoint('start', base), base + '/start')
        self.assertEqual(heartbeat.endpoint('fail', base), base + '/fail')
        # A bare URL is what closes the check as successful.
        self.assertEqual(heartbeat.endpoint('success', base), base)

    def test_a_trailing_slash_does_not_become_a_double_slash(self):
        self.assertEqual(heartbeat.endpoint('start', 'https://example.test/uuid/'),
                         'https://example.test/uuid/start')

    def test_an_unknown_event_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            heartbeat.endpoint('finished', 'https://example.test/uuid')


class SilenceTests(unittest.TestCase):
    """A run with no configured URL is a dry run, a test, or a diagnostic."""

    def test_a_blank_or_absent_url_sends_nothing_at_all(self):
        for value in (None, '', '   '):
            with self.subTest(value=value):
                opener = Opener()
                environment = {} if value is None else {heartbeat.URL_VARIABLE: value}
                with mock.patch.dict(os.environ, environment, clear=True):
                    self.assertIsNone(heartbeat.ping('success', opener=opener))
                self.assertEqual(opener.calls, [])

    def test_silence_is_distinguishable_from_a_delivered_ping(self):
        opener = Opener()
        self.assertIs(heartbeat.ping('success', url='https://example.test/u', opener=opener), True)
        self.assertIsNone(heartbeat.ping('success', url='', opener=opener))


class DeliveryTests(unittest.TestCase):
    def test_the_url_comes_from_the_environment_not_from_source(self):
        opener = Opener()
        with mock.patch.dict(
                os.environ, {heartbeat.URL_VARIABLE: 'https://example.test/uuid'}, clear=True):
            heartbeat.ping('start', opener=opener)
        self.assertEqual(opener.calls[0][0], 'https://example.test/uuid/start')

    def test_no_ping_url_is_hardcoded_anywhere_in_the_tree(self):
        """Configuration lives on the box. A URL in source is a URL in every clone."""
        listed = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.split()
        for name in listed:
            path = ROOT / name
            if not path.is_file() or path.name == Path(__file__).name:
                continue
            try:
                body = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            self.assertNotIn('hc-ping.com', body, f'{name} hardcodes a heartbeat URL')

    def test_a_transport_failure_is_retried_then_reported_as_a_warning(self):
        opener = Opener(error=OSError('connection reset'))
        warnings = []
        result = heartbeat.ping('success', url='https://example.test/u', opener=opener,
                                sleep=lambda seconds: None, log=warnings.append)
        self.assertIs(result, False)
        self.assertEqual(len(opener.calls), heartbeat.ATTEMPTS)
        self.assertIn('not delivered', warnings[0])

    def test_a_ping_never_raises_whatever_the_transport_does(self):
        for error in (OSError('down'), ValueError('bad'), RuntimeError('odd')):
            with self.subTest(error=error):
                self.assertIs(heartbeat.ping('fail', url='https://example.test/u',
                                             opener=Opener(error=error),
                                             sleep=lambda seconds: None,
                                             log=lambda message: None), False)


class ExitCodeTests(unittest.TestCase):
    """A monitor that fails the run it monitors is worse than no monitor."""

    def test_the_cli_exits_zero_even_when_the_ping_could_not_be_sent(self):
        with mock.patch.object(heartbeat, 'ping', return_value=False):
            self.assertEqual(heartbeat.main(['success']), 0)

    def test_the_cli_exits_zero_on_a_bad_event_rather_than_failing_the_pass(self):
        self.assertEqual(heartbeat.main(['nonsense']), 0)
        self.assertEqual(heartbeat.main([]), 0)


@unittest.skipUnless(shutil.which('bash'), 'bash is required for the shell contract')
class ShellContractTests(unittest.TestCase):
    """Exercises deploy/vps/heartbeat.sh itself, with a stub for the pinger."""

    def run_pass(self, body, pinger_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            events = root / 'events'
            stub = root / 'pinger'
            # The helper calls: "$JOBDISCO_PYTHON" -m jobdisco.heartbeat <event>
            stub.write_text('#!/bin/sh\necho "$3" >> "$EVENTS"\nexit %d\n' % pinger_exit,
                            encoding='utf-8', newline='\n')
            stub.chmod(0o755)
            script = root / 'pass.sh'
            script.write_text(
                'set -euo pipefail\n'
                'JOBDISCO_PYTHON=%s\n'
                '. %s\n'
                'heartbeat_arm\n%s' % (stub.as_posix(), SHELL_HELPER.as_posix(), body),
                encoding='utf-8', newline='\n')
            completed = subprocess.run(['bash', script.as_posix()], capture_output=True,
                                       text=True, env={**os.environ, 'EVENTS': str(events)})
            sent = events.read_text(encoding='utf-8').split() if events.exists() else []
            return completed.returncode, sent

    def test_a_clean_pass_starts_then_reports_success(self):
        self.assertEqual(self.run_pass('echo done\n'), (0, ['start', 'success']))

    def test_a_failed_pass_reports_fail_and_keeps_its_exit_code(self):
        self.assertEqual(self.run_pass('exit 7\n'), (7, ['start', 'fail']))

    def test_a_failure_the_shell_takes_on_its_own_still_reports(self):
        """`set -e` exits without reaching any explicit exit; the trap must fire."""
        code, sent = self.run_pass('false\necho unreachable\n')
        self.assertEqual(sent, ['start', 'fail'])
        self.assertNotEqual(code, 0)

    def test_success_is_never_sent_for_a_pass_that_failed(self):
        self.assertNotIn('success', self.run_pass('exit 3\n')[1])

    def test_a_broken_pinger_cannot_turn_a_good_pass_into_a_failed_one(self):
        self.assertEqual(self.run_pass('echo done\n', pinger_exit=1), (0, ['start', 'success']))

    def test_a_broken_pinger_cannot_mask_a_real_failure_either(self):
        self.assertEqual(self.run_pass('exit 9\n', pinger_exit=1)[0], 9)


if __name__ == '__main__':
    unittest.main()
