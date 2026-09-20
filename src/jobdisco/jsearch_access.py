"""Local credentials and a conservative, persistent JSearch request guard."""
from contextlib import contextmanager
from datetime import date, datetime, time as clock, timedelta, timezone
import re
import sqlite3
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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


class AccountPaused(QuotaExhausted):
    """A provider refusal is a failure, not ordinary budget completion."""


class RequestGuard:
    """Reserve page credits before sending, including failures.

    SQLite serializes reservations across processes. Keep this file across runs;
    Period records are retained. Configure the actual provider billing anchor;
    calls made outside this ledger require separate reconciliation.
    """
    def __init__(self, path=STATE, limit=10000, interval=0.25, daily_limit=None,
                 target_limit=None, cycle_start='2026-09-16', cycle_days=30,
                 ignore_daily_limit=False, run_limit=None,
                 day_zone='America/Los_Angeles', day_resets_at='04:38'):
        self.attempts = 0
        self.credits = 0
        self.path = Path(path)
        self.limit = min(limit, 10000)
        self.interval = max(interval, 0.25)
        self.daily_limit = daily_limit
        self.target_limit = min(target_limit or self.limit, self.limit)
        # The plan renews every cycle_days, not on a day of the month: a
        # calendar anchor would drift by a day or three every month a period
        # crosses February or a 31-day month.
        self.cycle_start = date.fromisoformat(str(cycle_start))
        self.cycle_days = max(1, int(cycle_days))
        # A budget day begins when the scheduled pass does, not at a midnight
        # that belongs to nobody. The daily slice exists to give that pass its
        # allowance, so the two have to mean the same thing by "today".
        try:
            self.day_zone = ZoneInfo(str(day_zone))
        except ZoneInfoNotFoundError:
            # Never quietly fall back to UTC here. UTC is precisely the wrong
            # answer -- it is the boundary this exists to stop using -- and a
            # silent one would look like working software while spending the
            # scheduled pass's budget the evening before.
            raise ValueError(
                f'No time zone data for {day_zone!r}; install tzdata '
                '(it is a declared dependency) or set a zone this host knows') from None
        hour, _, minute = str(day_resets_at).partition(':')
        if not hour.isdigit() or (minute and not minute.isdigit()):
            raise ValueError('Budget day reset must be written as HH:MM')
        self.day_resets_at = clock(int(hour), int(minute or 0))
        # A backfill exists to spend credits that expire with the cycle, so the
        # daily slice -- which is only a way of pacing the month -- must not
        # stop it. The monthly target still binds, and always does.
        self.ignore_daily_limit = ignore_daily_limit
        # What this one run may spend. The durable limits pace a day and a
        # cycle; they cannot express "a third of what is left", which is what
        # keeps an early sweep from taking the remainder a later day may need.
        # Depth is discovered while paging, so nothing else bounds a run.
        self.run_limit = run_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.path, timeout=30) as db:
            db.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY CHECK(id=1), used INTEGER NOT NULL, last_sent REAL NOT NULL)')
            db.execute('INSERT OR IGNORE INTO usage VALUES (1, 0, 0)')
            db.execute('CREATE TABLE IF NOT EXISTS credit_usage (period TEXT, day TEXT, used INTEGER NOT NULL, PRIMARY KEY(period, day))')
            db.execute('CREATE TABLE IF NOT EXISTS account_pause (id INTEGER PRIMARY KEY, retry_at REAL NOT NULL)')
            # One row per dispatched page. The reservation is written before the
            # request leaves, so a crash or a timeout still shows the credit as
            # spent; the outcome is filled in afterwards. Without it the ledger
            # cannot tell a credit that returned jobs from one a 504 consumed.
            db.execute('''CREATE TABLE IF NOT EXISTS credit_events (
                              id INTEGER PRIMARY KEY, at REAL NOT NULL, period TEXT NOT NULL,
                              day TEXT NOT NULL, credits INTEGER NOT NULL,
                              outcome TEXT NOT NULL DEFAULT 'reserved',
                              provider_charged INTEGER)''')
            columns = {r[1] for r in db.execute('PRAGMA table_info(credit_events)')}
            if 'provider_charged' not in columns:
                db.execute('ALTER TABLE credit_events RENAME COLUMN provider_remaining TO provider_charged')
            # Credits spent outside this ledger -- a console test, a lost run, a
            # ledger rebuilt from scratch -- are real against the provider's
            # count and must not read as available here.
            db.execute('CREATE TABLE IF NOT EXISTS credit_baseline (period TEXT PRIMARY KEY, used INTEGER NOT NULL)')
            # Where each query had reached when the last backfill pass stopped.
            # A month-wide sweep is too long for one Actions job, so it runs over
            # the cycle's final days; without this each day would start at page
            # one and re-buy pages it already holds. Keyed by period, because a
            # new billing cycle is a new sweep.
            db.execute('''CREATE TABLE IF NOT EXISTS backfill_cursor (
                              period TEXT NOT NULL, query_key TEXT NOT NULL,
                              page INTEGER NOT NULL, exhausted INTEGER NOT NULL DEFAULT 0,
                              updated_at REAL NOT NULL, PRIMARY KEY(period, query_key))''')
            # Existing one-page reservations have no date. Charge them to the
            # first known billing period rather than silently erasing usage.
            if not db.execute('SELECT 1 FROM credit_usage LIMIT 1').fetchone():
                period, day = self.period()
                old = db.execute('SELECT used FROM usage WHERE id=1').fetchone()[0]
                db.execute('INSERT INTO credit_usage VALUES (?, ?, ?)', (period, day, old))

    def _cycle(self):
        """The cycle's first day and the UTC date, which is what dates it.

        The cycle stands in for the provider's own monthly quota, so it counts
        plain UTC days from a fixed anchor and never moves with daylight
        saving. That is load-bearing: 04:38 Pacific is eleven hours clear of a
        UTC date change in either offset, which is what keeps a pass from
        landing on a different cycle day twice a year.
        """
        today = datetime.fromtimestamp(time.time(), timezone.utc).date()
        elapsed = (today - self.cycle_start).days
        cycles = elapsed // self.cycle_days if elapsed >= 0 else -((-elapsed + self.cycle_days - 1) // self.cycle_days)
        return self.cycle_start + timedelta(days=cycles * self.cycle_days), today

    def budget_day(self):
        """Which day's page-credit allowance is being spent right now.

        A budget day runs from one scheduled pass to the next, in the timezone
        the schedule is written in. It is not a UTC day and not a local
        midnight: the daily slice exists to fund the scheduled pass, so it has
        to begin when that pass does.

        Under UTC the day turned over at 17:00 Pacific, eleven hours before the
        pass it was meant to fund, so anything run on a Pacific evening spent
        the next morning's credits. Measured once, on 2026-09-19: a catch-up
        run at 18:05 and 20:10 Pacific took 296 of 320, and the scheduled pass
        eleven hours later got 24 and reached fifteen of its fifty-two queries.

        One implementation, in `daily_window`: the key written into the ledger
        and the range the spend is counted over have to name the same day, and
        two functions computing it separately is how they stop doing so.
        """
        return date.fromisoformat(self.daily_window()[0])

    def period(self):
        """The cycle's first day, and the budget day, both as ISO dates.

        The two are anchored differently on purpose; see `_cycle` and
        `budget_day` for why each is the clock it is.
        """
        return self._cycle()[0].isoformat(), self.budget_day().isoformat()

    def days_until_reset(self):
        """Days left in this cycle, counting today. 1 means today is the last."""
        start, today = self._cycle()
        return self.cycle_days - (today - start).days

    def daily_window(self):
        """The budget day as an instant range, from one scheduled pass to the next.

        Driven by the configured zone and reset time rather than a literal
        04:38 Pacific, so this and `budget_day` cannot answer differently, and
        so a schedule change moves both. A test reads the systemd timer to hold
        the configuration to the same hour the pass actually runs.
        """
        local = datetime.fromtimestamp(time.time(), self.day_zone)
        start = local.replace(hour=self.day_resets_at.hour,
                              minute=self.day_resets_at.minute,
                              second=0, microsecond=0)
        if local < start:
            start -= timedelta(days=1)
        end = start + timedelta(days=1)
        return start.date().isoformat(), start.timestamp(), end.timestamp()

    def daily_used(self, db):
        """Recount timestamped history without rewriting the UTC audit ledger.

        Older aggregate-only credits cannot be assigned an exact time. Their
        stored day is still the budget-day key that was active when they were
        recorded, so charge each residual to that one day.
        """
        day, start, end = self.daily_window()
        used = db.execute('SELECT COALESCE(SUM(credits), 0) FROM credit_events '
                          'WHERE at>=? AND at<?', (start, end)).fetchone()[0]
        residual = db.execute('''SELECT COALESCE(SUM(MAX(0, u.used - COALESCE(e.used, 0))), 0)
            FROM credit_usage u LEFT JOIN (
                SELECT period, day, SUM(credits) AS used FROM credit_events GROUP BY period, day
            ) e USING(period, day) WHERE u.day=?''', (day,)).fetchone()[0]
        return day, used + residual

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

    def baseline(self, used, period=None):
        """Record credits the provider counted that this ledger never saw."""
        period = period or self.period()[0]
        with connect(self.path) as db:
            db.execute('INSERT INTO credit_baseline VALUES (?, ?) '
                       'ON CONFLICT(period) DO UPDATE SET used=excluded.used', (period, used))
        return period, used

    def resume_page(self, query_key, period=None):
        """The page a backfill should ask for next, and whether it is finished."""
        period = period or self.period()[0]
        with connect(self.path) as db:
            row = db.execute('SELECT page, exhausted FROM backfill_cursor WHERE period=? AND query_key=?',
                             (period, query_key)).fetchone()
        return (row[0], bool(row[1])) if row else (1, False)

    def advance(self, query_key, page, exhausted=False, period=None):
        period = period or self.period()[0]
        with connect(self.path, timeout=120) as db:
            db.execute('INSERT INTO backfill_cursor VALUES (?, ?, ?, ?, ?) '
                       'ON CONFLICT(period, query_key) DO UPDATE SET '
                       'page=excluded.page, exhausted=excluded.exhausted, updated_at=excluded.updated_at',
                       (period, query_key, page, int(exhausted), time.time()))

    def balance(self):
        """What is spent and what is left, right now, from durable state."""
        period, day = self.period()
        with connect(self.path) as db:
            one = lambda sql, *args: db.execute(sql, args).fetchone()[0]
            used = (one('SELECT COALESCE(SUM(used), 0) FROM credit_usage WHERE period=?', period)
                    + one('SELECT COALESCE(SUM(used), 0) FROM credit_baseline WHERE period=?', period))
            day, today = self.daily_used(db)
            wasted = one("""SELECT COALESCE(SUM(credits), 0) FROM credit_events
                            WHERE period=? AND outcome NOT LIKE 'http:2%'""", period)
            charged = one("""SELECT COALESCE(SUM(provider_charged), 0) FROM credit_events
                             WHERE period=? AND provider_charged IS NOT NULL""", period)
            reserved = one("""SELECT COALESCE(SUM(credits), 0) FROM credit_events
                              WHERE period=? AND provider_charged IS NOT NULL""", period)
        return {'period': period, 'day': day, 'period_used': used,
                'period_remaining': max(0, self.target_limit - used),
                'day_used': today,
                'day_remaining': max(0, self.daily_limit - today) if self.daily_limit is not None else None,
                'period_unproductive': wasted,
                # Nonzero means the provider charged something other than what
                # this ledger reserved, which nothing else would reveal.
                'provider_drift': charged - reserved}

    def _get_locked(self, session, url, credits=1, **kwargs):
        with connect(self.path, timeout=120) as db:
            db.execute('BEGIN IMMEDIATE')
            used, last = db.execute('SELECT used, last_sent FROM usage WHERE id=1').fetchone()
            time.sleep(max(0, last + self.interval - time.time()))
            period, day = self.period()
            monthly = db.execute('SELECT COALESCE(SUM(used), 0) FROM credit_usage WHERE period=?', (period,)).fetchone()[0]
            _, daily = self.daily_used(db)
            over_daily = (not self.ignore_daily_limit and self.daily_limit is not None
                          and daily + credits > self.daily_limit)
            over_run = self.run_limit is not None and self.credits + credits > self.run_limit
            if monthly + credits > self.target_limit or over_daily or over_run:
                raise QuotaExhausted('JSearch page-credit budget reached; no request sent')
            pause = db.execute('SELECT retry_at FROM account_pause WHERE id=1').fetchone()
            if pause and pause[0] > time.time():
                raise AccountPaused('JSearch account cooldown is active; no request sent')
            monthly_base = db.execute(
                'SELECT COALESCE(SUM(used), 0) FROM credit_baseline WHERE period=?', (period,)).fetchone()[0]
            if monthly + monthly_base + credits > self.target_limit:
                raise QuotaExhausted('JSearch page-credit budget reached; no request sent')
            db.execute('UPDATE usage SET used=used+?, last_sent=? WHERE id=1', (credits, time.time()))
            db.execute('INSERT INTO credit_usage VALUES (?, ?, ?) ON CONFLICT(period, day) DO UPDATE SET used=used+excluded.used', (period, day, credits))
            event = db.execute('INSERT INTO credit_events (at, period, day, credits) VALUES (?, ?, ?, ?)',
                               (time.time(), period, day, credits)).lastrowid
            db.commit()
            self.attempts += 1
            self.credits += credits
        # The reservation is committed before the request leaves, so a network
        # error or a crash still shows the credit as spent. Only the outcome is
        # written afterwards, and failing to write it never refunds anything.
        try:
            response = session.get(url, allow_redirects=False, **kwargs)
        except BaseException as exc:
            self.settle(event, 'transport:' + type(exc).__name__)
            raise
        self.settle(event, f'http:{response.status_code}', response.headers)
        return response

    # The provider states what a call cost, not what is left, as
    # `X-RapidAPI-Billing: Queries=1; Requests=1`. Recording it is how a charge
    # that differs from the credit we reserved becomes visible at all.
    BILLING_HEADER = 'X-RapidAPI-Billing'

    def settle(self, event, outcome, headers=None):
        # requests' header mapping is case-insensitive; a plain dict is not.
        raw = (headers or {}).get(self.BILLING_HEADER,
                                  (headers or {}).get(self.BILLING_HEADER.lower()))
        found = re.search(r'Queries\s*=\s*(\d+)', str(raw or ''))
        charged = int(found.group(1)) if found else None
        with connect(self.path, timeout=120) as db:
            db.execute('UPDATE credit_events SET outcome=?, provider_charged=? WHERE id=?',
                       (outcome, charged, event))
