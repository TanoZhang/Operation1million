-- When a source was last read in full.
--
-- An incremental pass on a newest-first board stops at the first posting
-- published before its watermark. That is only safe for a posting whose
-- publication date moves when it appears or changes, and providers do not
-- promise it: a posting can reach the index days after its stated date, and an
-- edited one keeps the date it was first published under. Each such posting is
-- invisible to every incremental pass that follows. A full pass at a bounded
-- interval is what finds them, and it needs to know when the last one was --
-- which `last_success_at` cannot say, because every successful incremental
-- pass moves it.
BEGIN IMMEDIATE;

ALTER TABLE source_state ADD COLUMN last_full_at TEXT;

INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('006_source_full_pass');
COMMIT;
