"""Durable job store: baseline on the first pass, differences after that.

A run only learns what is new by comparing against what the previous run stored,
so the incremental strategies here all key off `source_state`. That table is
empty before the first run, which makes the first pass a full download of every
board without needing a separate mode.
"""
import gzip
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .paths import CONFIG, DATA, DB, ROOT

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
    return {'seen': seen, 'new': 0, 'closed': 0,
            'new_urls': [], 'closed_urls': [], 'stamp': stamp}


# The durable log may live in a separate (private) data repository checkout.
LOG = Path(os.environ.get('JOBDISCO_STORE') or DATA / 'store')
# Job descriptions, requirements and pay are the point of collecting at all, so they
# are kept in full. What goes is what carries no information about the job: branding
# assets, employer ratings, the provider's own relevance scoring and parser output,
# duplicate renderings of a description we already keep, and the row markup we
# scraped the normalized fields out of.
DROP_FIELDS = {
    # Branding and employer reputation.
    'employer_logo', 'hiring_organization_logo', 'logo', 'employer_reviews',
    'review_count', 'reviews', 'rating', 'stars',
    # Provider-internal scoring, parser output, compliance and UI metadata.
    'meta_data', 'metadata', 'data_compliance', 'ml_job_parser', 'ml_skills',
    'bulletFields', 'sectionLabels', 'solrScore', 'isHot', 'job_uid', 'uuid',
    'savedSearchMetadata', 'resultsMetaData', 'debug',
    # Benefits blurbs: marketing copy, identical across a company's postings.
    'benefits', 'jobBenefits', 'job_benefits', 'job_benefits_strings',
    # Duplicate or truncated renderings of a description we keep in full.
    'descriptionHtml', 'jobDescriptionHtml', 'descriptionTeaser', 'description_short',
    # The scraped row markup; normalize() already took the fields out of it.
    'html',
}
LOG_FIELDS = ['url', 'company_key', 'provider_key', 'title', 'location', 'source_job_id',
              'posted_at', 'posted_relative', 'lastmod', 'first_seen', 'raw']


def slim(raw):
    """Drop fields that say nothing about the job, keeping everything else in full.

    Deliberately name-based rather than size-based: the description and the
    requirements are long precisely because they are the content worth having, and
    a length rule throws them away. Anything not named here survives, so a field
    from a provider we have not catalogued is kept rather than silently lost.
    """
    if not isinstance(raw, dict):
        return raw
    return {k: v for k, v in raw.items() if k not in DROP_FIELDS}


def daily_log(stamp):
    """One immutable gzipped file per collection day.

    Gzip is right here precisely because the file stops changing once the day ends:
    there is no later revision for Git to delta against, and the content compresses
    9x. An append-only file that got rewritten daily would be the opposite case.
    """
    return LOG / 'runs' / f'{stamp[:10]}.ndjson.gz'


def manifest_path(stamp):
    return LOG / 'manifests' / f'{stamp[:10]}.json'


def append_log(db, urls, closed_urls, stamp):
    """Append this pass's discoveries and closures to the day's durable file.

    The log, not the SQLite file, is what persists between runs: a binary database
    committed daily would store a full copy per commit, while a day's text file is
    written once and reviewable in a diff.
    """
    path = daily_log(stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not urls and not closed_urls:
        return
    # Gzip members concatenate, so a run can append per source and still read back
    # as one stream.
    with gzip.open(path, 'at', encoding='utf-8') as f:
        for start in range(0, len(urls), 400):
            chunk = urls[start:start + 400]
            for row in db.execute(
                    'SELECT %s FROM jobs WHERE url IN (%s)'
                    % (','.join(LOG_FIELDS), ','.join('?' * len(chunk))), chunk):
                record = dict(row, type='job')
                record['raw'] = slim(json.loads(record['raw'] or 'null'))
                f.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + '\n')
        for url in closed_urls:
            f.write(json.dumps({'type': 'closed', 'url': url, 'at': stamp},
                               ensure_ascii=True, sort_keys=True) + '\n')


