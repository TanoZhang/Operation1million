"""Conservative request pacing and durable pauses for direct company sources."""
from contextlib import closing
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from pathlib import Path
import sqlite3
import time

from .paths import ROOT

STATE = ROOT / '.local' / 'source_access.sqlite'


class SourcePaused(Exception):
    """Stop this source for the run; a later run must honor its cooldown."""


def request_interval(source, requested):
    minimum = 3.0 if source.company_key == 'microsoft' else (
        2.5 if source.provider_key == 'eightfold' else 1.0
    )
    return max(minimum, requested)


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
        self.interval = request_interval(source, requested_delay)
        self.path = Path(path)
        self.stopped = None

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
