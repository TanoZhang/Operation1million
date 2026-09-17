"""Durable job store: baseline on the first pass, differences after that.

A run only learns what is new by comparing against what the previous run stored,
so the incremental strategies here all key off `source_state`. That table is
empty before the first run, which makes the first pass a full download of every
board without needing a separate mode.
"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .paths import CONFIG, DB, ROOT

MIGRATION = CONFIG / 'migrations/002_job_store.sql'

# Boards whose listing is strictly newest-first, verified by sampling offsets
# across the whole result set. Only these may stop paginating early; a board
# that merely trends newest-first would silently drop postings.
MONOTONIC_NEWEST_FIRST = {'eightfold'}
# Boards that publish <lastmod> per job URL, so unchanged detail pages are skipped.
LASTMOD_SITEMAP = {'renesas_careers'}


def now():
    return datetime.now(timezone.utc).isoformat()


def migrate(path=DB):
    """Apply the job store migration, backing the catalog up the first time."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError('Existing job catalog database required')
    with closing(sqlite3.connect(path)) as db:
        applied = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if not applied:
            backup = ROOT / '.local/backups/job_discovery_before_job_store.sqlite'
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as destination:
                    db.backup(destination)
        db.executescript(MIGRATION.read_text(encoding='utf-8'))


def connect(path=DB):
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db


