PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS enabled_company_search_sources;
DROP TABLE IF EXISTS company_search_sources;

CREATE TABLE IF NOT EXISTS companies (
    company_key TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_sources (
    source_instance_id TEXT PRIMARY KEY,
    company_key TEXT NOT NULL REFERENCES companies(company_key) ON UPDATE CASCADE ON DELETE CASCADE,
    provider_key TEXT NOT NULL,
    provider_identifier TEXT NOT NULL,
    access_url TEXT NOT NULL,
    instance_fields_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'failed', 'disabled')),
    UNIQUE (company_key, provider_key, provider_identifier)
);

CREATE TABLE IF NOT EXISTS company_direct_sources (
    direct_source_id TEXT PRIMARY KEY,
    company_key TEXT NOT NULL REFERENCES companies(company_key) ON UPDATE CASCADE ON DELETE CASCADE,
    provider_key TEXT NOT NULL,
    provider_identifier TEXT NOT NULL,
    access_url TEXT NOT NULL,
    access_url_template TEXT NOT NULL,
    keyword_parameter TEXT,
    location_parameter TEXT,
    instance_fields_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'failed', 'disabled')),
    UNIQUE (company_key, provider_key, provider_identifier)
);

CREATE INDEX IF NOT EXISTS idx_company_sources_provider
    ON company_sources (provider_key, enabled);

CREATE INDEX IF NOT EXISTS idx_company_direct_sources_provider
    ON company_direct_sources (provider_key, enabled);

CREATE VIEW IF NOT EXISTS enabled_company_sources AS
SELECT
    s.source_instance_id,
    c.name AS company_name,
    s.provider_key,
    s.provider_identifier,
    s.access_url
FROM company_sources AS s
JOIN companies AS c ON c.company_key = s.company_key
WHERE s.enabled = 1;

CREATE VIEW IF NOT EXISTS enabled_company_direct_sources AS
SELECT
    s.direct_source_id,
    c.name AS company_name,
    s.provider_key,
    s.provider_identifier,
    s.access_url,
    s.access_url_template,
    s.keyword_parameter,
    s.location_parameter
FROM company_direct_sources AS s
JOIN companies AS c ON c.company_key = s.company_key
WHERE s.enabled = 1;

INSERT INTO companies (company_key, name)
VALUES
    ('amd', 'Advanced Micro Devices, Inc.'),
    ('altera', 'Altera Corporation'),
    ('amazon', 'Amazon.com, Inc.'),
    ('ambarella', 'Ambarella, Inc.'),
    ('apple', 'Apple Inc.'),
    ('arm', 'Arm, Inc.'),
    ('astera_labs', 'Astera Labs, Inc.'),
    ('broadcom', 'Broadcom Inc.'),
    ('cadence', 'Cadence Design Systems, Inc.'),
    ('cerebras', 'Cerebras Systems Inc.'),
    ('cisco', 'Cisco Systems, Inc.'),
    ('credo_technology', 'Credo Technology Group Holding Ltd'),
    ('etched', 'Etched.ai, Inc.'),
    ('google', 'Google LLC'),
    ('intel', 'Intel Corporation'),
    ('lattice_semiconductor', 'Lattice Semiconductor Corporation'),
    ('lightmatter', 'Lightmatter, Inc.'),
    ('marvell', 'Marvell Technology, Inc.'),
    ('matx', 'MATX'),
    ('micron', 'Micron Technology, Inc.'),
    ('microsoft', 'Microsoft Corporation'),
    ('nxp', 'NXP USA, Inc.'),
    ('nvidia', 'NVIDIA'),
    ('qualcomm', 'QUALCOMM Incorporated'),
    ('rambus', 'Rambus Inc.'),
    ('renesas', 'Renesas Electronics America, Inc.'),
    ('rivos', 'Rivos Inc.'),
    ('samsung_semiconductor', 'Samsung Semiconductor, Inc.'),
    ('sandisk', 'SanDisk'),
    ('sifive', 'SiFive, Inc.'),
    ('silicon_labs', 'Silicon Laboratories Inc.'),
    ('sk_hynix_america', 'SK hynix America Inc.'),
    ('synopsys', 'Synopsys, Inc.'),
    ('tenstorrent', 'Tenstorrent Inc.'),
    ('teradyne', 'Teradyne, Inc.'),
    ('texas_instruments', 'Texas Instruments Incorporated'),
    ('ventana_micro', 'Ventana Micro Systems Inc.')
