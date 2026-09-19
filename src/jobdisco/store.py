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
        db.executescript((CONFIG / 'migrations/003_job_identities.sql').read_text(encoding='utf-8'))
        applied = {r[0] for r in db.execute('SELECT migration_key FROM catalog_migrations')}
        if '004_relevance' not in applied:
            db.executescript((CONFIG / 'migrations/004_relevance.sql').read_text(encoding='utf-8'))
        if '005_seen_jobs' not in applied:
            db.executescript((CONFIG / 'migrations/005_seen_jobs.sql').read_text(encoding='utf-8'))


SEEN_SNAPSHOT = 'operational/seen_jobs.ndjson.gz'
SEEN_COLUMNS = ['provider_key', 'source_job_id', 'url', 'title', 'employer',
                'first_seen', 'last_seen', 'decision', 'confidence', 'filter_version']


def export_seen(db, root=None):
    """Write the whole seen table to the data repository, for a machine that dies.

    It lives under `operational/` rather than in the daily log, and that is the
    whole point. The log is a fourteen-day rolling backup; knowing that a job
    has been seen before must outlast it, or on the fifteenth day every posting
    the provider still lists becomes new again and is scored and rejected from
    scratch. The table is small enough that keeping all of it costs less than
    the pass that would otherwise re-decide it.

    A snapshot rather than an append, because the rows change: last_seen moves
    and a decision can flip when the filter does.
    """
    root = Path(root) if root is not None else LOG
    path = root / SEEN_SNAPSHOT
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    written = 0
    with gzip.open(temporary, 'wt', encoding='utf-8') as handle:
        for row in db.execute('SELECT %s FROM seen_jobs ORDER BY provider_key, source_job_id'
                              % ', '.join(SEEN_COLUMNS)):
            handle.write(json.dumps(dict(zip(SEEN_COLUMNS, row)), ensure_ascii=True) + '\n')
            written += 1
    temporary.replace(path)
    return written


def import_seen(db, root=None):
    """Restore the seen table from the snapshot, if the repository carries one."""
    root = Path(root) if root is not None else LOG
    path = root / SEEN_SNAPSHOT
    if not path.exists():
        return 0
    restored = 0
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        batch = []
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            batch.append([row.get(name) for name in SEEN_COLUMNS])
            if len(batch) >= 1000:
                restored += _insert_seen(db, batch)
                batch = []
        restored += _insert_seen(db, batch)
    return restored


def _insert_seen(db, batch):
    if not batch:
        return 0
    db.executemany(
        'INSERT OR REPLACE INTO seen_jobs (%s) VALUES (%s)'
        % (', '.join(SEEN_COLUMNS), ', '.join('?' * len(SEEN_COLUMNS))), batch)
    return len(batch)


def record_seen(db, rows, stamp=None):
    """Note that a provider returned these jobs, whatever was decided about them.

    Called before the filter, so a posting that is about to be rejected still
    leaves something behind. The question this answers is only "have we seen
    this before"; the answer to "is it worth applying to" lives in `jobs`.

    `first_seen` is written once and never moved. Everything else is refreshed,
    because a posting can be retitled, and because a filter change can turn
    yesterday's rejection into today's acceptance.
    """
    stamp = stamp or now()
    payload = [(row.get('provider_key') or 'jsearch',
                row.get('source_job_id') or row.get('url') or '',
                row.get('url') or '', row.get('title') or '',
                row.get('employer') or '', stamp, stamp,
                row.get('decision') or '', row.get('confidence'),
                row.get('filter_version') or '')
               for row in rows
               if (row.get('source_job_id') or row.get('url'))]
    if not payload:
        return 0
    db.executemany(
        '''INSERT INTO seen_jobs (provider_key, source_job_id, url, title, employer,
               first_seen, last_seen, decision, confidence, filter_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(provider_key, source_job_id) DO UPDATE SET
               url=excluded.url, title=excluded.title, employer=excluded.employer,
               last_seen=excluded.last_seen, decision=excluded.decision,
               confidence=excluded.confidence, filter_version=excluded.filter_version''',
        payload)
    return len(payload)


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


_FILTER_RULES = None


def filter_rules():
    global _FILTER_RULES
    if _FILTER_RULES is None:
        from . import jsearch
        _FILTER_RULES = jsearch.load_plan()[0]['filter']
    return _FILTER_RULES


