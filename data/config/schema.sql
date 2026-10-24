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
    ('anthropic', 'Anthropic'),
    ('applied_materials', 'Applied Materials, Inc.'),
    ('d_matrix', 'd-Matrix'),
    ('globalfoundries', 'GlobalFoundries'),
    ('kla', 'KLA Corporation'),
    ('lam_research', 'Lam Research Corporation'),
    ('openai', 'OpenAI'),
    ('quadric', 'Quadric'),
    ('sambanova', 'SambaNova Systems'),
    ('xai', 'xAI'),
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
    -- Japan's chip boards, read directly (the user, 2026-10-11). TSMC was
    -- removed on 2026-09-16 and is back for its Yokohama design centre.
    ('edgecortix', 'EdgeCortix'),
    ('preferred_networks', 'Preferred Networks'),
    ('tsmc', 'Taiwan Semiconductor Manufacturing Company'),
    ('toshiba', 'Toshiba'),
    ('kioxia', 'Kioxia'),
    ('sony_semiconductor_manufacturing', 'Sony Semiconductor Manufacturing'),
    -- Japan's big employers read directly (2026-10-23). Advantest, Infineon and
    -- Analog Devices were removed on 2026-09-16 and are back for their Japan boards.
    ('advantest', 'Advantest'),
    ('tokyo_electron', 'Tokyo Electron'),
    ('canon', 'Canon'),
    ('kyocera', 'Kyocera'),
    ('tdk', 'TDK'),
    ('epson', 'Seiko Epson'),
    ('panasonic', 'Panasonic'),
    ('sharp', 'Sharp'),
    ('horiba', 'Horiba'),
    ('nidec', 'Nidec'),
    ('macnica', 'Macnica'),
    ('ablic', 'ABLIC'),
    ('konica_minolta', 'Konica Minolta'),
    ('aisin', 'Aisin'),
    ('toppan', 'TOPPAN'),
    ('fuji_electric', 'Fuji Electric'),
    ('hitachi', 'Hitachi'),
    ('subaru', 'Subaru'),
    ('infineon', 'Infineon Technologies'),
    ('analog_devices', 'Analog Devices'),
    ('microchip', 'Microchip Technology')
ON CONFLICT(company_key) DO UPDATE SET
    name = excluded.name;

-- Older catalogs may lack cascading foreign keys on company_sources.
DELETE FROM company_sources WHERE company_key IN ('rambus', 'ventana_micro');
DELETE FROM company_direct_sources WHERE company_key IN ('rambus', 'ventana_micro');