ON CONFLICT(company_key) DO UPDATE SET
    name = excluded.name;

DELETE FROM companies
WHERE company_key IN (
    'ampere_computing',
    'bytedance',
    'mediatek',
    'meta',
    'tesla',
    'advantest',
    'maxlinear',
    'omnivision',
    'infineon',
    'achronix',
    'nexperia',
    'nokia',
    'semtech',
    'onsemi',
    'akeana',
    'microchip_technology',
    'psiquantum',
    'analog_devices',
    'celestica',
    'tsmc'
);

DELETE FROM company_sources
WHERE source_instance_id IN (
    'greenhouse:matx',
    'amazon_jobs:amazon',
    'apple_jobs:apple',
    'google_jobs:google',
    'ti_careers:texas_instruments'
);

INSERT INTO company_sources (
    source_instance_id,
    company_key,
    provider_key,
    provider_identifier,
    access_url,
    instance_fields_json,
    enabled,
    status
) VALUES (
    'icims:careers-amd',
    'amd',
    'icims',
    'careers-amd',
    'https://careers.amd.com/api/jobs?sortBy=relevance&descending=false&internal=false',
    '{"portal_subdomain":"careers-amd"}',
    1,
    'pending'
),
(
    'workday:altera:Altera',
    'altera',
    'workday',
    'Altera',
    'https://altera.wd1.myworkdayjobs.com/Altera',
    '{"tenant":"altera","workday_host":"wd1","site":"Altera"}',
    1,
    'verified'
),
(
    'workday:ambarella:Ambarella',
    'ambarella',
    'workday',
    'Ambarella',
    'https://ambarella.wd108.myworkdayjobs.com/Ambarella',
    '{"tenant":"ambarella","workday_host":"wd108","site":"Ambarella"}',
    1,
    'verified'
),
(
    'talentbrew:careers.arm.com',
    'arm',
    'talentbrew',
    'careers.arm.com',
    'https://careers.arm.com/search-jobs',
    '{"career_domain":"careers.arm.com","search_path":"search-jobs","cname":"careers-arm-com.talentbrew.com"}',
    1,
    'pending'
),
(
    'greenhouse:asteralabs',
    'astera_labs',
    'greenhouse',
    'asteralabs',
    'https://boards-api.greenhouse.io/v1/boards/asteralabs/jobs',
    '{"board_token":"asteralabs"}',
    1,
    'verified'
),
(
    'workday:broadcom:External_Career',
    'broadcom',
    'workday',
    'External_Career',
    'https://broadcom.wd1.myworkdayjobs.com/External_Career',
    '{"tenant":"broadcom","workday_host":"wd1","site":"External_Career"}',
    1,
    'verified'
),
(
    'workday:cadence:External_Careers',
    'cadence',
    'workday',
    'External_Careers',
    'https://cadence.wd1.myworkdayjobs.com/External_Careers',
    '{"tenant":"cadence","workday_host":"wd1","site":"External_Careers"}',
    1,
    'verified'
),
(
    'ashby:cerebras',
    'cerebras',
    'ashby',
    'cerebras',
    'https://api.ashbyhq.com/posting-api/job-board/cerebras?includeCompensation=false',
    '{"job_board_name":"cerebras"}',
    1,
    'verified'
),
(
    'phenom:careers.cisco.com',
    'cisco',
    'phenom',
    'careers.cisco.com',
    'https://careers.cisco.com/widgets',
    '{"career_domain":"careers.cisco.com","locale_path":"global/en","locale":"en_global","cname":"cisco.phenompeople.net"}',
    1,
    'pending'
),
(
    'hibob:credo',
    'credo_technology',
    'hibob',
    'credo',
    'https://credo.careers.hibob.com/jobs',
    '{"subdomain":"credo"}',
    1,
    'pending'
),
(
    'ashby:etched',
    'etched',
    'ashby',
    'etched',
    'https://api.ashbyhq.com/posting-api/job-board/etched?includeCompensation=false',
    '{"job_board_name":"etched"}',
    1,
    'verified'
),
(
    'workday:intel:External',
    'intel',
    'workday',
    'External',
    'https://intel.wd1.myworkdayjobs.com/en-US/External',
    '{"tenant":"intel","workday_host":"wd1","site":"External","locale":"en-US"}',
    1,
    'verified'
),
(
    'workday:latticesemi:latticesemiconductorscareers',
    'lattice_semiconductor',
    'workday',
    'latticesemiconductorscareers',
    'https://latticesemi.wd5.myworkdayjobs.com/latticesemiconductorscareers',
    '{"tenant":"latticesemi","workday_host":"wd5","site":"latticesemiconductorscareers"}',
    1,
    'verified'
),
(
    'greenhouse:lightmatter',
    'lightmatter',
    'greenhouse',
    'lightmatter',
    'https://boards-api.greenhouse.io/v1/boards/lightmatter/jobs',
    '{"board_token":"lightmatter"}',
    1,
    'verified'
),
(
    'workday:marvell:MarvellCareers',
    'marvell',
    'workday',
    'MarvellCareers',
    'https://marvell.wd1.myworkdayjobs.com/MarvellCareers',
    '{"tenant":"marvell","workday_host":"wd1","site":"MarvellCareers"}',
    1,
    'verified'
),
(
    'ashby:matx',
    'matx',
    'ashby',
    'matx',
    'https://api.ashbyhq.com/posting-api/job-board/matx',
    '{"job_board_name":"matx"}',
    1,
    'verified'
),
(
    'eightfold:careers.micron.com',
    'micron',
    'eightfold',
    'careers.micron.com',
    'https://careers.micron.com/api/pcsx/search?domain=micron.com&query=&location=',
    '{"career_domain":"careers.micron.com"}',
    1,
    'pending'
),
(
    'workday:nxp:careers',
    'nxp',
    'workday',
    'careers',
    'https://nxp.wd3.myworkdayjobs.com/careers',
    '{"tenant":"nxp","workday_host":"wd3","site":"careers"}',
    1,
    'verified'
),
(
    'workday:nvidia:NVIDIAExternalCareerSite',
    'nvidia',
    'workday',
    'NVIDIAExternalCareerSite',
    'https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite',
    '{"tenant":"nvidia","workday_host":"wd5","site":"NVIDIAExternalCareerSite","locale":"en-US"}',
    1,
    'verified'
),
(
    'eightfold:careers.qualcomm.com',
    'qualcomm',
    'eightfold',
    'careers.qualcomm.com',
    'https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com&query=&location=',
    '{"career_domain":"careers.qualcomm.com"}',
    1,
    'pending'
),
(
    'icims:careers-rambus',
    'rambus',
    'icims',
    'careers-rambus',
    'https://careers-rambus.icims.com/jobs/search?ss=1',
    '{"portal_subdomain":"careers-rambus"}',
    1,
    'pending'
),
(
    'workday:sec:Samsung_Careers',
    'samsung_semiconductor',
    'workday',
    'Samsung_Careers',
    'https://sec.wd3.myworkdayjobs.com/Samsung_Careers',
    '{"tenant":"sec","workday_host":"wd3","site":"Samsung_Careers"}',
    1,
    'verified'
),
(
    'smartrecruiters:Sandisk',
    'sandisk',
    'smartrecruiters',
    'Sandisk',
    'https://api.smartrecruiters.com/v1/companies/Sandisk/postings',
    '{"company_slug":"Sandisk"}',
    1,
    'verified'
),
(
    'workday:sifive:sifivecareers',
    'sifive',
    'workday',
    'sifivecareers',
    'https://sifive.wd1.myworkdayjobs.com/sifivecareers',
    '{"tenant":"sifive","workday_host":"wd1","site":"sifivecareers"}',
    1,
    'verified'
),
(
    'workday:silabs:SiliconLabsCareers',
    'silicon_labs',
    'workday',
    'SiliconLabsCareers',
    'https://silabs.wd1.myworkdayjobs.com/SiliconLabsCareers',
    '{"tenant":"silabs","workday_host":"wd1","site":"SiliconLabsCareers"}',
    1,
    'verified'
),
(
    'greenhouse:skhynixamerica',
    'sk_hynix_america',
    'greenhouse',
    'skhynixamerica',
    'https://boards-api.greenhouse.io/v1/boards/skhynixamerica/jobs',
    '{"board_token":"skhynixamerica"}',
    1,
    'verified'
),
(
    'avature:careers.synopsys.com',
    'synopsys',
    'avature',
    'careers.synopsys.com',
    'https://careers.synopsys.com/search-jobs',
    '{"career_domain":"careers.synopsys.com","search_path":"search-jobs","application_domain":"synopsys.avature.net"}',
    1,
    'pending'
),
(
    'greenhouse:tenstorrent',
    'tenstorrent',
    'greenhouse',
    'tenstorrent',
    'https://boards-api.greenhouse.io/v1/boards/tenstorrent/jobs',
    '{"board_token":"tenstorrent"}',
    1,
    'verified'
),
(
    'jobs2web:jobs.teradyne.com',
    'teradyne',
    'jobs2web',
    'jobs.teradyne.com',
    'https://jobs.teradyne.com/search/',
    '{"career_domain":"jobs.teradyne.com","query":"","q2":"","title":"","location":"","department":"","facility":""}',
    1,
    'pending'
),
(
    'jobvite:ventanamicro',
    'ventana_micro',
    'jobvite',
    'ventanamicro',
    'https://jobs.jobvite.com/ventanamicro/',
    '{"company_slug":"ventanamicro"}',
    1,
    'pending'
)
ON CONFLICT(source_instance_id) DO UPDATE SET
    company_key = excluded.company_key,
    provider_key = excluded.provider_key,
    provider_identifier = excluded.provider_identifier,
    access_url = excluded.access_url,
    instance_fields_json = excluded.instance_fields_json,
    enabled = excluded.enabled,
    status = excluded.status;

