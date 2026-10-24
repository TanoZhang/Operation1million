BEGIN IMMEDIATE;

-- More of Japan's big employers (the user, 2026-10-23: "日本 继续expand"):
-- Astemo and HOYA on HRMOS, Omron's public axol board, Ebara and Hitachi
-- Systems on jposting's HTML list, ArkEdge Space and Nintendo Systems on HERP;
-- Tokyo Electron's own Workday, Monolithic Power Systems and Lumentum, whose
-- Workday boards list Japan.
INSERT INTO companies (company_key, name) VALUES
    ('astemo', 'Astemo'),
    ('hoya', 'HOYA'),
    ('omron', 'Omron Corporation'),
    ('ebara', 'Ebara'),
    ('hitachi_systems', 'Hitachi Systems'),
    ('arkedge_space', 'ArkEdge Space'),
    ('nintendo_systems', 'Nintendo Systems'),
    ('monolithic_power', 'Monolithic Power Systems'),
    ('lumentum', 'Lumentum')
ON CONFLICT(company_key) DO UPDATE SET name = excluded.name;

INSERT OR IGNORE INTO company_sources (
    source_instance_id, company_key, provider_key, provider_identifier,
    access_url, instance_fields_json, enabled, status
) VALUES
    ('hrmos:astemo', 'astemo', 'hrmos', 'astemo',
     'https://hrmos.co/pages/astemo/jobs',
     '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:hoya', 'hoya', 'hrmos', 'hoya',
     'https://hrmos.co/pages/hoya/jobs',
     '{"country":"Japan"}', 1, 'verified'),
    ('axol:omron', 'omron', 'axol', 'omron',
     'https://job.axol.jp/qd/c/omron/public/job/list',
     '{"country":"Japan"}', 1, 'verified'),
    ('jposting:ebara', 'ebara', 'jposting', 'ebara',
     'https://ebara.jposting.net/u/jobs/job.phtml',
     '{"list":"html","detail":"https://ebara.jposting.net/u/jobs/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}', 1, 'verified'),
    ('jposting:hitachi-systems', 'hitachi_systems', 'jposting', 'hitachi-systems',
     'https://js03.jposting.net/hitachi-systems/u/job.phtml',
     '{"list":"html","detail":"https://js03.jposting.net/hitachi-systems/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}', 1, 'verified'),
    ('herp:arkedgespace', 'arkedge_space', 'herp', 'arkedgespace',
     'https://herp.careers/v1/arkedgespace',
     '{"country":"Japan"}', 1, 'verified'),
    ('herp:nscareer', 'nintendo_systems', 'herp', 'nscareer',
     'https://herp.careers/v1/nscareer',
     '{"country":"Japan"}', 1, 'verified'),
    ('workday:tel:TEL-Careers', 'tokyo_electron', 'workday', 'TEL-Careers',
     'https://tel.wd3.myworkdayjobs.com/TEL-Careers',
     '{"tenant":"tel","workday_host":"wd3","site":"TEL-Careers"}', 1, 'verified'),
    ('workday:monolithicpower:MPS_Careers', 'monolithic_power', 'workday', 'MPS_Careers',
     'https://monolithicpower.wd12.myworkdayjobs.com/MPS_Careers',
     '{"tenant":"monolithicpower","workday_host":"wd12","site":"MPS_Careers"}', 1, 'verified'),
    ('workday:lumentum:LITE', 'lumentum', 'workday', 'LITE',
     'https://lumentum.wd5.myworkdayjobs.com/LITE',
     '{"tenant":"lumentum","workday_host":"wd5","site":"LITE"}', 1, 'verified');

INSERT OR IGNORE INTO catalog_migrations (migration_key)
VALUES ('014_japan_more_boards');

COMMIT;
