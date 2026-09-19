"""Dead-man's switch for the production pass.

Nothing on the VPS will otherwise say it died: a timer that stops, a disk that
fills and a process the kernel kills are all silent. An external check is the
only thing that notices absence, so the pass reports start, success and failure
to it -- and a pass that never runs reports nothing at all, which is exactly
what the check is watching for.

This module never raises and never changes an exit code. A monitor that could
fail the run it monitors would be worse than no monitor: it would turn a good
collection into a red one and train the operator to ignore the alarm.
"""
import os
import sys
import time
import urllib.error
import urllib.request

URL_VARIABLE = 'HEALTHCHECK_URL'

# Healthchecks.io reads the event from the path: a bare URL closes the check as
# successful, /start opens a run, /fail marks it down immediately.
EVENTS = {'start': '/start', 'success': '', 'fail': '/fail'}

TIMEOUT = 10
ATTEMPTS = 3


def endpoint(event, url):
    """Return the URL for an event, or None when this is not a production run.

    The URL is configuration, never source. An unset or blank variable means a
    dry run, a test, or a manual diagnostic, and those must stay silent: a
    heartbeat they sent would tell the check that a production pass had
    succeeded when none had run.
    """
    if event not in EVENTS:
        raise ValueError(f'Unknown heartbeat event: {event}')
    url = (url if url is not None else os.environ.get(URL_VARIABLE, '')).strip()
    if not url:
        return None
    return url.rstrip('/') + EVENTS[event]


def ping(event, url=None, attempts=ATTEMPTS, timeout=TIMEOUT, opener=None,
         sleep=time.sleep, log=None):
    """Report an event. Returns True if sent, False if it could not be, None if silent.

    False is a warning and never an error: the collection it describes has
    already happened, and the ledger and the log are what actually record it.
    """
    log = log if log is not None else (lambda message: print(message, file=sys.stderr))
    try:
        target = endpoint(event, url)
    except ValueError as exc:
        log(f'warning: {exc}')
        return False
    if target is None:
        return None
    opener = opener or urllib.request.urlopen
    for attempt in range(1, attempts + 1):
        try:
            with opener(target, timeout=timeout) as response:
                # The service can return HTTP 200 with "OK (not found)".
                # Only the exact acknowledgement means the check accepted it.
                if response.read().strip() != b'OK':
                    raise ValueError('Heartbeat endpoint did not acknowledge the event')
            return True
        except Exception as exc:  # noqa: BLE001 - a monitor may not raise
            if attempt == attempts:
                log(f'warning: heartbeat {event!r} not delivered after '
                    f'{attempts} attempts: {exc}')
                return False
            sleep(min(2 ** attempt, 8))
    return False


def main(argv=None):
    """Always exit 0. The caller owns its own exit code and keeps it."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in EVENTS:
        print(f'usage: python -m jobdisco.heartbeat {{{"|".join(EVENTS)}}}', file=sys.stderr)
        return 0
    ping(argv[0])
    return 0


if __name__ == '__main__':
    sys.exit(main())