INSERT INTO company_direct_sources (
    direct_source_id,
    company_key,
    provider_key,
    provider_identifier,
    access_url,
    access_url_template,
    keyword_parameter,
    location_parameter,
    instance_fields_json,
    enabled,
    status
) VALUES (
    'amazon_jobs:amazon',
    'amazon',
    'amazon_jobs',
    'amazon',
    'https://www.amazon.jobs/en/search?base_query=&loc_query=',
    'https://www.amazon.jobs/en/search?base_query={keyword}&loc_query={location}',
    'base_query',
    'loc_query',
    '{"locale":"en"}',
    1,
    'pending'
),
(
    'apple_jobs:apple',
    'apple',
    'apple_jobs',
    'apple',
    'https://jobs.apple.com/en-us/search?location=united-states-USA',
    'https://jobs.apple.com/en-us/search?search={keyword}&location={location}',
    'search',
    'location',
    '{"locale":"en-us","location":"united-states-USA"}',
    1,
    'pending'
),
(
    'google_jobs:google',
    'google',
    'google_jobs',
    'google',
    'https://www.google.com/about/careers/applications/jobs/results',
    'https://www.google.com/about/careers/applications/jobs/results/?q={keyword}&location={location}',
    'q',
    'location',
    '{}',
    1,
    'pending'
),
(
    'microsoft_careers:microsoft',
    'microsoft',
    'eightfold',
    'apply.careers.microsoft.com',
    'https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=&location=',
    'https://apply.careers.microsoft.com/careers?query={keyword}&location={location}&start={start}',
    'query',
    'location',
    '{"career_domain":"apply.careers.microsoft.com","start":"0"}',
    1,
    'pending'
),
(
    'renesas_careers:renesas',
    'renesas',
    'renesas_careers',
    'jobs.renesas.com',
    'https://jobs.renesas.com/vacanciessitemap.xml',
    'https://jobs.renesas.com/vacanciessitemap.xml',
    NULL,
    NULL,
    '{"career_domain":"jobs.renesas.com","path":"vacanciessitemap.xml"}',
    1,
    'pending'
),
(
    'uplers_company_profile:rivos',
    'rivos',
    'uplers_company_profile',
    'rivos-inc-4535',
    'https://www.uplers.com/company/rivos-inc-4535',
    'https://www.uplers.com/company/rivos-inc-4535',
    NULL,
    NULL,
    '{"company_slug":"rivos-inc","company_id":"4535","source_domain":"www.uplers.com"}',
    1,
    'pending'
),
(
    'ti_careers:texas_instruments',
    'texas_instruments',
    'ti_careers',
    'careers.ti.com',
    'https://careers.ti.com/en/sites/CX/jobs?mode=location',
    'https://careers.ti.com/en/sites/CX/jobs?mode=location',
    NULL,
    NULL,
    '{"career_domain":"careers.ti.com","locale":"en","site":"CX","mode":"location"}',
    1,
    'pending'
)
ON CONFLICT(direct_source_id) DO UPDATE SET
    company_key = excluded.company_key,
    provider_key = excluded.provider_key,
    provider_identifier = excluded.provider_identifier,
    access_url = excluded.access_url,
    access_url_template = excluded.access_url_template,
    keyword_parameter = excluded.keyword_parameter,
    location_parameter = excluded.location_parameter,
    instance_fields_json = excluded.instance_fields_json,
    enabled = excluded.enabled,
    status = excluded.status;