def load_state(path=DB):
    """Per-source incremental state, empty before the first run."""
    with closing(connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='source_state'").fetchone():
            return {}
        return {row['source_id']: dict(row) for row in db.execute('SELECT * FROM source_state')}


def plan(source, state):
    """Pick the cheapest safe strategy for one source.

    Without stored state the answer is always a full download, which is what the
    first run does for every board.
    """
    row = state.get(source.source_id) or {}
    if not row.get('last_success_at'):
        return 'full', None
    if row.get('etag'):
        return 'conditional', row['etag']
    if source.provider_key in MONOTONIC_NEWEST_FIRST:
        return 'since', row['last_success_at']
    if source.provider_key in LASTMOD_SITEMAP:
        return 'lastmod', row['last_success_at']
    return 'full', None


def known_urls(db, company_key):
    """URLs already held for a company, so per-job fetches can be skipped.

    Only useful where a board costs one request per posting, such as a sitemap
    with detail pages; a listing endpoint returns every posting in bulk whether
    we hold it or not.
    """
    return {r[0] for r in db.execute(
        'SELECT url FROM jobs WHERE company_key=?', (company_key,))}


def record_source(db, source, rows, status, strategy, requests, etag=None,
                  last_modified=None, note='', stamp=None, listed=None):
    """Upsert one source's rows and close postings it no longer lists.

    `listed` is every URL the board still advertises, which differs from `rows`
    when a pass deliberately skipped fetching postings it already holds. Closing
    compares against what the board listed, never against what we chose to
    download, or skipping a fetch would retire a live posting.

    Closing only happens for a complete pass. A capped, paused or failed pass has
    not seen the whole board, so treating its absences as closures would retire
    live postings.
    """
    stamp = stamp or now()
    seen = set()
    # Ask which URLs we already hold before writing. Comparing first_seen to
    # last_seen afterwards would call everything new whenever two passes land on
    # the same clock tick, which Windows timer granularity makes possible.
    incoming = [r['url'] for r in rows]
    known = set()
    for start in range(0, len(incoming), 400):
        chunk = incoming[start:start + 400]
        known.update(r[0] for r in db.execute(
            'SELECT url FROM jobs WHERE url IN (%s)' % ','.join('?' * len(chunk)), chunk))
    new = len({u for u in incoming if u not in known})
    for row in rows:
        raw = row.get('raw')
        posted_relative = lastmod = None
        if isinstance(raw, dict):
            # normalize() emits only FIELDS, so these live on the original record.
            value = raw.get('postedOn') or raw.get('posted_text')
            posted_relative = value if isinstance(value, str) else None
            value = raw.get('lastmod')
            lastmod = value if isinstance(value, str) else None
        url = row['url']
        seen.add(url)
        db.execute(
            '''INSERT INTO jobs (url, company_key, provider_key, title, location,
                   source_job_id, posted_at, posted_relative, lastmod,
                   first_seen, last_seen, closed_at, raw)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
               ON CONFLICT(url) DO UPDATE SET
                   title=excluded.title,
                   location=excluded.location,
                   source_job_id=COALESCE(excluded.source_job_id, jobs.source_job_id),
                   posted_at=COALESCE(excluded.posted_at, jobs.posted_at),
                   posted_relative=COALESCE(excluded.posted_relative, jobs.posted_relative),
                   lastmod=COALESCE(excluded.lastmod, jobs.lastmod),
                   last_seen=excluded.last_seen,
                   closed_at=NULL,
                   raw=excluded.raw''',
            (url, row['company_key'], row['provider_key'], row['title'],
             row.get('location') or '', row.get('source_job_id'), row.get('posted_at'),
             posted_relative, lastmod, stamp, stamp,
             json.dumps(raw, ensure_ascii=True, default=str)))
    fresh = sorted(u for u in incoming if u not in known)
    live = set(listed) if listed else seen
    # Postings the board still lists but this pass skipped fetching are alive.
    for start in range(0, len(live - seen), 400):
        chunk = sorted(live - seen)[start:start + 400]
        db.execute(
            'UPDATE jobs SET last_seen=? WHERE url IN (%s)' % ','.join('?' * len(chunk)),
            [stamp, *chunk])
    closed_urls = []
    if status == 'complete':
        placeholders = ','.join('?' * len(live)) or 'NULL'
        closed_urls = [r[0] for r in db.execute(
            f'''SELECT url FROM jobs WHERE company_key=? AND closed_at IS NULL
                AND url NOT IN ({placeholders})''', [source.company_key, *live])]
        db.execute(
            f'''UPDATE jobs SET closed_at=? WHERE company_key=? AND closed_at IS NULL
                AND url NOT IN ({placeholders})''',
            [stamp, source.company_key, *live])
    closed = len(closed_urls)
    db.execute(
        '''INSERT INTO source_state (source_id, company_key, provider_key, etag,
               last_modified, last_success_at, last_run_at, last_status, strategy,
               job_count, requests, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_id) DO UPDATE SET
               etag=COALESCE(excluded.etag, source_state.etag),
               last_modified=COALESCE(excluded.last_modified, source_state.last_modified),
               last_success_at=COALESCE(excluded.last_success_at, source_state.last_success_at),
               last_run_at=excluded.last_run_at,
               last_status=excluded.last_status,
               strategy=excluded.strategy,
               job_count=excluded.job_count,
               requests=excluded.requests,
               note=excluded.note''',
        (source.source_id, source.company_key, source.provider_key, etag,
         last_modified, stamp if status == 'complete' else None, stamp, status,
         strategy, len(seen), requests, note))
    return {'seen': len(seen), 'new': new, 'closed': closed,
            'new_urls': fresh, 'closed_urls': closed_urls, 'stamp': stamp}


def touch_source(db, source, strategy, requests, etag=None, last_modified=None,
                 note='', stamp=None):
    """Record a source that answered 304 Not Modified.

    An unchanged board means every posting we already hold is still listed, so
    refresh last_seen and close nothing. This is the only path that advances a
    source's watermark without having read any rows.
    """
    stamp = stamp or now()
    seen = db.execute(
        'UPDATE jobs SET last_seen=? WHERE company_key=? AND closed_at IS NULL',
        (stamp, source.company_key)).rowcount
    db.execute(
        """UPDATE source_state SET etag=COALESCE(?, etag),
               last_modified=COALESCE(?, last_modified), last_success_at=?,
               last_run_at=?, last_status='unchanged', strategy=?, job_count=?,
               requests=?, note=? WHERE source_id=?""",
        (etag, last_modified, stamp, stamp, strategy, seen, requests, note,
         source.source_id))
    return {'seen': seen, 'new': 0, 'closed': 0}


def start_run(db, run_id):
    db.execute('INSERT OR REPLACE INTO collection_runs (run_id, started_at) VALUES (?, ?)',
               (run_id, now()))


def finish_run(db, run_id, companies, seen, new, closed, requests, note=''):
    db.execute(
        '''UPDATE collection_runs SET finished_at=?, companies=?, jobs_seen=?,
               jobs_new=?, jobs_closed=?, requests=?, note=? WHERE run_id=?''',
        (now(), companies, seen, new, closed, requests, note, run_id))


def summary(path=DB):
    with closing(connect(path)) as db:
        open_jobs = db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        dated = db.execute(
            'SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL AND posted_at IS NOT NULL'
        ).fetchone()[0]
        return {'open': open_jobs, 'total': total, 'with_posted_at': dated}
