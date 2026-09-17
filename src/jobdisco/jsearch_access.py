"""Local credentials and a conservative, persistent JSearch request guard."""
from contextlib import contextmanager
from datetime import datetime, timezone
import calendar
import sqlite3
import time
from pathlib import Path
from .local_config import load_credentials
from .paths import ROOT
STATE = ROOT / '.local/jsearch_usage.sqlite'


@contextmanager
def connect(path, timeout=30):
    db = sqlite3.connect(path, timeout=timeout)
    try:
        with db:
            yield db
    finally:
        db.close()


class QuotaExhausted(Exception):
    pass


class RequestGuard:
    """Reserve page credits before sending, including failures.

    SQLite serializes reservations across processes. Keep this file across runs;
    Period records are retained. Configure the actual provider billing anchor;
    calls made outside this ledger require separate reconciliation.
    """
    def __init__(self, path=STATE, limit=10000, interval=0.25, daily_limit=None,
                 target_limit=None, billing_day=1):
        self.attempts = 0
        self.credits = 0
        self.path = Path(path)
        self.limit = min(limit, 10000)
        self.interval = max(interval, 0.25)
        self.daily_limit = daily_limit
        self.target_limit = min(target_limit or self.limit, self.limit)
        self.billing_day = billing_day
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.path, timeout=30) as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY CHECK(id=1), used INTEGER NOT NULL, last_sent REAL NOT NULL)')
            db.execute('INSERT OR IGNORE INTO usage VALUES (1, 0, 0)')
            db.execute('CREATE TABLE IF NOT EXISTS credit_usage (period TEXT, day TEXT, used INTEGER NOT NULL, PRIMARY KEY(period, day))')
            db.execute('CREATE TABLE IF NOT EXISTS account_pause (id INTEGER PRIMARY KEY, retry_at REAL NOT NULL)')
            # Existing one-page reservations have no date. Charge them to the
            # first known billing period rather than silently erasing usage.
            if not db.execute('SELECT 1 FROM credit_usage LIMIT 1').fetchone():
                period, day = self.period()
                old = db.execute('SELECT used FROM usage WHERE id=1').fetchone()[0]
                db.execute('INSERT INTO credit_usage VALUES (?, ?, ?)', (period, day, old))

    def period(self):
        today = datetime.fromtimestamp(time.time(), timezone.utc).date()
        year, month = today.year, today.month
        anchor = today.replace(day=min(self.billing_day, calendar.monthrange(year, month)[1]))
        if today < anchor:
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
            anchor = today.replace(year=year, month=month,
                                   day=min(self.billing_day, calendar.monthrange(year, month)[1]))
        return anchor.isoformat(), today.isoformat()

    def pause(self, seconds):
        with connect(self.path) as db:
            db.execute('INSERT INTO account_pause VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET retry_at=MAX(retry_at, excluded.retry_at)',
                       (time.time() + seconds,))

    def get(self, session, url, credits=1, **kwargs):
        if type(credits) is not int or not 1 <= credits <= 20:
            raise ValueError('A JSearch dispatch must reserve 1..20 page credits')
        # A separate lock database keeps reservations durable during network I/O.
        with connect(str(self.path) + '.lock', timeout=120) as lock:
            lock.execute('BEGIN IMMEDIATE')
            return self._get_locked(session, url, credits=credits, **kwargs)

    def used(self):
        with connect(self.path) as db:
            return db.execute('SELECT used FROM usage WHERE id=1').fetchone()[0]

    def _get_locked(self, session, url, credits=1, **kwargs):
        with connect(self.path, timeout=120) as db:
            db.execute('BEGIN IMMEDIATE')
            used, last = db.execute('SELECT used, last_sent FROM usage WHERE id=1').fetchone()
            period, day = self.period()
            monthly = db.execute('SELECT COALESCE(SUM(used), 0) FROM credit_usage WHERE period=?', (period,)).fetchone()[0]
            daily = db.execute('SELECT COALESCE(SUM(used), 0) FROM credit_usage WHERE day=?', (day,)).fetchone()[0]
            if monthly + credits > self.target_limit or (self.daily_limit is not None and daily + credits > self.daily_limit):
                raise QuotaExhausted('JSearch page-credit budget reached; no request sent')
            pause = db.execute('SELECT retry_at FROM account_pause WHERE id=1').fetchone()
            if pause and pause[0] > time.time():
                raise QuotaExhausted('JSearch account cooldown is active; no request sent')
            time.sleep(max(0, last + self.interval - time.time()))
            db.execute('UPDATE usage SET used=used+?, last_sent=? WHERE id=1', (credits, time.time()))
            db.execute('INSERT INTO credit_usage VALUES (?, ?, ?) ON CONFLICT(period, day) DO UPDATE SET used=used+excluded.used', (period, day, credits))
            db.commit()
            self.attempts += 1
            self.credits += credits
        # Reservations remain counted even on network errors or process crashes.
        return session.get(url, allow_redirects=False, **kwargs)
