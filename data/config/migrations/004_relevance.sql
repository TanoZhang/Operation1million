-- Relevance is scored once when a posting is stored, not on every read.
-- Scoring a whole board at read time means tens of thousands of postings times
-- a hundred patterns, which is seconds of work to answer one question.
BEGIN IMMEDIATE;
ALTER TABLE jobs ADD COLUMN relevance INTEGER;
CREATE INDEX IF NOT EXISTS jobs_relevance ON jobs(relevance DESC, posted_at DESC);
INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('004_relevance');
COMMIT;
