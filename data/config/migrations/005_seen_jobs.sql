-- Every job a provider has ever returned, including the ones the filter threw
-- away. Until now a rejected job left nothing behind but a counter, so the same
-- posting was fetched, normalized, scored and rejected again on every pass, and
-- nothing could answer "have we seen this before".
--
-- This is deliberately not a second copy of `jobs`. It carries only what dedup
-- needs, and it holds no description and no raw payload: a rejected posting is
-- not worth storing in full, it is worth recognising.
--
-- It has no foreign key to `jobs`, which is the whole point. `job_identities`
-- could not serve here because its url references jobs(url), and a rejected
-- posting has no row there to reference.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS seen_jobs (
    provider_key TEXT NOT NULL,
    -- The provider's stable id where it gives one, the url where it does not.
    source_job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    employer TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    -- '' when the job was accepted; otherwise the reason it was not.
    decision TEXT NOT NULL DEFAULT '',
    confidence INTEGER,
    -- Which filter configuration produced that decision. Recorded so a changed
    -- filter can be told from an unchanged one later; nothing reads it yet, and
    -- re-evaluation is not implemented.
    filter_version TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (provider_key, source_job_id)
);

CREATE INDEX IF NOT EXISTS seen_jobs_last_seen ON seen_jobs(last_seen);
CREATE INDEX IF NOT EXISTS seen_jobs_decision ON seen_jobs(decision);

INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('005_seen_jobs');
COMMIT;