def write_manifest(db, stamp, reports):
    """Record what the day collected, and checksum the file that holds it.

    The digest is what later tells you a day's data is the data that was collected,
    not something edited or truncated afterwards.
    """
    path = daily_log(stamp)
    manifest_path(stamp).parent.mkdir(parents=True, exist_ok=True)
    digest = records = None
    if path.is_file():
        sha = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                sha.update(block)
        digest = sha.hexdigest()
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            records = sum(1 for line in f if line.strip())
    manifest = {
        'run_date': stamp[:10],
        'collected_at': stamp,
        'records': records,
        'sources_completed': sum(1 for r in reports if r['direct_status'] == 'complete'),
        'sources_unchanged': sum(1 for r in reports if r['direct_status'] == 'unchanged'),
        'sources_incomplete': sum(1 for r in reports
                                  if r['direct_status'] in {'partial', 'fallback'}),
        'sources_failed': sum(1 for r in reports
                              if r['direct_status'] in {'failed', 'paused'}),
        'requests': sum(r['requests'] for r in reports),
        'open_jobs': db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0],
        'file': str(path.relative_to(LOG)).replace('\\', '/') if path.is_file() else None,
        'sha256': digest,
    }
    manifest_path(stamp).write_text(
        json.dumps(manifest, ensure_ascii=True, indent=1, sort_keys=True) + '\n',
        encoding='utf-8')
    return manifest


