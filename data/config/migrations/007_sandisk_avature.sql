BEGIN IMMEDIATE;

INSERT OR IGNORE INTO company_sources (
    source_instance_id, company_key, provider_key, provider_identifier,
    access_url, instance_fields_json, enabled, status
) VALUES (
    'avature:avature.sandisk.com', 'sandisk', 'avature',
    'avature.sandisk.com',
    'https://avature.sandisk.com/Careers/sitemap.xml',
    '{"sitemap_job_path":"/Careers/JobDetail/"}', 1, 'verified'
);

INSERT OR IGNORE INTO catalog_migrations (migration_key)
VALUES ('007_sandisk_avature');

COMMIT;
