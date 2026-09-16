PRAGMA foreign_keys = ON;

-- Storage for downloaded job postings. Fully decoupled from schema.sql (no FK into it).
-- Source DEFINITIONS live in TOML: ats_providers.toml (company boards),
-- sources_publicfeed.toml (no-auth feeds), sources_search.toml (keyword APIs).
-- source_key = company_sources.source_instance_id | feeds.* key | search.* key.

CREATE TABLE IF NOT EXISTS fetch_runs (
    run_id INTEGER PRIMARY KEY,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('ats', 'feed', 'search')),
    source_key TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    http_status INTEGER,
    job_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,  -- source_key:external_id
    source_kind TEXT NOT NULL CHECK (source_kind IN ('ats', 'feed', 'search')),
    source_key TEXT NOT NULL,
    external_id TEXT NOT NULL,
    company_name TEXT,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    posted_at TEXT,
    raw_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_open INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
    apply_status TEXT NOT NULL DEFAULT 'new' CHECK (apply_status IN ('new', 'shortlisted', 'applied', 'rejected', 'ignored')),
    UNIQUE (source_key, external_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source_key, is_open);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (apply_status, is_open);

CREATE VIEW IF NOT EXISTS open_jobs AS
SELECT job_id, source_kind, source_key, company_name, title, location, url, posted_at, apply_status
FROM jobs WHERE is_open = 1;

-- Fetcher contract (per run):
-- 1. INSERT INTO fetch_runs (source_kind, source_key, http_status, job_count) VALUES (?, ?, ?, ?);
-- 2. Per job:
--    INSERT INTO jobs (job_id, source_kind, source_key, external_id, company_name, title, location, url, posted_at, raw_json)
--    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
--    ON CONFLICT(job_id) DO UPDATE SET
--        company_name = excluded.company_name, title = excluded.title, location = excluded.location,
--        url = excluded.url, posted_at = excluded.posted_at, raw_json = excluded.raw_json,
--        last_seen_at = datetime('now'), is_open = 1;
-- 3. Full-dump sources only (ats + feed) — close postings that vanished:
--    UPDATE jobs SET is_open = 0 WHERE source_key = ? AND last_seen_at < :run_started_at;