-- Search templates only. Execution history belongs to company/query runs.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS catalog_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS search_queries (
    query_key TEXT PRIMARY KEY CHECK(length(trim(query_key)) > 0),
    keyword TEXT NOT NULL CHECK(length(trim(keyword)) > 0),
    location TEXT NOT NULL DEFAULT 'United States' CHECK(length(trim(location)) > 0),
    country TEXT NOT NULL DEFAULT 'us' CHECK(length(country)=2 AND country=lower(country)),
    tier INTEGER NOT NULL DEFAULT 1 CHECK(tier IN (1, 2)),
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(keyword COLLATE NOCASE, location COLLATE NOCASE, country)
);
CREATE TRIGGER IF NOT EXISTS search_queries_updated
AFTER UPDATE OF keyword, location, country, tier, sort_order, enabled, notes ON search_queries
BEGIN
    UPDATE search_queries SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE query_key=NEW.query_key;
END;
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'electrical_engineer', 'electrical engineer', 1, 0 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'hardware_engineer', 'hardware engineer', 1, 1 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'asic_design_engineer', 'ASIC design engineer', 1, 2 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'rtl_design_engineer', 'RTL design engineer', 1, 3 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'design_verification_engineer', 'design verification engineer', 1, 4 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'physical_design_engineer', 'physical design engineer', 1, 5 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'analog_design_engineer', 'analog design engineer', 1, 6 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'mixed_signal_design_engineer', 'mixed-signal design engineer', 1, 7 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'fpga_engineer', 'FPGA engineer', 1, 8 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'soc_design_engineer', 'SoC design engineer', 1, 9 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'silicon_validation_engineer', 'silicon validation engineer', 2, 10 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'signal_integrity_engineer', 'signal integrity engineer', 2, 11 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'power_electronics_engineer', 'power electronics engineer', 2, 12 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'rf_engineer', 'RF engineer', 2, 13 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'pcb_design_engineer', 'PCB design engineer', 2, 14 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'embedded_hardware_engineer', 'embedded hardware engineer', 2, 15 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'cpu_design_engineer', 'CPU design engineer', 2, 16 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'memory_design_engineer', 'memory design engineer', 2, 17 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('001_search_queries');
COMMIT;
