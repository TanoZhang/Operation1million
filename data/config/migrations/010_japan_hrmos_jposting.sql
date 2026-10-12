BEGIN IMMEDIATE;

-- More of Japan's chip boards (the user, 2026-10-11): Toshiba (with Device &
-- Storage) on HRMOS; Kioxia and Sony Semiconductor Manufacturing on jposting.
INSERT INTO companies (company_key, name) VALUES
    ('toshiba', 'Toshiba'),
    ('kioxia', 'Kioxia'),
    ('sony_semiconductor_manufacturing', 'Sony Semiconductor Manufacturing')
ON CONFLICT(company_key) DO UPDATE SET name = excluded.name;

INSERT OR IGNORE INTO company_sources (
    source_instance_id, company_key, provider_key, provider_identifier,
    access_url, instance_fields_json, enabled, status
) VALUES
    ('hrmos:toshiba', 'toshiba', 'hrmos', 'toshiba',
     'https://hrmos.co/pages/toshiba/jobs',
     '{"country":"Japan"}', 1, 'verified'),
    ('jposting:kioxia', 'kioxia', 'jposting', 'kioxia',
     'https://jscudp.jcareers.com/kioxia/u/jobs.phtml',
     '{"board":"https://kioxia.jposting.net/joblist/","detail":"https://kioxia.jposting.net/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}', 1, 'verified'),
    ('jposting:sonyck', 'sony_semiconductor_manufacturing', 'jposting', 'sonyck',
     'https://jsdp03.jcareers.com/sonyck/u/sck/jobs.phtml',
     '{"board":"https://jsd.jposting.net/sonyck/","detail":"https://js03.jposting.net/sonyck/u/sck/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}', 1, 'verified');

INSERT OR IGNORE INTO catalog_migrations (migration_key)
VALUES ('010_japan_hrmos_jposting');

COMMIT;