def verify(stamp=None):
    """Check each day's file against the digest recorded in its manifest."""
    results = []
    for path in sorted((LOG / 'manifests').glob('*.json')):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if stamp and manifest['run_date'] != stamp[:10]:
            continue
        data = LOG / (manifest.get('file') or '')
        if not manifest.get('sha256') or not data.is_file():
            results.append((manifest['run_date'], 'missing'))
            continue
        sha = hashlib.sha256()
        with data.open('rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                sha.update(block)
        results.append((manifest['run_date'],
                        'ok' if sha.hexdigest() == manifest['sha256'] else 'MISMATCH'))
    return results


def export_state(db):
    """Per-source incremental state as small readable JSON beside the log."""
    LOG.mkdir(parents=True, exist_ok=True)
    rows = [dict(r) for r in db.execute('SELECT * FROM source_state ORDER BY source_id')]
    (LOG / 'source_state.json').write_text(
        json.dumps(rows, ensure_ascii=True, indent=1, sort_keys=True) + '\n', encoding='utf-8')


def bootstrap(path=DB):
    """Build the whole database from versioned text, for a runner that has none.

    Nothing binary needs to be stored anywhere: the catalog comes from the authored
    SQL in this repository, and the collected postings come from the committed log.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.isolation_level = None
    try:
        con.executescript((CONFIG / 'schema.sql').read_text(encoding='utf-8'))
        for migration in sorted((CONFIG / 'migrations').glob('*.sql')):
            con.executescript(migration.read_text(encoding='utf-8'))
    finally:
        con.close()
    return rebuild(path)


def rebuild(path=DB):
    """Replay the log into the job store, so the database is disposable.

    An Actions runner starts with no database. Replaying is deterministic: every
    job line inserts or refreshes a posting, then every closure event is applied
    in order.
    """
    migrate(path)
    counts = {'jobs': 0, 'events': 0, 'sources': 0}
    with closing(connect(path)) as db, db:
        # Replay in date order: a posting may be discovered, closed, and relisted.
        for log in sorted((LOG / 'runs').glob('*.ndjson.gz')):
            with gzip.open(log, 'rt', encoding='utf-8') as f:
                lines = [l for l in f if l.strip()]
            for line in lines:
                r = json.loads(line)
                if r.get('type') == 'closed':
                    db.execute('UPDATE jobs SET closed_at=? WHERE url=?', (r['at'], r['url']))
                    counts['events'] += 1
                    continue
                db.execute(
                    '''INSERT INTO jobs (url, company_key, provider_key, title, location,
                           source_job_id, posted_at, posted_relative, lastmod,
                           first_seen, last_seen, closed_at, raw)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                       ON CONFLICT(url) DO UPDATE SET
                           title=excluded.title, location=excluded.location,
                           posted_at=COALESCE(excluded.posted_at, jobs.posted_at),
                           first_seen=MIN(jobs.first_seen, excluded.first_seen),
                           raw=excluded.raw''',
                    (r['url'], r['company_key'], r['provider_key'], r['title'],
                     r.get('location') or '', r.get('source_job_id'), r.get('posted_at'),
                     r.get('posted_relative'), r.get('lastmod'), r['first_seen'],
                     r['first_seen'], json.dumps(r.get('raw'), ensure_ascii=True)))
                counts['jobs'] += 1
        state = LOG / 'source_state.json'
        if state.is_file():
            for r in json.loads(state.read_text(encoding='utf-8')):
                columns = ','.join(r)
                db.execute('INSERT OR REPLACE INTO source_state (%s) VALUES (%s)'
                           % (columns, ','.join('?' * len(r))), list(r.values()))
                counts['sources'] += 1
    return counts


def start_run(db, run_id):
    db.execute('INSERT OR REPLACE INTO collection_runs (run_id, started_at) VALUES (?, ?)',
               (run_id, now()))


def finish_run(db, run_id, companies, seen, new, closed, requests, note=''):
    db.execute(
        '''UPDATE collection_runs SET finished_at=?, companies=?, jobs_seen=?,
               jobs_new=?, jobs_closed=?, requests=?, note=? WHERE run_id=?''',
        (now(), companies, seen, new, closed, requests, note, run_id))


def main():
    """Inspect the store, or rebuild it from the committed log."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--migrate', action='store_true')
    parser.add_argument('--bootstrap', action='store_true',
                        help='Create the database from schema.sql, migrations and the log')
    parser.add_argument('--rebuild', action='store_true',
                        help='Replay data/store/*.ndjson into the database')
    parser.add_argument('--verify', action='store_true',
                        help='Check each day file against its manifest digest')
    parser.add_argument('--export', action='store_true',
                        help='Write every held posting to the log (one-off backfill)')
    args = parser.parse_args()
    if args.migrate:
        migrate(args.db)
    if args.bootstrap:
        print('bootstrapped:', bootstrap(args.db))
    if args.rebuild:
        print('rebuilt:', rebuild(args.db))
    if args.export:
        with closing(connect(args.db)) as db, db:
            urls = [r[0] for r in db.execute('SELECT url FROM jobs ORDER BY url')]
            closed = [(r[0], r[1]) for r in db.execute(
                'SELECT url, closed_at FROM jobs WHERE closed_at IS NOT NULL')]
            for old in (LOG / 'runs').glob('*.ndjson.gz'):
                old.unlink()
            for old in (LOG / 'manifests').glob('*.json'):
                old.unlink()
            # Group by the day each posting was first seen, so a backfill produces
            # the same per-day files a live run would have written.
            by_day = {}
            for url in urls:
                stamp = db.execute('SELECT first_seen FROM jobs WHERE url=?', (url,)).fetchone()[0]
                by_day.setdefault(stamp[:10], []).append(url)
            for day, batch in sorted(by_day.items()):
                append_log(db, batch, [], f'{day}T00:00:00+00:00')
            for url, at in closed:
                append_log(db, [], [url], at)
            for day in sorted(by_day):
                write_manifest(db, f'{day}T00:00:00+00:00', [])
            export_state(db)
        print('exported:', len(urls), 'jobs,', len(closed), 'closures')
    if args.verify:
        for day, state in verify():
            print(f'  {day}: {state}')
    print('summary:', summary(args.db))
    return 0


def summary(path=DB):
    with closing(connect(path)) as db:
        open_jobs = db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        dated = db.execute(
            'SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL AND posted_at IS NOT NULL'
        ).fetchone()[0]
        return {'open': open_jobs, 'total': total, 'with_posted_at': dated}
