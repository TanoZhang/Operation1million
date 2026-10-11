BEGIN IMMEDIATE;

UPDATE company_direct_sources
SET instance_fields_json = '{"locale":"en","max_jobs":30000}'
WHERE direct_source_id = 'amazon_jobs:amazon';

INSERT OR IGNORE INTO catalog_migrations (migration_key)
VALUES ('008_amazon_partition');

COMMIT;
