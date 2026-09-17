-- Durable job records plus the per-source state that makes runs incremental.
-- first_seen/last_seen are our own observations and exist for every board;
-- posted_at only exists where the board states an absolute date, so recency
-- reporting must never depend on it alone.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS catalog_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY CHECK(url LIKE 'http%'),
    company_key TEXT NOT NULL,
    provider_key TEXT NOT NULL CHECK(length(trim(provider_key)) > 0),
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    location TEXT NOT NULL DEFAULT '',
    source_job_id TEXT,
    -- Absolute posting date as published by the board, never derived.
    posted_at TEXT,
    -- Relative phrasing kept verbatim, e.g. Workday "Posted 7 Days Ago".
    posted_relative TEXT,
    -- Sitemap <lastmod>, used to skip unchanged detail pages.
    lastmod TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    closed_at TEXT,
    raw TEXT NOT NULL,
    CHECK(closed_at IS NULL OR closed_at >= first_seen)
);
CREATE INDEX IF NOT EXISTS jobs_open ON jobs(company_key, closed_at);
CREATE INDEX IF NOT EXISTS jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS jobs_posted_at ON jobs(posted_at);

CREATE TABLE IF NOT EXISTS source_state (
    source_id TEXT PRIMARY KEY,
    company_key TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    -- Validators for conditional requests; a 304 means skip the source entirely.
    etag TEXT,
    last_modified TEXT,
    -- Only a fully successful pass may be used as an incremental watermark.
    last_success_at TEXT,
    last_run_at TEXT,
    last_status TEXT NOT NULL DEFAULT '',
    strategy TEXT NOT NULL DEFAULT 'full'
        CHECK(strategy IN ('full', 'conditional', 'since', 'lastmod')),
    job_count INTEGER NOT NULL DEFAULT 0 CHECK(job_count >= 0),
    requests INTEGER NOT NULL DEFAULT 0 CHECK(requests >= 0),
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    companies INTEGER NOT NULL DEFAULT 0,
    jobs_seen INTEGER NOT NULL DEFAULT 0,
    jobs_new INTEGER NOT NULL DEFAULT 0,
    jobs_closed INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT ''
);

INSERT INTO catalog_migrations (migration_key) SELECT '002_job_store'
WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='002_job_store');
COMMIT;
