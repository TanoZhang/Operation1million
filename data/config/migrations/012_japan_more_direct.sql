BEGIN IMMEDIATE;

-- Japan's big employers read directly (the user, 2026-10-23), each board
-- checked that day: sixteen on HRMOS, Hitachi and Subaru on jposting, and
-- three foreign makers whose global boards list Japan: Infineon (Eightfold),
-- Analog Devices and Microchip (Workday).
INSERT INTO companies (company_key, name) VALUES
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
ON CONFLICT(company_key) DO UPDATE SET name = excluded.name;

INSERT OR IGNORE INTO company_sources (
    source_instance_id, company_key, provider_key, provider_identifier,
    access_url, instance_fields_json, enabled, status
) VALUES
    ('hrmos:advantest', 'advantest', 'hrmos', 'advantest',
     'https://hrmos.co/pages/advantest/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:tel', 'tokyo_electron', 'hrmos', 'tel',
     'https://hrmos.co/pages/tel/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:canon', 'canon', 'hrmos', 'canon',
     'https://hrmos.co/pages/canon/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:kyocera', 'kyocera', 'hrmos', 'kyocera',
     'https://hrmos.co/pages/kyocera/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:tdk', 'tdk', 'hrmos', 'tdk',
     'https://hrmos.co/pages/tdk/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:epson', 'epson', 'hrmos', 'epson',
     'https://hrmos.co/pages/epson/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:panasonic', 'panasonic', 'hrmos', 'panasonic',
     'https://hrmos.co/pages/panasonic/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:sharp', 'sharp', 'hrmos', 'sharp',
     'https://hrmos.co/pages/sharp/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:horiba', 'horiba', 'hrmos', 'horiba',
     'https://hrmos.co/pages/horiba/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:nidec', 'nidec', 'hrmos', 'nidec',
     'https://hrmos.co/pages/nidec/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:macnica', 'macnica', 'hrmos', 'macnica',
     'https://hrmos.co/pages/macnica/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:ablic', 'ablic', 'hrmos', 'ablic',
     'https://hrmos.co/pages/ablic/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:kmi-career', 'konica_minolta', 'hrmos', 'kmi-career',
     'https://hrmos.co/pages/kmi-career/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:aisincareer', 'aisin', 'hrmos', 'aisincareer',
     'https://hrmos.co/pages/aisincareer/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:toppan', 'toppan', 'hrmos', 'toppan',
     'https://hrmos.co/pages/toppan/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('hrmos:fujielectric', 'fuji_electric', 'hrmos', 'fujielectric',
     'https://hrmos.co/pages/fujielectric/jobs', '{"country":"Japan"}', 1, 'verified'),
    ('jposting:hitachi', 'hitachi', 'jposting', 'hitachi',
     'https://jscudp.jcareers.com/hitachi/u/jobs.phtml',
     '{"board":"https://hitachi.jposting.net/joblist/","detail":"https://hitachi.jposting.net/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}', 1, 'verified'),
    ('jposting:subaru', 'subaru', 'jposting', 'subaru',
     'https://jsdp01.jcareers.com/subaru/u/jobs.phtml',
     '{"board":"https://jsd.jposting.net/subaru/","detail":"https://js01.jposting.net/subaru/u/job.phtml?job_code=","encoding":"euc-jp","country":"Japan"}', 1, 'verified'),
    ('eightfold:jobs.infineon.com', 'infineon', 'eightfold', 'jobs.infineon.com',
     'https://jobs.infineon.com/api/pcsx/search?domain=infineon.com&query=&location=',
     '{"career_domain":"jobs.infineon.com","pcsx_domain":"infineon.com"}', 1, 'verified'),
    ('workday:analogdevices:External', 'analog_devices', 'workday', 'External',
     'https://analogdevices.wd1.myworkdayjobs.com/External',
     '{"tenant":"analogdevices","workday_host":"wd1","site":"External"}', 1, 'verified'),
    ('workday:microchiphr:External', 'microchip', 'workday', 'External',
     'https://microchiphr.wd5.myworkdayjobs.com/External',
     '{"tenant":"microchiphr","workday_host":"wd5","site":"External"}', 1, 'verified');

INSERT OR IGNORE INTO catalog_migrations (migration_key)
VALUES ('012_japan_more_direct');

COMMIT;