def score_row(title, raw):
    """Relevance of one posting, 0..100, on the same yardstick for every source.

    A company's own board is not a filtered list; it carries that company's
    accountants and HR interns too, so a direct posting earns its rank exactly
    as a search result does.
    """
    from . import jsearch
    if jsearch.employer_excluded({'raw': raw}, filter_rules()) or jsearch.excluded(title, filter_rules()):
        return 0
    stored = raw.get('relevance') if isinstance(raw, dict) else None
    if isinstance(stored, dict) and isinstance(stored.get('confidence'), int):
        return stored['confidence']
    return calculate_score(title, raw)


def calculate_score(title, raw):
    """Compute from the current rules, ignoring any score embedded in raw."""
    from . import jsearch
    return jsearch.relevance({'title': title or '', 'raw': raw}, filter_rules())[0]


MAX_CLOSURE_FRACTION = 0.25


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
    open_before = db.execute(
        '''SELECT COUNT(*) FROM jobs WHERE company_key=? AND provider_key=?
           AND closed_at IS NULL''',
        (source.company_key, source.provider_key)).fetchone()[0]
    seen = set()
    prepared, before_rows, pending_identities = [], {}, {}
    for original in rows:
        row = dict(original)
        scope = '' if row['provider_key'] == 'jsearch' else row['company_key']
        identity = (row['provider_key'], scope, str(row['source_job_id'])) if row.get('source_job_id') else None
        mapped = db.execute('SELECT url FROM job_identities WHERE provider_key=? AND scope=? AND source_job_id=?', identity).fetchone() if identity else None
        if mapped:
            row['url'] = mapped[0]
        elif identity in pending_identities:
            row['url'] = pending_identities[identity]
        previous = db.execute('SELECT * FROM jobs WHERE url=?', (row['url'],)).fetchone()
        before_rows.setdefault(row['url'], dict(previous) if previous else None)
        if previous:
            old_raw = json.loads(previous['raw'] or 'null')
            if previous['provider_key'] != 'jsearch' and row['provider_key'] == 'jsearch':
                # Direct title, employer and source identity stay authoritative.
                enrichment = dict(old_raw or {})
                enrichment['jsearch'] = merge_raw(enrichment.get('jsearch'), row['raw'])
                for field in ('company_key', 'provider_key', 'title', 'location', 'source_job_id', 'posted_at'):
                    row[field] = previous[field]
                row['raw'] = enrichment
            else:
                row['raw'] = merge_raw(old_raw, row.get('raw'))
        prepared.append((row, identity))
        if identity:
            pending_identities[identity] = row['url']
    rows = [r for r, _ in prepared]
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
        raw = slim(row.get('raw'))
        current = db.execute('SELECT raw FROM jobs WHERE url=?', (row['url'],)).fetchone()
        if current:
            raw = slim(merge_raw(json.loads(current['raw'] or 'null'), raw))
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
                   first_seen, last_seen, closed_at, raw, relevance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                   company_key=excluded.company_key,
                   provider_key=excluded.provider_key,
                   title=excluded.title,
                   location=excluded.location,
                   source_job_id=COALESCE(excluded.source_job_id, jobs.source_job_id),
                   posted_at=COALESCE(excluded.posted_at, jobs.posted_at),
                   posted_relative=COALESCE(excluded.posted_relative, jobs.posted_relative),
                   lastmod=COALESCE(excluded.lastmod, jobs.lastmod),
                   last_seen=excluded.last_seen,
                   closed_at=NULL,
                   raw=excluded.raw,
                   relevance=COALESCE(jobs.relevance, excluded.relevance)''',
            (url, row['company_key'], row['provider_key'], row['title'],
             row.get('location') or '', row.get('source_job_id'), row.get('posted_at'),
             posted_relative, lastmod, stamp, stamp,
             json.dumps(raw, ensure_ascii=True, default=str),
             # Score a posting once, when it first arrives. Every pass re-reads the
             # whole board, so re-scoring what has not changed would spend a minute
             # a day recomputing the same numbers. `job-store --rescore` covers the
             # case that does change them: an edit to the term lists.
             score_row(row['title'], raw) if url not in known else None))
    for identity, url in pending_identities.items():
        db.execute('INSERT OR IGNORE INTO job_identities VALUES (?, ?, ?, ?)', (*identity, url))
    # A stable provider ID may outlive a title-derived URL slug. Historical
    # imports can therefore contain both the old and new URL even though the
    # identity table correctly points at one canonical row. Closing those stale
    # aliases is identity deduplication, not inventory retirement: it is safe on
    # a partial pass because no distinct provider ID is inferred absent.
    identity_duplicates = set()
    for (provider_key, scope, source_job_id), canonical_url in pending_identities.items():
        params = [provider_key, source_job_id, canonical_url]
        company_clause = ''
        if provider_key != 'jsearch':
            company_clause = ' AND company_key=?'
            params.append(scope)
        identity_duplicates.update(r[0] for r in db.execute(
            '''SELECT url FROM jobs WHERE provider_key=? AND source_job_id=?
               AND url<>? AND closed_at IS NULL''' + company_clause, params))
    if identity_duplicates:
        db.executemany('UPDATE jobs SET closed_at=? WHERE url=?',
                       [(stamp, url) for url in sorted(identity_duplicates)])
    fresh = sorted(set(u for u in incoming if u not in known))
    changed = []
    for url in seen - set(fresh):
        old = before_rows[url]
        latest = dict(db.execute('SELECT * FROM jobs WHERE url=?', (url,)).fetchone())
        if old and any(old[k] != latest[k] for k in ('company_key', 'provider_key', 'title', 'location', 'source_job_id', 'posted_at', 'raw', 'closed_at')):
            changed.append(url)
    # Identity resolution can retain an old canonical URL after a sitemap slug
    # changes. Successfully read rows remain live under that canonical URL too.
    live = set(listed) | seen if listed is not None else seen
    seen_count = len(live)
    # Postings the board still lists but this pass skipped fetching are alive.
    for start in range(0, len(live - seen), 400):
        chunk = sorted(live - seen)[start:start + 400]
        db.execute(
            'UPDATE jobs SET last_seen=? WHERE url IN (%s)' % ','.join('?' * len(chunk)),
            [stamp, *chunk])
    closed_urls = sorted(identity_duplicates)
    closure_candidates = []
    closure_ratio = 0.0
    effective_status = status
    effective_note = note
    if status == 'complete' and strategy != 'since' and source.provider_key != 'jsearch':
        placeholders = ','.join('?' * len(live)) or "''" 
        closure_candidates = [r[0] for r in db.execute(
            f'''SELECT url FROM jobs WHERE company_key=? AND provider_key=? AND closed_at IS NULL
                AND url NOT IN ({placeholders})''', [source.company_key, source.provider_key, *live])]
        closure_ratio = len(closure_candidates) / open_before if open_before else 0.0
        if closure_ratio > MAX_CLOSURE_FRACTION:
            effective_status = 'partial'
            fuse = (f'Closure fuse blocked {len(closure_candidates)} of {open_before} open '
                    f'{source.company_key}/{source.provider_key} jobs '
                    f'({closure_ratio:.1%}); limit is {MAX_CLOSURE_FRACTION:.0%}; '
                    'no jobs were retired')
            effective_note = '; '.join(filter(None, [note, fuse]))
        else:
            closed_urls.extend(closure_candidates)
            db.execute(
                f'''UPDATE jobs SET closed_at=? WHERE company_key=? AND provider_key=? AND closed_at IS NULL
                    AND url NOT IN ({placeholders})''',
                [stamp, source.company_key, source.provider_key, *live])
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
         last_modified, stamp if effective_status == 'complete' else None, stamp,
         effective_status, strategy, seen_count, requests, effective_note))
    return {'seen': seen_count, 'new': new, 'closed': closed,
            'new_urls': fresh, 'changed_urls': changed,
            'seen_urls': sorted(live - set(fresh) - set(changed)),
            'closed_urls': closed_urls, 'stamp': stamp,
            'status': effective_status, 'note': effective_note,
            'closure_candidates': len(closure_candidates),
            'closure_ratio': closure_ratio, 'closure_fused': effective_status != status}


def touch_source(db, source, strategy, requests, etag=None, last_modified=None,
                 note='', stamp=None):
    """Record a source that answered 304 Not Modified.

    An unchanged board means every posting we already hold is still listed, so
    refresh last_seen and close nothing. This is the only path that advances a
    source's watermark without having read any rows.
    """
    stamp = stamp or now()
    seen = db.execute(
        'UPDATE jobs SET last_seen=? WHERE company_key=? AND provider_key=? AND closed_at IS NULL',
        (stamp, source.company_key, source.provider_key)).rowcount
    db.execute(
        """UPDATE source_state SET etag=COALESCE(?, etag),
               last_modified=COALESCE(?, last_modified), last_success_at=?,
               last_run_at=?, last_status='unchanged', strategy=?, job_count=?,
               requests=?, note=? WHERE source_id=?""",
        (etag, last_modified, stamp, stamp, strategy, seen, requests, note,
         source.source_id))
    # Every persist path returns the same shape. A caller that has to ask which
    # one it got will one day forget, and a 304 is the ordinary case, not the
    # rare one: a board that answers unchanged is the cheapest pass there is.
    return {'seen': seen, 'new': 0, 'closed': 0,
            'new_urls': [], 'changed_urls': [], 'closed_urls': [], 'stamp': stamp,
            'status': 'unchanged', 'note': note,
            'closure_candidates': 0, 'closure_ratio': 0.0, 'closure_fused': False,
            'seen_urls': [r[0] for r in db.execute('SELECT url FROM jobs WHERE company_key=? AND provider_key=? AND closed_at IS NULL', (source.company_key, source.provider_key))]}


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
    'savedSearchMetadata', 'resultsMetaData', 'debug', 'tracking', 'tracking_metadata',
    'ranking', 'ranking_score', 'review_counts', 'employer_review_count',
    # Benefits blurbs: marketing copy, identical across a company's postings.
    'benefits', 'jobBenefits', 'job_benefits', 'job_benefits_strings',
    # Duplicate or truncated renderings of a description we keep in full.
    'descriptionTeaser', 'description_short',
    # The scraped row markup; normalize() already took the fields out of it.
    'html',
    # A relative age the board recomputes on every read: "8 days" becomes
    # "9 days" with nothing about the posting having changed. Keeping it made
    # every Amazon posting differ from itself once a day, and a differing row
    # is rewritten into the log in full, description and all -- 9,993 rows and
    # about 92 MB per pass, for a string the absolute posted_at already says.
    'updated_time',
}
# The score is a pure function of the title, the raw record and the term list,
# and it is computed once on write. Carrying it in the log keeps a rebuild as
# cheap as the replay itself: recomputing it costs two minutes for 39,000
# postings, which a runner would otherwise pay on every single run.
LOG_FIELDS = ['url', 'company_key', 'provider_key', 'title', 'location', 'source_job_id',
              'posted_at', 'posted_relative', 'lastmod', 'first_seen', 'last_seen', 'closed_at',
              'relevance', 'raw']
MAX_DAILY_LOG_BYTES = 90_000_000


def merge_raw(previous, incoming):
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return incoming if incoming is not None else previous
    result = dict(previous)
    for key, value in incoming.items():
        if value is not None:
            result[key] = value
    if 'discovery_queries' in previous or 'discovery_queries' in incoming:
        result['discovery_queries'] = sorted(set(previous.get('discovery_queries', []) + incoming.get('discovery_queries', [])))
    return result


def slim(raw):
    """Drop fields that say nothing about the job, keeping everything else in full.

    Deliberately name-based rather than size-based: the description and the
    requirements are long precisely because they are the content worth having, and
    a length rule throws them away. Anything not named here survives, so a field
    from a provider we have not catalogued is kept rather than silently lost.
    """
    if not isinstance(raw, dict):
        return raw
    from bs4 import BeautifulSoup
    result = {k: slim(v) if isinstance(v, dict) else
              [slim(x) for x in v] if isinstance(v, list) else v
              for k, v in raw.items() if k not in DROP_FIELDS}
    # Drop duplicate HTML only after verifying equivalent full plain text.
    plain = next((str(result[k]).strip() for k in ('descriptionPlain', 'job_description', 'description')
                  if result.get(k)), '')
    for key in ('descriptionHtml', 'jobDescriptionHtml'):
        value = result.get(key)
        if isinstance(value, str) and plain and ' '.join(BeautifulSoup(value, 'html.parser').stripped_strings) == ' '.join(plain.split()):
            result.pop(key)
    return result


def sealed(stamp):
    """Whether a day is closed to further writing.

    A day seals when it is over, not when a run finishes. What is worth
    protecting is that a day already in the record never changes again; a second
    pass on the same day is ordinary, and its postings belong in that day's file
    beside the first pass's. The manifest is rewritten each time, so its digest
    always describes the file as it currently stands, and becomes final when the
    day does.
    """
    return stamp[:10] < now()[:10]


def daily_log(stamp):
    """One immutable gzipped file per collection day.

    Gzip is right here precisely because the file stops changing once the day ends:
    there is no later revision for Git to delta against, and the content compresses
    9x. An append-only file that got rewritten daily would be the opposite case.
    """
    return LOG / 'runs' / f'{stamp[:10]}.ndjson.gz'


def manifest_path(stamp):
    return LOG / 'manifests' / f'{stamp[:10]}.json'


def _file_facts(path):
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            sha.update(block)
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        records = sum(1 for line in handle if line.strip())
    return sha.hexdigest(), records


def _file_digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            sha.update(block)
    return sha.hexdigest()


def _write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, indent=1, sort_keys=True) + '\n',
        encoding='utf-8')
    temporary.replace(path)


def shard_daily_log(stamp):
    """Move the current UTC day's main log to the next immutable shard."""
    path = daily_log(stamp)
    if not path.is_file() or not path.stat().st_size:
        return None
    day = stamp[:10]
    numbers = []
    for existing in (LOG / 'runs').glob(f'{day}-*.ndjson.gz'):
        suffix = existing.name[len(day) + 1:-len('.ndjson.gz')]
        if suffix.isdigit():
            numbers.append(int(suffix))
    number = max(numbers, default=0) + 1
    shard = path.with_name(f'{day}-{number:04d}.ndjson.gz')
    shard_manifest = (LOG / 'manifests' / shard.name.removesuffix('.ndjson.gz')).with_suffix('.json')
    digest, records = _file_facts(path)
    current_manifest = manifest_path(stamp)
    if current_manifest.is_file():
        manifest = json.loads(current_manifest.read_text(encoding='utf-8'))
    else:
        manifest = {'run_date': day, 'collected_at': stamp,
                    'sources_completed': 0, 'sources_unchanged': 0,
                    'sources_incomplete': 0, 'sources_failed': 0,
                    'requests': 0, 'open_jobs': None}
    manifest.update({'file': str(shard.relative_to(LOG)).replace('\\', '/'),
                     'sha256': digest, 'records': records, 'shard': number,
                     'sharded_at': stamp})
    temporary = shard_manifest.with_suffix('.json.tmp')
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=1, sort_keys=True) + '\n',
        encoding='utf-8')
    path.replace(shard)
    temporary.replace(shard_manifest)
    current_manifest.unlink(missing_ok=True)
    return shard


def _append_records(stamp, records):
    if not records:
        return
    path = daily_log(stamp)
    member = gzip.compress((''.join(json.dumps(r, ensure_ascii=True, sort_keys=True) + '\n'
                                    for r in records)).encode('utf-8'), mtime=0)
    if path.exists() and path.stat().st_size + len(member) > MAX_DAILY_LOG_BYTES:
        shard_daily_log(stamp)
    size = path.stat().st_size if path.exists() else 0
    try:
        with path.open('ab') as handle:
            handle.write(member)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        with path.open('r+b') as handle:
            handle.truncate(size)
        raise


def append_log(db, urls, closed_urls, stamp, seen_urls=(), source_id=None):
    """Append this pass's discoveries and closures to the day's durable file.

    The log, not the SQLite file, is what persists between runs: a binary database
    committed daily would store a full copy per commit, while a day's text file is
    written once and reviewable in a diff.
    """
    path = daily_log(stamp)
    if sealed(stamp):
        raise FileExistsError('Daily log is sealed; refusing to change a day that is over')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not urls and not closed_urls and not seen_urls and not source_id:
        return
    # Build a complete gzip member before touching the existing stream. Restore
    # its previous length if a write fails; never leave half a member appended.
    records = []
    for start in range(0, len(urls), 400):
        chunk = urls[start:start + 400]
        for row in db.execute(
                'SELECT %s FROM jobs WHERE url IN (%s)'
                % (','.join(LOG_FIELDS), ','.join('?' * len(chunk))), chunk):
            record = dict(row, type='job')
            record['raw'] = slim(json.loads(record['raw'] or 'null'))
            record['identities'] = [dict(r) for r in db.execute(
                'SELECT provider_key, scope, source_job_id FROM job_identities WHERE url=? ORDER BY provider_key, scope, source_job_id', (record['url'],))]
            records.append(record)
    for url in closed_urls:
        records.append({'type': 'closed', 'url': url, 'at': stamp})
    if seen_urls:
        records.append({'type': 'seen', 'urls': sorted(set(seen_urls)), 'at': stamp})
    if source_id:
        state = db.execute('SELECT * FROM source_state WHERE source_id=?', (source_id,)).fetchone()
        if state:
            records.append({'type': 'source_state', 'state': dict(state)})
    _append_records(stamp, records)


def append_scores(db, stamp, urls=None):
    """Persist compact score corrections without rewriting historical jobs."""
    if sealed(stamp):
        raise FileExistsError('Daily log is sealed; refusing to change a day that is over')
    path = daily_log(stamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    if urls is None:
        rows = db.execute('SELECT url, relevance FROM jobs WHERE relevance IS NOT NULL ORDER BY url')
    else:
        values = sorted(set(urls))
        rows = []
        for start in range(0, len(values), 400):
            chunk = values[start:start + 400]
            rows.extend(db.execute(
                'SELECT url, relevance FROM jobs WHERE relevance IS NOT NULL AND url IN (%s) ORDER BY url'
                % ','.join('?' * len(chunk)), chunk))
    records = [{'type': 'score', 'url': row['url'], 'relevance': row['relevance']}
               for row in rows]
    _append_records(stamp, records)
    return len(records)


def write_manifest(db, stamp, reports, jsearch_stats=None):
    """Record what the day collected, and checksum the file that holds it.

    The digest is what later tells you a day's data is the data that was collected,
    not something edited or truncated afterwards.
    """
    path = daily_log(stamp)
    if sealed(stamp):
        raise FileExistsError('Daily manifest is sealed; that day is over')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(gzip.compress(b'', mtime=0))
    manifest_path(stamp).parent.mkdir(parents=True, exist_ok=True)
    digest = records = None
    if path.is_file():
        digest, records = _file_facts(path)
    manifest = {
        'run_date': stamp[:10],
        'collected_at': stamp,
        'records': records,
        'sources_completed': sum(1 for r in reports if r['direct_status'] in {'complete', 'query_limited'}),
        'sources_unchanged': sum(1 for r in reports if r['direct_status'] == 'unchanged'),
        'sources_incomplete': sum(1 for r in reports
                                  if r['direct_status'] in {'partial', 'fallback', 'skipped'}),
        'sources_failed': sum(1 for r in reports
                              if r['direct_status'] in {'failed', 'paused'}),
        'requests': sum(r['requests'] for r in reports),
        'open_jobs': db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0],
        'file': str(path.relative_to(LOG)).replace('\\', '/') if path.is_file() else None,
        'sha256': digest,
    }
    if jsearch_stats:
        manifest.update(jsearch_stats)
    _write_json_atomic(manifest_path(stamp), manifest)
    return manifest


def verify(stamp=None):
    """Check each day's file against the digest recorded in its manifest."""
    results = []
    referenced = set()
    for path in sorted((LOG / 'manifests').glob('*.json')):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if stamp and manifest['run_date'] != stamp[:10]:
            continue
        data = LOG / (manifest.get('file') or '')
        if manifest.get('file'):
            referenced.add(data.resolve())
        if not manifest.get('sha256') or not data.is_file():
            results.append((path.stem, 'missing'))
            continue
        digest = _file_digest(data)
        results.append((path.stem,
                        'ok' if digest == manifest['sha256'] else 'MISMATCH'))
    for data in sorted((LOG / 'runs').glob('*.ndjson.gz')):
        if stamp and not data.name.startswith(stamp[:10]):
            continue
        if data.resolve() not in referenced:
            results.append((data.name.removesuffix('.ndjson.gz'), 'missing-manifest'))
    return results


def export_state(db):
    """Per-source incremental state as small readable JSON beside the log."""
    LOG.mkdir(parents=True, exist_ok=True)
    rows = [dict(r) for r in db.execute('SELECT * FROM source_state ORDER BY source_id')]
    temporary = LOG / 'source_state.json.tmp'
    temporary.write_text(
        json.dumps(rows, ensure_ascii=True, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(LOG / 'source_state.json')


def bootstrap(path=DB):
    """Build the whole database from versioned text, for a runner that has none.

    Nothing binary needs to be stored anywhere: the catalog comes from the authored
    SQL in this repository, and the collected postings come from the committed log.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.bootstrap.tmp')
    temporary.unlink(missing_ok=True)
    con = sqlite3.connect(temporary)
    try:
        con.isolation_level = None
        con.executescript((CONFIG / 'schema.sql').read_text(encoding='utf-8'))
        for migration in sorted((CONFIG / 'migrations').glob('*.sql')):
            con.executescript(migration.read_text(encoding='utf-8'))
    finally:
        con.close()
    try:
        counts = rebuild(temporary)
        for suffix in ('-wal', '-shm'):
            Path(str(path) + suffix).unlink(missing_ok=True)
        temporary.replace(path)
        return counts
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def rebuild(path=DB):
    """Replay the log into the job store, so the database is disposable.

    An Actions runner starts with no database. Replaying is deterministic: every
    job line inserts or refreshes a posting, then every closure event is applied
    in order.
    """
    invalid = [(day, status) for day, status in verify() if status != 'ok']
    if invalid:
        raise ValueError(f'Daily log integrity check failed: {invalid}')
    migrate(path)
    counts = {'jobs': 0, 'events': 0, 'sources': 0}
    with closing(connect(path)) as db, db:
        # Replay in date order: a posting may be discovered, closed, and relisted.
        for log in sorted((LOG / 'runs').glob('*.ndjson.gz')):
            with gzip.open(log, 'rt', encoding='utf-8') as f:
                lines = [l for l in f if l.strip()]
            for line in lines:
                r = json.loads(line)
                if r.get('type') == 'seen':
                    db.executemany('UPDATE jobs SET last_seen=? WHERE url=?',
                                   [(r['at'], url) for url in r['urls']])
                    counts['events'] += 1
                    continue
                if r.get('type') == 'source_state':
                    state_row = r['state']
                    columns = ','.join(state_row)
                    db.execute('INSERT OR REPLACE INTO source_state (%s) VALUES (%s)' %
                               (columns, ','.join('?' * len(state_row))), list(state_row.values()))
                    continue
                if r.get('type') == 'closed':
                    db.execute('UPDATE jobs SET closed_at=? WHERE url=?', (r['at'], r['url']))
                    counts['events'] += 1
                    continue
                if r.get('type') == 'score':
                    db.execute('UPDATE jobs SET relevance=? WHERE url=?',
                               (r['relevance'], r['url']))
                    counts['events'] += 1
                    continue
                raw = r.get('raw')
                relevance = r.get('relevance')
                db.execute(
                    '''INSERT INTO jobs (url, company_key, provider_key, title, location,
                           source_job_id, posted_at, posted_relative, lastmod,
                           first_seen, last_seen, closed_at, relevance, raw)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(url) DO UPDATE SET
                           company_key=excluded.company_key, provider_key=excluded.provider_key,
                           title=excluded.title, location=excluded.location,
                           posted_at=COALESCE(excluded.posted_at, jobs.posted_at),
                           first_seen=MIN(jobs.first_seen, excluded.first_seen),
                           last_seen=excluded.last_seen, closed_at=excluded.closed_at,
                           source_job_id=excluded.source_job_id,
                           posted_relative=excluded.posted_relative, lastmod=excluded.lastmod,
                           relevance=COALESCE(excluded.relevance, jobs.relevance),
                           raw=excluded.raw''',
                    (r['url'], r['company_key'], r['provider_key'], r['title'],
                     r.get('location') or '', r.get('source_job_id'), r.get('posted_at'),
                     r.get('posted_relative'), r.get('lastmod'), r['first_seen'],
                     r.get('last_seen', r['first_seen']), r.get('closed_at'),
                     # Slimmed on the way in, as a live pass would store it.
                     # A log line written before a field became noise still
                     # carries it, and replaying it verbatim put the field back
                     # -- so the next pass saw a difference that was only the
                     # policy, and rewrote the posting again. Every run.
                     relevance, json.dumps(slim(raw), ensure_ascii=True)))
                identities = r.get('identities')
                # Logs written before identity tracking have no identities key,
                # so infer their primary identity for backward compatibility.
                # A present but empty list is authoritative: the URL is a stale
                # duplicate and must not take an identity from a newer URL.
                if identities is None and r.get('source_job_id'):
                    identities = [{'provider_key': r['provider_key'],
                                   'scope': '' if r['provider_key'] == 'jsearch' else r['company_key'],
                                   'source_job_id': str(r['source_job_id'])}]
                for identity in identities or []:
                    db.execute('INSERT OR REPLACE INTO job_identities VALUES (?, ?, ?, ?)',
                               (identity['provider_key'], identity['scope'], identity['source_job_id'], r['url']))
                counts['jobs'] += 1
        state = LOG / 'source_state.json'
        if state.is_file():
            for r in json.loads(state.read_text(encoding='utf-8')):
                current = db.execute('SELECT last_run_at FROM source_state WHERE source_id=?',
                                     (r['source_id'],)).fetchone()
                if current and (current[0] or '') > (r.get('last_run_at') or ''):
                    continue
                columns = ','.join(r)
                db.execute('INSERT OR REPLACE INTO source_state (%s) VALUES (%s)'
                           % (columns, ','.join('?' * len(r))), list(r.values()))
                counts['sources'] += 1
        # Older logs predate durable relevance. Score only the final unique rows,
        # after replay, rather than every historical version of each job event.
        # A later append-only correction makes this fallback a no-op on hosted
        # runs while keeping arbitrary legacy logs self-contained.
        cursor = db.execute('SELECT url, title, raw FROM jobs WHERE relevance IS NULL')
        while True:
            rows = cursor.fetchmany(500)
            if not rows:
                break
            db.executemany(
                'UPDATE jobs SET relevance=? WHERE url=?',
                [(calculate_score(r['title'], json.loads(r['raw'] or 'null')), r['url'])
                 for r in rows])
        # The log cannot carry this: it is pruned to a rolling window and the
        # memory of having seen a job has to outlast that window. It comes back
        # from its own snapshot under operational/, which is never pruned.
        counts['seen'] = import_seen(db)
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
    parser.add_argument('--rescore', action='store_true',
                        help='Recompute every stored relevance score, after a term-list edit')
    parser.add_argument('--min-score', type=int, metavar='N',
                        help='With --ranked, hide postings scoring below N')
    parser.add_argument('--ranked', type=int, nargs='?', const=40, metavar='N',
                        help='List the N most relevant open postings')
    parser.add_argument('--since', metavar='DATE',
                        help='With --ranked, only postings first seen on or after this date')
    parser.add_argument('--export-seen', action='store_true',
                        help='Snapshot the seen table into the data repository')
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
        if any((LOG / 'runs').glob('*.ndjson.gz')) or any((LOG / 'manifests').glob('*.json')):
            parser.error('Backfill requires an empty JOBDISCO_STORE; existing history is immutable')
        with closing(connect(args.db)) as db, db:
            urls = [r[0] for r in db.execute('SELECT url FROM jobs ORDER BY url')]
            closed = [(r[0], r[1]) for r in db.execute(
                'SELECT url, closed_at FROM jobs WHERE closed_at IS NOT NULL')]
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
    if args.export_seen:
        with closing(connect(args.db)) as db, db:
            print('seen snapshot:', export_seen(db), 'rows')
    if args.rescore:
        def tick(done):
            print('  rescored %d postings' % done, flush=True)
        print('rescored:', rescore(args.db, progress=tick))
    if args.ranked:
        for row in ranked(args.db, args.ranked, args.since, args.min_score):
            score = '%3d' % row['confidence']
            print('%-6s %-22s %-52s %s' % (
                score, (row['company_name'] or '')[:22], (row['title'] or '')[:52],
                (row['posted_at'] or row['posted_relative'] or row['first_seen'] or '')[:10]))
            print('       %s' % row['url'])
    if args.verify:
        results = verify()
        for day, state in results:
            print(f'  {day}: {state}')
        if any(state != 'ok' for _, state in results):
            return 1
    print('summary:', summary(args.db))
    return 0


def summary(path=DB):
    with closing(connect(path)) as db:
        open_jobs = db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]
        total = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        dated = db.execute(
            'SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL AND posted_at IS NOT NULL'
        ).fetchone()[0]
        # Postings logged before the score travelled with them. They rank as if
        # irrelevant until `--rescore` is run, so the count is stated rather
        # than left to be discovered by an empty ranking.
        unscored = db.execute(
            'SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL AND relevance IS NULL').fetchone()[0]
        return {'open': open_jobs, 'total': total, 'with_posted_at': dated,
                'unscored': unscored}


def rescore(path=DB, batch=500, progress=None):
    """Recompute every stored score. Run this after editing the term lists.

    Read with one cursor and write with another, committing as it goes: pulling
    every posting into memory first costs a couple of hundred megabytes of stored
    descriptions, and a single transaction means an interrupted run leaves
    nothing behind and shows nothing while it works.
    """
    done, pending = 0, []
    with closing(connect(path)) as reader, closing(connect(path)) as writer:
        cursor = reader.execute('SELECT url, title, raw FROM jobs')
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                break
            pending = [(calculate_score(r['title'], json.loads(r['raw'] or 'null')), r['url'])
                       for r in rows]
            writer.executemany('UPDATE jobs SET relevance=? WHERE url=?', pending)
            writer.commit()
            done += len(pending)
            if progress:
                progress(done)
    return done


def ranked(path=DB, limit=40, since=None, minimum=None):
    """Open postings, most relevant first, from the score stored on each row."""
    clauses, params = ['j.closed_at IS NULL'], []
    if since:
        clauses.append('j.first_seen >= ?')
        params.append(since)
    if minimum is not None:
        clauses.append('COALESCE(j.relevance, 0) >= ?')
        params.append(minimum)
    params.append(limit or -1)
    with closing(connect(path)) as db:
        return [dict(r) for r in db.execute(
            'SELECT j.url, COALESCE(c.name, j.company_key) AS company_name, j.title,'
            ' j.location, j.provider_key, j.posted_at, j.posted_relative, j.first_seen,'
            ' COALESCE(j.relevance, 0) AS confidence'
            ' FROM jobs j LEFT JOIN companies c USING(company_key)'
            ' WHERE ' + ' AND '.join(clauses) +
            ' ORDER BY confidence DESC, j.posted_at DESC, j.first_seen DESC LIMIT ?', params)]


if __name__ == '__main__':
    raise SystemExit(main())
