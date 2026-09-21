"""Conservative request pacing and durable pauses for direct company sources."""
from contextlib import closing
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit

import requests

from .paths import ROOT

STATE = ROOT / '.local' / 'source_access.sqlite'


class SourcePaused(Exception):
    """Stop this source for the run; a later run must honor its cooldown."""


_ROBOTS_DELAY: dict[str, float | None] = {}


def robots_delay(url, timeout=15):
    """Crawl-delay the host declares for us, cached per host.

    Read directly rather than through urllib.robotparser: that parser applies
    rules in file order instead of longest-match, so a site that says
    "Disallow: / " and then "Allow: /api/pcsx" reads as a blanket refusal when
    it is in fact granting the path. Crawl-delay is what we need here, and an
    unreachable robots.txt simply leaves the configured minimum in place.
    """
    host = urlsplit(url).netloc
    if host in _ROBOTS_DELAY:
        return _ROBOTS_DELAY[host]
    delay = None
    try:
        r = requests.get(f'https://{host}/robots.txt', timeout=timeout,
                         headers={'User-Agent': 'JobSourceCollector/1.0'})
        if r.status_code == 200:
            for value in re.findall(r'(?im)^\s*crawl-delay:\s*(\S+)', r.text):
                try:
                    delay = max(delay or 0.0, float(value))
                except ValueError:
                    continue
    except requests.RequestException:
        delay = None
    _ROBOTS_DELAY[host] = delay
    return delay


def request_interval(source, requested):
    minimum = 3.0 if source.company_key == 'microsoft' else (
        2.5 if source.provider_key == 'eightfold' else 1.0
    )
    # A declared Crawl-delay is the host's own stated limit; never go below it.
    return max(minimum, requested, robots_delay(source.access_url) or 0.0)


def retry_after_seconds(value, now=None):
    """Accept both Retry-After formats without shortening server wait times."""
    if value is None:
        return None
    now = time.time() if now is None else now
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            seconds = stamp.timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, math.ceil(seconds)) if math.isfinite(seconds) else None


class SourcePolicy:
    def __init__(self, source, requested_delay, path=STATE):
        self.company_key = source.company_key
        self.source, self.requested_delay = source, requested_delay
        self._interval = None
        self.path = Path(path)
        self.stopped = None

    @property
    def interval(self):
        """The pace for this source, resolved on first use rather than here.

        Resolving it asks the host for its robots.txt. Constructing a policy
        therefore sent a request to a source that might be inside an active
        cooldown -- from the object whose whole purpose is to keep us off it,
        and before `check()` had a chance to say so. Every caller reads this
        only after `check()` has passed, so the robots request now goes out
        only where a collection request was going out anyway.
        """
        if self._interval is None:
            self._interval = request_interval(self.source, self.requested_delay)
        return self._interval

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=30)
        con.execute('''CREATE TABLE IF NOT EXISTS source_pauses (
            company_key TEXT PRIMARY KEY,
            retry_at REAL NOT NULL,
            reason TEXT NOT NULL
        )''')
        return con

    def check(self):
        if self.stopped:
            raise SourcePaused(self.stopped)
        with closing(self.connect()) as con:
            row = con.execute('SELECT retry_at, reason FROM source_pauses WHERE company_key=?',
                              (self.company_key,)).fetchone()
        if row and row[0] > time.time():
            stamp = datetime.fromtimestamp(row[0], timezone.utc).isoformat()
            self.stopped = f'{self.company_key}: {row[1]}; retry no earlier than {stamp}'
            raise SourcePaused(self.stopped)

    def pause(self, reason, seconds):
        retry_at = time.time() + seconds
        with closing(self.connect()) as con, con:
            con.execute('''INSERT INTO source_pauses VALUES (?, ?, ?)
                ON CONFLICT(company_key) DO UPDATE SET
                    retry_at=MAX(source_pauses.retry_at, excluded.retry_at),
                    reason=excluded.reason''', (self.company_key, retry_at, reason))
            retry_at = con.execute('SELECT retry_at FROM source_pauses WHERE company_key=?',
                                   (self.company_key,)).fetchone()[0]
        stamp = datetime.fromtimestamp(retry_at, timezone.utc).isoformat()
        self.stopped = f'{self.company_key}: {reason}; retry no earlier than {stamp}'
        raise SourcePaused(self.stopped)
