-- Provider IDs resolve repeated discovery queries to the same stored job URL.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS job_identities (
    provider_key TEXT NOT NULL,
    scope TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    url TEXT NOT NULL REFERENCES jobs(url),
    PRIMARY KEY (provider_key, scope, source_job_id)
);
CREATE INDEX IF NOT EXISTS job_identities_url ON job_identities(url);
INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('003_job_identities');
COMMIT;
