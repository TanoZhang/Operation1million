BEGIN IMMEDIATE;

-- Japan's chip boards, read directly (the user, 2026-10-11): EdgeCortix on
-- BambooHR, Preferred Networks on Talentio, TSMC on Avature.
INSERT INTO companies (company_key, name) VALUES
    ('edgecortix', 'EdgeCortix'),
    ('preferred_networks', 'Preferred Networks'),
    ('tsmc', 'Taiwan Semiconductor Manufacturing Company')
ON CONFLICT(company_key) DO UPDATE SET name = excluded.name;

INSERT OR IGNORE INTO company_sources (
    source_instance_id, company_key, provider_key, provider_identifier,
    access_url, instance_fields_json, enabled, status
) VALUES
    ('bamboohr:edgecortix', 'edgecortix', 'bamboohr', 'edgecortix',
     'https://edgecortix.bamboohr.com/careers',
     '{"subdomain":"edgecortix"}', 1, 'verified'),
    ('talentio:preferred', 'preferred_networks', 'talentio', 'preferred',
     'https://open.talentio.com/r/1/c/preferred',
     '{"homes":["https://open.talentio.com/r/1/c/preferred/homes/4678","https://open.talentio.com/r/1/c/preferred/homes/4679"],"location":"Tokyo, Japan"}', 1, 'verified'),
    ('avature:careers.tsmc.com', 'tsmc', 'avature', 'careers.tsmc.com',
     'https://careers.tsmc.com/en_US/careers/sitemap.xml',
     '{"sitemap_job_path":"/en_US/careers/JobDetail/","max_pages":1200}', 1, 'verified');

INSERT OR IGNORE INTO catalog_migrations (migration_key)
VALUES ('009_japan_direct_sources');

COMMIT;
