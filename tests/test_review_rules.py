"""Employer policy and publisher noise must not bypass review decisions."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json
import re
import tempfile
import unittest
from unittest import mock

from jobdisco import applications, jsearch, store
from jobdisco.job_text import clean_title


class FilterPolicyTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def matches_keep(self, title):
        return any(re.search(p, title, re.I) for p in self.rules['keep_title_patterns'])

    def test_explicit_seniority_is_hard_rejected_before_keep(self):
        for title in ('Senior RTL Engineer', 'Sr. FPGA Engineer', 'Sr ASIC Engineer',
                      'ASIC Engineer, Sr.', 'SENIOR Design Verification Engineer',
                      'Director of RTL Design', 'FPGA Engineering Manager',
                      # A level, like senior, since 2026-09-22 at the user's request.
                      'Principal RTL Engineer'):
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), 'excluded')
        for title in ('Staff FPGA Engineer', 'SRAM Design Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))
        self.assertEqual(jsearch.rejection_reason({
            'title': 'RTL Engineer', 'raw': {'description': 'Work with Senior engineers and a Manager.'}
        }, self.rules), '')

    def test_unrelated_titles_are_hard_rejected_even_with_trade_evidence(self):
        titles = (
            'Silicon Photonics Engineer', 'Photonic Engineer', 'Photonics Engineer',
            'Optical Engineer', 'Optics Engineer', 'Optoelectronic Engineer',
            'Optoelectronics Engineer', 'Laser Engineer', 'Process Engineer',
            'Semiconductor Process Integration Engineer', 'Semiconductor Process Engineer',
            'Silicon Device Engineer', 'Device Integration Engineer', 'Silicon Yield Engineer',
            'Yield Engineer', 'Fab Engineer', 'Fabrication Engineer', 'Lithography Engineer',
            'Thin Film Engineer', 'Etch Engineer', 'Deposition Engineer',
            'Materials Engineer', 'Materials Scientist', 'Chemical Engineer',
            'Battery Engineer', 'Electrochemical Engineer', 'Electrochemistry Scientist',
            'Mechanical Engineer', 'Thermal Engineer', 'Structural Engineer',
            'Civil Engineer', 'Construction Engineer', 'Manufacturing Engineer',
            'Industrial Engineer', 'FPGA Photonics Engineer',
        )
        for title in titles:
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), 'excluded')

    def test_device_is_only_rejected_as_an_explicit_fab_phrase(self):
        """`device` is not a fab word; the phrases built around it are."""
        for title in ('Semiconductor Device Engineer', 'Device Integration Engineer',
                      'Device Physics Engineer', 'Device Process Engineer',
                      'Device Characterization Engineer', 'Principal Process/Device Engineer',
                      'NAND Cell Device Engineer', 'Foundry Device Engineer',
                      'CMOS Device Integration Team'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.excluded(title, self.rules))
        # Each of these reads as the trade to someone in it, and a bare
        # `device engineer` rule took all of them to reach the fab postings.
        for title in ('Device Validation Engineer', 'Silicon Device Validation Engineer',
                      'Embedded Device Engineer', 'PCIe Device Engineer',
                      'Hardware Device Engineer', 'Device Driver Engineer',
                      'Device Engineer', 'Staff Device Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))

    def test_evidence_titles_use_prose_without_punishing_missing_prose(self):
        """RF uses supplied prose, but absent publisher data is not a rejection."""
        for title in ('RF Engineer', 'RFIC Engineer', 'RF IC Engineer',
                      'Microwave Engineer', 'Antenna Engineer',
                      'RFIC Digital Verification Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules), 'no longer a hard reject')
                self.assertTrue(jsearch.needs_evidence(title, self.rules))
                trade = {'title': title,
                         'raw': {'description': 'RTL ASIC FPGA UVM SystemVerilog ' * 200}}
                self.assertEqual(jsearch.rejection_reason(trade, self.rules), '')
                self.assertEqual(jsearch.rejection_reason(
                    {'title': title, 'raw': {}}, self.rules), '')
                self.assertEqual(jsearch.rejection_reason(
                    {'title': title,
                     'raw': {'description': 'Antenna tuning and spectrum planning.'}},
                    self.rules), 'no_evidence')

    def test_a_repeated_raw_title_is_not_mistaken_for_a_description(self):
        row = {'title': 'RF Engineer', 'raw': {'job_title': 'RF Engineer'}}
        self.assertEqual(jsearch.description_text(row), '')
        self.assertEqual(jsearch.rejection_reason(row, self.rules), '')
        self.assertEqual(jsearch.description_text(
            {'raw': {'skills': [{'name': 'SystemVerilog'}]}}), 'SystemVerilog')

    def test_location_and_employment_metadata_do_not_replace_missing_description(self):
        row = {'title': 'RF Engineer', 'raw': {
            'job_title': 'RF Engineer', 'job_description': None,
            'job_city': 'Austin', 'job_state': 'Texas', 'job_country': 'US',
            'job_employment_type': 'FULLTIME',
            'locations': [{'name': 'Austin, Texas'}]}}
        self.assertEqual(jsearch.description_text(row), '')
        self.assertEqual(jsearch.rejection_reason(row, self.rules), '')

    def test_an_evidence_title_cannot_escape_the_check_through_a_keep(self):
        """The check runs before the keeps, or the name would answer for itself."""
        row = {'title': 'RFIC Digital Design Engineer', 'raw': {'description': 'Short.'}}
        self.assertTrue(self.matches_keep(row['title']))
        self.assertEqual(jsearch.rejection_reason(row, self.rules), 'no_evidence')

    def test_software_survives_when_the_title_names_low_level_work(self):
        for title in ('Embedded Software Engineer', 'Firmware Software Engineer',
                      'Device Driver Software Engineer', 'SoC Software Engineer',
                      'Silicon Validation Software Engineer', 'FPGA Software Engineer',
                      'Hardware Software Co-Design Engineer'):
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), '')
        # Nothing in these names the hardware underneath, so they still go.
        for title in ('Software Engineer', 'Software Engineer, Machine Learning',
                      'Full Stack Software Engineer', 'Software Development Engineer II'):
            with self.subTest(title=title):
                row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM ' * 200}}
                self.assertEqual(jsearch.rejection_reason(row, self.rules), 'title_mismatch')

    def test_target_titles_are_not_hard_rejected(self):
        for title in ('Silicon Validation Engineer', 'Pre-Silicon Validation Engineer',
                      'SoC Validation Engineer', 'Hardware Design Engineer',
                      'FPGA Validation Engineer', 'Embedded FPGA Engineer',
                      'Device Driver Engineer', 'Process Control FPGA Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))

    def test_explicit_titles_keep_without_scoring(self):
        for title in ('RTL Design Engineer', 'ASIC Design Engineer', 'FPGA Engineer',
                      'SoC Design Verification Engineer', 'Digital Design Engineer',
                      'Physical Design Engineer', 'Logic Design Engineer',
                      'Pre-Silicon Verification Engineer', 'Hardware Verification Engineer',
                      'Formal Verification Engineer', 'DFT Engineer', 'VLSI Engineer'):
            with self.subTest(title=title):
                self.assertTrue(self.matches_keep(title))
                with mock.patch.object(jsearch, 'relevance', side_effect=AssertionError('Scoring reached')):
                    self.assertEqual(jsearch.rejection_reason({'title': title}, self.rules), '')

    def test_generic_titles_do_not_bypass_scoring(self):
        for title in ('Silicon Validation Engineer', 'Pre-Silicon Validation Engineer',
                      'Hardware Validation Engineer', 'Test Engineer', 'Semiconductor Engineer',
                      'IC Engineer', 'Embedded Engineer', 'Firmware Engineer',
                      'Digital Marketing Engineer', 'Verification Engineer', 'Formal Engineer',
                      'Silicon Photonics Engineer'):
            with self.subTest(title=title):
                self.assertFalse(self.matches_keep(title))
        row = {'title': 'Silicon Validation Engineer', 'raw': {'description': 'Ordinary duties. ' * 200}}
        with mock.patch.object(jsearch, 'relevance', return_value=(0, [])) as score:
            self.assertEqual(jsearch.rejection_reason(row, self.rules), 'off_domain')
            score.assert_called_once()

    def test_employer_blacklist_precedes_explicit_keeps(self):
        for employer in ('Boeing', 'The Boeing Company', 'Lockheed Martin Corporation',
                         'Northrop Grumman', 'RTX', 'RTX Corporation', 'Raytheon',
                         'L3Harris Technologies', 'General Dynamics', 'BAE Systems',
                         'Leidos', 'CACI International', 'SAIC', 'Amentum', 'Peraton', 'Anduril-1'):
            for title in ('RTL Design Engineer', 'FPGA Engineer', 'ASIC Design Engineer'):
                with self.subTest(employer=employer, title=title):
                    row = {'title': title, 'company_name': employer}
                    self.assertEqual(jsearch.rejection_reason(row, self.rules), 'excluded_employer')

    def test_title_and_employer_patterns_do_not_scan_description(self):
        for employer in ('NVIDIA', 'Analog Devices', 'RTX Labs Research', 'SAIC Motor', 'Peratonics'):
            row = {'title': 'NVIDIA RTX FPGA Engineer', 'company_name': employer,
                   'raw': {'description': 'Boeing RF IC Engineer process device Photonics Engineer'}}
            with self.subTest(employer=employer):
                self.assertEqual(jsearch.rejection_reason(row, self.rules), '')


class SoftBlockTests(unittest.TestCase):
    """Asked for on 2026-09-22: another function's word drops a title unless
    the title also names the trade."""

    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def test_another_functions_word_alone_is_blocked(self):
        for title in ('Power Integrity Engineer', 'Supply Chain Planner', 'Product Engineer',
                      'Manufacturing Engineering Intern', 'Mechanical Design Engineer',
                      'Wireless Power Magnetics Architect', 'Technical Program Management',
                      'Project Management Apprenticeship', 'Business Operations Analyst'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.title_blocked(title, self.rules))

    def test_a_title_that_names_the_trade_is_scored_instead(self):
        for title in ('Low Power Verification Engineer', 'Power-aware RTL Design Engineer',
                      'SoC Product Validation Engineer', 'FPGA Manufacturing Test Engineer',
                      'UVM Verification Engineer, Operations'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.title_blocked(title, self.rules))

    def test_a_function_title_about_hardware_is_kept(self):
        """The first version of this block dropped 38 early-career groups on
        the live queue along with the supply planners it was aimed at."""
        for title in ('AI GPU Power Architect - New College Grad 2026', 'CPU Power Engineer',
                      'Intern - NAND Product Development Engineer', 'Product Validation Intern',
                      'Intern Position (Custom IC Product Group)',
                      'Hardware Products Early Career Rotation Program',
                      'New College Grad - DRAM Product Test Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.title_blocked(title, self.rules))

    def test_a_hardware_word_without_a_role_does_not_rescue(self):
        for title in ('Business Operations Analyst, Processor', 'Supply Chain Planner, Memory'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.title_blocked(title, self.rules))

    def test_the_older_block_is_not_softened(self):
        """Analog and software were the user's own earlier choices, and a
        hardware word never argued them back in."""
        for title in ('Analog IC Design Engineer, Intern', 'GPU Fleet Software Development Engineer'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.title_blocked(title, self.rules))

    def test_principal_is_a_level(self):
        self.assertTrue(jsearch.excluded('Principal Digital Verification Engineer', self.rules))
        # Lead too, asked for the same day; the word, not words that contain it.
        for title in ('Lead Product Validation Engineer', 'Design Verification Tech Lead',
                      'RTL Design Engineer - Team Lead'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.excluded(title, self.rules))
        self.assertTrue(jsearch.excluded('Médico/a del Trabajo, Workplace Health and Safety', self.rules))
        for title in ('Leadership Development Program - Hardware Engineer',
                      'ASIC Engineer, Leading-Edge Nodes'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))
        self.assertFalse(jsearch.excluded('Staff Digital Verification Engineer', self.rules))


class UsPersonTests(unittest.TestCase):
    """Asked for on 2026-09-22: a U.S. citizenship or U.S. person requirement
    is a hard pass. The phrasings are the ones measured in the live index."""

    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def test_the_requirement_is_recognised_however_it_is_put(self):
        for text in ('Must be a U.S. citizen, lawful permanent resident of the U.S., or other U.S. Person.',
                     'Due to applicable export control laws and regulations, candidates must be a '
                     'U.S. citizen or national, U.S. permanent resident (i.e., current Green Card holder)',
                     'This position requires that the candidate selected be a US Citizen.',
                     'applicant must be a (i) U.S. citizen or national, (ii) U.S. lawful, permanent resident',
                     'access to the AWS GovCloud region will be restricted to Amazon employees who are U.S. Citizens.',
                     'US citizenship is required due to potential training delivery on military bases.'):
            with self.subTest(text=text[:50]):
                self.assertTrue(jsearch.us_person_required(text, self.rules))

    def test_what_is_not_a_requirement_is_left_alone(self):
        for text in ('We consider applicants without regard to race, citizenship status or national origin.',
                     'the offer may be contingent upon your citizenship/permanent residency status or '
                     'ability to obtain prior license approval',
                     'Under these laws, U.S. persons (which includes U.S. citizens, lawful permanent '
                     'residents, refugees, and asylees) will be',
                     'Applicants must be authorized to work in the United States.',
                     'We sponsor visas; no U.S. citizenship required.'):
            with self.subTest(text=text[:50]):
                self.assertFalse(jsearch.us_person_required(text, self.rules))

    def test_it_is_a_hard_pass_whatever_the_title(self):
        row = {'title': 'RTL Design Engineer Intern',
               'raw': {'description': 'RTL UVM ASIC. Must be a U.S. citizen or U.S. person.'}}
        self.assertEqual(jsearch.rejection_reason(row, self.rules), 'us_person_required')
        self.assertIn('us_person_required', jsearch.HARD_REJECTIONS)


class TitleTests(unittest.TestCase):
    def test_relative_dates_and_known_location_do_not_change_identity(self):
        role = 'Senior ASIC Design Verification Engineer'
        for suffix in ('Posted a day ago', 'Posted 2 days ago', 'Posted today', 'Posted on 2026-09-18'):
            noisy = role + ' Minneapolis, Minnesota, United States of America ' + suffix
            self.assertEqual(clean_title(noisy, 'Minneapolis, Minnesota, US'), role)
        self.assertEqual(clean_title('New York Hardware Engineer'), 'New York Hardware Engineer')

    def test_both_suffixes_come_off_whichever_order_they_are_in(self):
        """Each is only removable at the end, so one pass reached only the last.

        A title ending in the location came back still carrying the date, and
        cleaning it a second time returned something different from cleaning it
        once -- which is the same title stored under two spellings.
        """
        for noisy in ('RTL Design Engineer - Austin, TX - Posted today',
                      'RTL Design Engineer - Posted today - Austin, TX',
                      'RTL Design Engineer | Posted 2 days ago | Austin, TX'):
            with self.subTest(noisy=noisy):
                cleaned = clean_title(noisy, 'Austin, TX')
                self.assertEqual(cleaned, 'RTL Design Engineer')
                self.assertEqual(clean_title(cleaned, 'Austin, TX'), cleaned)

    def test_employer_exclusions_precede_strong_title_and_cached_score(self):
        rules = jsearch.load_plan()[0]['filter']
        for employer in ('Lockheed Martin Corporation', 'Northrop Grumman', 'Anduril-1'):
            row = {'title': 'ASIC & FPGA Verification Engineer Stf - E4',
                   'company_name': employer, 'raw': {'employer_name': employer, 'relevance': {'confidence': 100}}}
            self.assertEqual(jsearch.rejection_reason(row, rules), 'excluded_employer')
            self.assertEqual(jsearch.relevance(row, rules)[0], 0)
            self.assertEqual(store.score_row(row['title'], row['raw']), 0)
        row = {'title': 'NVIDIA RTX FPGA Verification Engineer', 'company_name': 'NVIDIA'}
        self.assertFalse(jsearch.employer_excluded(row, rules))


class QueueRulesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Path(temporary.name) / 'jobs.sqlite'
        self.ledger = Path(temporary.name) / 'applications.ndjson'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''CREATE TABLE companies(company_key TEXT, name TEXT);
                INSERT INTO companies VALUES ('sample', 'Sample');
                CREATE TABLE jobs(url TEXT, company_key TEXT, title TEXT, location TEXT,
                    source_job_id TEXT,
                    first_seen TEXT, posted_at TEXT, provider_key TEXT, relevance INTEGER,
                    closed_at TEXT, raw TEXT);''')
            # A real JSearch row always carries the provider's job id. It is what
            # keeps a decision attached when the title gains "Posted 2 days ago"
            # and the url is rewritten underneath it.
            db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 100, NULL, ?)',
                       ('https://example.test/job', 'sample', 'RTL Engineer', 'Minneapolis, Minnesota, US',
                        'provider-req-1', datetime.now(timezone.utc).isoformat(), 'jsearch', '{}'))

    def queue(self):
        return applications.queue(self.db, self.ledger)

    def test_the_soft_block_reaches_direct_boards_in_the_queue(self):
        """Direct postings never went through the soft block: it ran only on
        paid results, at collection. Measured on the live backlog, 4,434 groups
        it names were being offered for review."""
        for title, provider, kept in (('Business Operations Analyst', 'workday', False),
                                      ('Supply Chain Planner', 'jsearch', False),
                                      ('Software Development Engineer, Web', 'workday', False),
                                      ('Low Power Verification Engineer', 'workday', True),
                                      ('RFIC Digital Verification Engineer', 'workday', True)):
            with self.subTest(title=title):
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute('UPDATE jobs SET title=?, provider_key=?', (title, provider))
                self.assertEqual(bool(self.queue()['pending']), kept)

    def test_less_related_takes_both_the_last_band_and_a_low_score(self):
        """Asked for on 2026-09-22: barely related postings go to the back."""
        for title, relevance, less in (('Onsite Medical Representative', 0, True),
                                       ('SDC, Synthesis and STA Engineer', 69, False),
                                       ('RTL Design Engineer', 0, False)):
            with self.subTest(title=title):
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute('UPDATE jobs SET title=?, relevance=?', (title, relevance))
                self.assertIs(self.queue()['pending'][0]['less_related'], less)

    def test_a_third_party_listing_says_who_published_it(self):
        """Every open JSearch posting measured on 2026-09-22 linked to a
        third-party site, with no direct option to prefer."""
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET raw=?', (json.dumps({
                'job_publisher': 'InterviewSense', 'job_apply_is_direct': False,
                'employer_website': 'https://www.micron.com'}),))
        job = self.queue()['pending'][0]['jobs'][0]
        self.assertEqual((job['publisher'], job['employer_site']),
                         ('InterviewSense', 'https://www.micron.com'))
        from jobdisco import review
        self.assertEqual(review.slim({'pending': [{'id': 'x', 'jobs': [job]}]})['pending'][0]['jobs'][0]
                         ['publisher'], 'InterviewSense')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET raw=?', (json.dumps({
                'job_publisher': 'Micron', 'job_apply_is_direct': True,
                'employer_website': 'javascript:alert(1)'}),))
        job = self.queue()['pending'][0]['jobs'][0]
        self.assertNotIn('publisher', job, 'a direct link is not a third-party one')
        self.assertNotIn('employer_site', job)

    def test_a_blocked_job_site_is_hidden_by_host_or_by_publisher(self):
        """Blocked at the user's request on 2026-09-22."""
        rules = jsearch.load_plan()[0]['filter']
        for url, publisher, blocked in (
                ('https://us.trabajo.org/job/123', 'Trabajo.org', True),
                ('https://us.trabajo.org/job/123', None, True),
                ('https://www.experteer.com/career/view-jobs/x', 'LinkedIn', True),
                ('https://www.linkedin.com/jobs/view/1', 'Experteer', True),
                ('https://www.adviesvanspijk.nl/vacature/1', None, True),
                ('https://www.linkedin.com/jobs/view/1', 'Advies Van Spijk', True),
                ('https://www.linkedin.com/jobs/view/1', 'LinkedIn', False),
                # "trabajo" anywhere in the link, as asked the same day.
                ('https://www.amazon.jobs/en/jobs/1/medico-a-del-trabajo-whs', 'Amazon', True),
                ('https://careers.example.test/rtl-design', 'Example', False)):
            with self.subTest(url=url, publisher=publisher):
                self.assertEqual(jsearch.publisher_excluded(url, {'job_publisher': publisher}, rules), blocked)
        row = {'title': 'RTL Design Engineer', 'url': 'https://us.trabajo.org/job/1',
               'raw': {'job_publisher': 'Trabajo.org', 'description': 'RTL UVM ASIC'}}
        self.assertEqual(jsearch.rejection_reason(row, rules), 'excluded_publisher')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET url=?, raw=?', ('https://us.trabajo.org/job/1',
                                                       json.dumps({'job_publisher': 'Trabajo.org'})))
        self.assertEqual(self.queue()['pending'], [])

    def test_evidence_domains_reject_before_keeps_and_hide_existing_rows(self):
        rules = jsearch.load_plan()[0]['filter']
        domains = rules['exclude_publisher_domains']
        self.assertEqual(len(domains), 21)
        self.assertEqual(len(set(domains)), len(domains))
        self.assertTrue({'trabajo.org', 'bebee.com', 'experteer.com', 'jobsora.com',
                         'geebo.com', 'higher-hire.com', 'nexxt.com',
                         'adviesvanspijk.nl'}.issubset(domains))
        for domain in rules['exclude_publisher_domains']:
            for url in (f'https://{domain}/job/1', f'https://JOBS.{domain.upper()}.:443/job/1'):
                with self.subTest(url=url):
                    row = {'title': 'RTL Design Intern', 'url': url, 'raw': {}}
                    self.assertEqual(jsearch.rejection_reason(row, rules), 'excluded_publisher')
                    with closing(sqlite3.connect(self.db)) as db, db:
                        db.execute('UPDATE jobs SET url=?', (url,))
                    self.assertEqual(self.queue()['pending'], [])
            self.assertTrue(jsearch.publisher_excluded(
                'https://example.test/job', {'job_publisher': domain}, rules))

    def test_evidence_domains_do_not_match_other_hosts_or_mentions(self):
        rules = jsearch.load_plan()[0]['filter']
        domain = rules['exclude_publisher_domains'][0]
        for url in (f'https://not{domain}/job', f'https://{domain}.example.test/job',
                    f'https://example.test/{domain}', f'https://example.test/?ref={domain}',
                    f'https://{domain}@example.test/job', 'https://[broken', None):
            with self.subTest(url=url):
                self.assertFalse(jsearch.publisher_excluded(url, {}, rules))
        self.assertFalse(jsearch.publisher_excluded(
            'https://example.test', {'job_publisher': 'Report about ' + domain}, rules))
        self.assertTrue(jsearch.publisher_excluded(
            f'https://example.test@{domain}/job', {}, rules))
        self.assertTrue(jsearch.publisher_excluded(
            f'//{domain}/job', {}, {'exclude_publisher_domains': [domain]}))

    def test_domain_configuration_rejects_urls_wildcards_and_wrong_types(self):
        config = self.db.parent / 'plan.toml'
        for value in ('"example.com"', '[42]', '["https://example.com"]',
                      '["*.example.com"]', '["example.com/path"]', '["Example.com"]'):
            with self.subTest(value=value):
                config.write_text('[filter]\nexclude_publisher_domains = ' + value,
                                  encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'exclude_publisher_domains'):
                    jsearch.load_plan(config)

    def test_a_us_person_requirement_hides_a_direct_posting(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE jobs SET provider_key=?, raw=?', ('workday', json.dumps(
                {'description': 'Candidates must be a U.S. citizen or U.S. permanent resident.'})))
        self.assertEqual(self.queue()['pending'], [])

    def test_existing_high_score_defense_employer_is_hidden(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE companies SET name='Anduril-1'")
            db.execute('UPDATE jobs SET relevance=100')
        self.assertEqual(self.queue()['pending'], [])

    def test_existing_jobs_apply_experience_without_deleting_history(self):
        for title, description, kept in (
                ('RTL Engineer', '3 years required', False),
                ('RTL Engineer', 'BS+4 / MS+2', True),
                ('RTL Intern', '5 years required', True),
                ('HR Business Partner, Hardware', '', False),
                ('RTL Engineer', '', True)):
            with self.subTest(title=title, description=description):
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute('UPDATE jobs SET title=?, raw=?', (title, json.dumps({'description': description})))
                pending = self.queue()['pending']
                self.assertEqual(bool(pending), kept)
                if kept:
                    self.assertIn('experience_filter', pending[0]['jobs'][0])
                with closing(sqlite3.connect(self.db)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)

    def test_old_noisy_snapshot_survives_date_and_url_changes(self):
        role = 'ASIC Design Verification Engineer'
        old_title = role + ' Minneapolis, Minnesota, United States of America Posted a day ago'
        group = self.queue()['pending'][0]
        group['title'] = old_title
        group['jobs'][0]['location'] = 'Minneapolis, Minnesota, US'
        applications.append_decision(self.ledger, group, 'skipped', 'Already reviewed')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE jobs SET title=?, location='Minneapolis, Minnesota, US', url=url || '-changed'",
                       (role + ' Minneapolis, Minnesota, United States of America Posted 2 days ago',))
        state = self.queue()
        self.assertEqual(state['pending'], [])
        self.assertEqual(state['skipped'][0]['title'], role)
        applications.append_decision(self.ledger, state['skipped'][0], 'pending')
        self.assertEqual(len(self.queue()['pending']), 1)