DELETE FROM companies
WHERE company_key IN (
    'ampere_computing',
    'bytedance',
    'mediatek',
    'meta',
    'tesla',
    'maxlinear',
    'omnivision',
    'achronix',
    'nexperia',
    'nokia',
    'semtech',
    'onsemi',
    'akeana',
    'microchip_technology',
    'psiquantum',
    'celestica',
    'rambus',
    'ventana_micro'
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
    'amd_careers',
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
    '{"career_domain":"careers.micron.com","pcsx_domain":"micron.com"}',
    1,
    'pending'
),
-- Added 2026-10-03 at the user's request; each board answered with postings that day.
(
    'greenhouse:anthropic',
    'anthropic',
    'greenhouse',
    'anthropic',
    'https://boards-api.greenhouse.io/v1/boards/anthropic/jobs',
    '{"board_token":"anthropic"}',
    1,
    'verified'
),
(
    'greenhouse:xai',
    'xai',
    'greenhouse',
    'xai',
    'https://boards-api.greenhouse.io/v1/boards/xai/jobs',
    '{"board_token":"xai"}',
    1,
    'verified'
),
(
    'greenhouse:sambanovasystems',
    'sambanova',
    'greenhouse',
    'sambanovasystems',
    'https://boards-api.greenhouse.io/v1/boards/sambanovasystems/jobs',
    '{"board_token":"sambanovasystems"}',
    1,
    'verified'
),
(
    'ashby:openai',
    'openai',
    'ashby',
    'openai',
    'https://api.ashbyhq.com/posting-api/job-board/openai?includeCompensation=false',
    '{"job_board_name":"openai"}',
    1,
    'verified'
),
(
    'ashby:d-matrix',
    'd_matrix',
    'ashby',
    'd-matrix',
    'https://api.ashbyhq.com/posting-api/job-board/d-matrix?includeCompensation=false',
    '{"job_board_name":"d-matrix"}',
    1,
    'verified'
),
(
    'ashby:quadric',
    'quadric',
    'ashby',
    'quadric',
    'https://api.ashbyhq.com/posting-api/job-board/quadric?includeCompensation=false',
    '{"job_board_name":"quadric"}',
    1,
    'verified'
),
(
    'workday:kla:Search',
    'kla',
    'workday',
    'Search',
    'https://kla.wd1.myworkdayjobs.com/Search',
    '{"tenant":"kla","workday_host":"wd1","site":"Search"}',
    1,
    'verified'
),
(
    'workday:amat:External',
    'applied_materials',
    'workday',
    'External',
    'https://amat.wd1.myworkdayjobs.com/External',
    '{"tenant":"amat","workday_host":"wd1","site":"External"}',
    1,
    'verified'
),
(
    'workday:globalfoundries:External',
    'globalfoundries',
    'workday',
    'External',
    'https://globalfoundries.wd1.myworkdayjobs.com/External',
    '{"tenant":"globalfoundries","workday_host":"wd1","site":"External"}',
    1,
    'verified'
),
(
    'eightfold:careers.lamresearch.com',
    'lam_research',
    'eightfold',
    'careers.lamresearch.com',
    'https://careers.lamresearch.com/api/pcsx/search?domain=lamresearch.com&query=&location=',
    '{"career_domain":"careers.lamresearch.com","pcsx_domain":"lamresearch.com"}',
    1,
    'verified'
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
    '{"career_domain":"careers.qualcomm.com","pcsx_domain":"qualcomm.com"}',
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
    'avature:avature.sandisk.com',
    'sandisk',
    'avature',
    'avature.sandisk.com',
    'https://avature.sandisk.com/Careers/sitemap.xml',
    '{"sitemap_job_path":"/Careers/JobDetail/"}',
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
    'bamboohr:edgecortix',
    'edgecortix',
    'bamboohr',
    'edgecortix',
    'https://edgecortix.bamboohr.com/careers',
    '{"subdomain":"edgecortix"}',
    1,
    'verified'
),
(
    'talentio:preferred',
    'preferred_networks',
    'talentio',
    'preferred',
    'https://open.talentio.com/r/1/c/preferred',
    '{"homes":["https://open.talentio.com/r/1/c/preferred/homes/4678","https://open.talentio.com/r/1/c/preferred/homes/4679"],"location":"Tokyo, Japan"}',
    1,
    'verified'
),
(
    'avature:careers.tsmc.com',
    'tsmc',
    'avature',
    'careers.tsmc.com',
    'https://careers.tsmc.com/en_US/careers/sitemap.xml',
    '{"sitemap_job_path":"/en_US/careers/JobDetail/","max_pages":1200}',
    1,
    'verified'
),
(
    'hrmos:toshiba',
    'toshiba',
    'hrmos',
    'toshiba',
    'https://hrmos.co/pages/toshiba/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'jposting:kioxia',
    'kioxia',
    'jposting',
    'kioxia',
    'https://jscudp.jcareers.com/kioxia/u/jobs.phtml',
    '{"board":"https://kioxia.jposting.net/joblist/","detail":"https://kioxia.jposting.net/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}',
    1,
    'verified'
),
(
    'jposting:sonyck',
    'sony_semiconductor_manufacturing',
    'jposting',
    'sonyck',
    'https://jsdp03.jcareers.com/sonyck/u/sck/jobs.phtml',
    '{"board":"https://jsd.jposting.net/sonyck/","detail":"https://js03.jposting.net/sonyck/u/sck/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:advantest',
    'advantest',
    'hrmos',
    'advantest',
    'https://hrmos.co/pages/advantest/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:tel',
    'tokyo_electron',
    'hrmos',
    'tel',
    'https://hrmos.co/pages/tel/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:canon',
    'canon',
    'hrmos',
    'canon',
    'https://hrmos.co/pages/canon/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:kyocera',
    'kyocera',
    'hrmos',
    'kyocera',
    'https://hrmos.co/pages/kyocera/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:tdk',
    'tdk',
    'hrmos',
    'tdk',
    'https://hrmos.co/pages/tdk/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:epson',
    'epson',
    'hrmos',
    'epson',
    'https://hrmos.co/pages/epson/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:panasonic',
    'panasonic',
    'hrmos',
    'panasonic',
    'https://hrmos.co/pages/panasonic/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:sharp',
    'sharp',
    'hrmos',
    'sharp',
    'https://hrmos.co/pages/sharp/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:horiba',
    'horiba',
    'hrmos',
    'horiba',
    'https://hrmos.co/pages/horiba/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:nidec',
    'nidec',
    'hrmos',
    'nidec',
    'https://hrmos.co/pages/nidec/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:macnica',
    'macnica',
    'hrmos',
    'macnica',
    'https://hrmos.co/pages/macnica/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:ablic',
    'ablic',
    'hrmos',
    'ablic',
    'https://hrmos.co/pages/ablic/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:kmi-career',
    'konica_minolta',
    'hrmos',
    'kmi-career',
    'https://hrmos.co/pages/kmi-career/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:aisincareer',
    'aisin',
    'hrmos',
    'aisincareer',
    'https://hrmos.co/pages/aisincareer/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:toppan',
    'toppan',
    'hrmos',
    'toppan',
    'https://hrmos.co/pages/toppan/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'hrmos:fujielectric',
    'fuji_electric',
    'hrmos',
    'fujielectric',
    'https://hrmos.co/pages/fujielectric/jobs',
    '{"country":"Japan"}',
    1,
    'verified'
),
(
    'jposting:hitachi',
    'hitachi',
    'jposting',
    'hitachi',
    'https://jscudp.jcareers.com/hitachi/u/jobs.phtml',
    '{"board":"https://hitachi.jposting.net/joblist/","detail":"https://hitachi.jposting.net/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}',
    1,
    'verified'
),
(
    'jposting:subaru',
    'subaru',
    'jposting',
    'subaru',
    'https://jsdp01.jcareers.com/subaru/u/jobs.phtml',
    '{"board":"https://jsd.jposting.net/subaru/","detail":"https://js01.jposting.net/subaru/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}',
    1,
    'verified'
),
(
    'eightfold:jobs.infineon.com',
    'infineon',
    'eightfold',
    'jobs.infineon.com',
    'https://jobs.infineon.com/api/pcsx/search?domain=infineon.com&query=&location=',
    '{"career_domain":"jobs.infineon.com","pcsx_domain":"infineon.com"}',
    1,
    'verified'
),
(
    'workday:analogdevices:External',
    'analog_devices',
    'workday',
    'External',
    'https://analogdevices.wd1.myworkdayjobs.com/External',
    '{"tenant":"analogdevices","workday_host":"wd1","site":"External"}',
    1,
    'verified'
),
(
    'workday:microchiphr:External',
    'microchip',
    'workday',
    'External',
    'https://microchiphr.wd5.myworkdayjobs.com/External',
    '{"tenant":"microchiphr","workday_host":"wd5","site":"External"}',
    1,
    'verified'
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
    '{"locale":"en","max_jobs":30000}',
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
    '{"career_domain":"apply.careers.microsoft.com","pcsx_domain":"microsoft.com","start":"0"}',
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

-- Which migrations have run.
CREATE TABLE IF NOT EXISTS catalog_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
