-- Postings by requisition. Each pass of a direct board asks, once per
-- requisition, which other URLs carry the same provider id; with only
-- (company_key, closed_at) indexed each question scanned the board's open
-- rows, so a pass grew with the square of the board (external review,
-- 2026-10-16: 8,000 rows took 10 s, 0.8 s with this index).
BEGIN IMMEDIATE;
CREATE INDEX IF NOT EXISTS jobs_requisition ON jobs(provider_key, source_job_id);
INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('011_jobs_requisition');
COMMIT;
