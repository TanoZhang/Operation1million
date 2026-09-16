"""Local credentials and a conservative, persistent JSearch request guard."""
from contextlib import contextmanager
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
    """Count attempts before sending, including failures. No automatic reset.

    SQLite serializes reservations across processes. Keep this file across runs;
    resets require reconciliation against the provider's actual billing cycle.
    """
    def __init__(self, path=STATE, limit=10000, interval=0.25):
        self.attempts = 0
        self.path = Path(path)
        self.limit = min(limit, 10000)
        self.interval = max(interval, 0.25)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.path, timeout=30) as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY CHECK(id=1), used INTEGER NOT NULL, last_sent REAL NOT NULL)')
            db.execute('INSERT OR IGNORE INTO usage VALUES (1, 0, 0)')

    def get(self, session, url, **kwargs):
        # A separate lock database keeps reservations durable during network I/O.
        with connect(str(self.path) + '.lock', timeout=120) as lock:
            lock.execute('BEGIN IMMEDIATE')
            return self._get_locked(session, url, **kwargs)

    def used(self):
        with connect(self.path) as db:
            return db.execute('SELECT used FROM usage WHERE id=1').fetchone()[0]

    def _get_locked(self, session, url, **kwargs):
        with connect(self.path, timeout=120) as db:
            db.execute('BEGIN IMMEDIATE')
            used, last = db.execute('SELECT used, last_sent FROM usage WHERE id=1').fetchone()
            if used >= self.limit:
                raise QuotaExhausted('Local JSearch cap reached; reconcile the billing period before resetting')
            time.sleep(max(0, last + self.interval - time.time()))
            db.execute('UPDATE usage SET used=used+1, last_sent=? WHERE id=1', (time.time(),))
            db.commit()
            self.attempts += 1
        # Reservations remain counted even on network errors or process crashes.
        return session.get(url, allow_redirects=False, **kwargs)
