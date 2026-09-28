"""Bugs found by measuring today's fixes against the real index, 2026-09-27.

The job index was bootstrapped from the private data repository for the
first time in this session, and the review queue was built with d7be20e and
with 691c051 against it. Reading every posting that changed side found four
defects, two of them regressions from fixes made earlier the same day (#1 and
#96, #152). Each case below is the wording of a real posting. Red on 691c051.
"""
import unittest

from jobdisco import jsearch
from jobdisco.experience import evaluate, is_heading

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='Digital Design Engineer II'):
    return evaluate(title, text)['effective_experience_years']


class LiveMeasurementTests(unittest.TestCase):
    def test_161_title_case_headings_with_other_words(self):
        """Microsoft's "Additional Or Preferred Qualifications" and GE's
        "Desired Characteristics" stopped being headings with #1, and their
        preferred years became requirements."""
        self.assertTrue(is_heading('Additional Or Preferred Qualifications'))
        self.assertTrue(is_heading('Desired Characteristics'))
        self.assertIsNone(years('Additional Or Preferred Qualifications\n'
                                '• 3+ years building production FPGA designs in Verilog'))
        self.assertIsNone(years('Desired Characteristics\n'
                                '• 4+ years of full-time professional engineering experience'))
        # Still not a heading: a sentence, or a line ending in a full stop.
        self.assertFalse(is_heading('Ideally you know Python'))
        self.assertFalse(is_heading('Bonus if you know Perl.'))
        self.assertFalse(is_heading('Python preferred.'))

    def test_162_a_frequency(self):
        """"pass the Microsoft Cloud Background Check upon hire and every 2
        years thereafter" was read as two years of experience."""
        self.assertIsNone(years('Other Requirements\n• This position will be required to pass the '
                                'Microsoft Cloud Background Check upon hire/transfer and every 2 years thereafter.'))

    def test_163_this_position_requires_it(self):
        """Amazon: "This position requires that the candidate selected must be
        a US Citizen and ... an active TS/SCI" was waved through by #96, which
        meant "positions that require" in the plural."""
        self.assertTrue(jsearch.us_person_required(
            'This position requires that the candidate selected must be a US Citizen and currently '
            'possess and maintain an active TS/SCI security clearance.', RULES))
        self.assertFalse(jsearch.us_person_required(
            'Applicants for positions that require U.S. citizenship must be U.S. citizens', RULES))

    def test_164_a_preferred_section_ends_at_the_next_heading(self):
        """Blue Origin: a Preferred list, then "Export Control Regulations",
        then the U.S. person requirement, which #152 read as preferred."""
        text = ('Preferred Qualifications\n• Python\n\nExport Control Regulations\n\n'
                'Applicants for employment at Blue Origin must be a U.S. citizen or national, '
                'U.S. permanent resident (i.e. current Green Card holder), or lawfully admitted '
                'into the U.S. as a refugee or granted asylum.')
        self.assertTrue(jsearch.us_person_required(text, RULES))
        self.assertEqual(years('Preferred Qualifications:\n- Python\nKey Qualifications:\n'
                               '- 5+ years of RTL design experience'), 5)


class LiveRejectionSampleTests(unittest.TestCase):
    """From reading a random sample of the 446 trade postings the experience
    gate rejects on the live index. Red on a8a42af."""

    def test_165_a_graduate_degree_is_the_masters_path(self):
        self.assertEqual(years("Bachelor's Degree and minimum 4 years of prior relevant experience.\n"
                               'Graduate Degree and a minimum of 2 years of prior related experience.'), 2)

    def test_166_in_lieu_of_a_degree(self):
        self.assertEqual(years("Bachelor's Degree and minimum 4 years of prior relevant experience.\n"
                               'Graduate Degree and a minimum of 2 years of prior related experience.\n'
                               'In lieu of a degree, minimum of 8 years of prior related experience.'), 2)
        self.assertIsNone(years('In lieu of a degree, minimum of 8 years of prior related experience.'))

    def test_167_the_masters_named_first_with_no_years(self):
        self.assertEqual(years("Master's degree in a quantitative field, or Bachelor's degree and 5+ "
                               'years of a quantitative field such as statistics'), 0)

    def test_168_btech_mtech_be_me(self):
        self.assertEqual(years('BE/B.Tech with 3+ years’ of experience or M.Tech with 1+ years of '
                               'experience in Infrastructure development with SOCs or IPs verification'), 1)
        self.assertEqual(years('B.E. with 4 years of experience or M.E. with 2 years of experience'), 2)
        # "be" and "me" in a sentence are words, not degrees.
        self.assertEqual(years('You will be expected to have 5+ years of experience'), 5)

    def test_169_years_or_a_bachelors(self):
        self.assertEqual(years('3+ years of quality assurance engineering experience, or '
                               "Bachelor's degree in engineering, statistics or computer science"), 0)
        self.assertEqual(years('3+ years of experience or a PhD'), 3)


class LiveMissTests(unittest.TestCase):
    """From reading queued trade postings that name 3+ years the gate did not
    read as a requirement. Red on 81e0e88."""

    def test_171_a_bullet_that_leads_with_the_years(self):
        for text in ('Qualifications\n\nMSEE or equivalent\n\n7+ years in Mixed-Signal SOC products, '
                     'with proven tapeout-to-production experience',
                     'Who You Are\n\n7+ years in systems diagnostics, hardware validation, or manufacturing test',
                     '• 5+ years in calibration algorithm development, system bring-up, or verification'):
            with self.subTest(text=text[:40]):
                self.assertGreaterEqual(years(text) or 0, 5)
        # Not a duration that is not asked for.
        self.assertIsNone(years('Our hardware will make intelligence available 3-5 years sooner'))
        self.assertIsNone(years('Our platform has been flying for over 10 years'))

    def test_172_a_bracketed_preference_is_not_a_heading(self):
        """Quanta: a "(Preferred)" line opened a Preferred section with #1 and
        hid the "5+ years of professional" requirement below it."""
        self.assertFalse(is_heading('(Preferred)'))
        self.assertEqual(years('Required Skills/Abilities\n• Python for test automation.\n(Preferred)\n'
                               '• Strong debugging skills\n\nEducation and Experience\n'
                               '• 5+ years of professional'), 5)

    def test_173_mojibake_no_break_spaces(self):
        """"7+ years inÂ\xa0Mixed-Signal SOCÂ\xa0products": a no-break space
        decoded as Windows-1252 glued "in" to the next word."""
        self.assertGreaterEqual(years('Qualifications\n7+ years inÂ Mixed-Signal SOCÂ products, '
                                      'withÂ proven tapeout-to-production experience') or 0, 7)
        self.assertTrue(jsearch.us_person_required('Must be a U.S.Â citizen', RULES))


class LiveCitizenshipTests(unittest.TestCase):
    """From reading the citizenship and export-control sentences left in the
    live queue. Red on cc9f578."""

    def test_174_require_the_candidate_to_be(self):
        self.assertTrue(jsearch.us_person_required(
            'To note: this is an on-site role in Erie and does require the candidate to be a US Persons '
            '(US Citizen or Permanent Resident).', RULES))

    def test_175_a_policy_to_only_hire_them(self):
        self.assertTrue(jsearch.us_person_required(
            'Because our employees are provided access to export-controlled items, our policy is to only '
            'hire "U.S. persons" who are permitted to have access to our technology without an export license.',
            RULES))

    def test_176_either_a_citizen_or(self):
        self.assertTrue(jsearch.us_person_required(
            'Due to applicable export control laws and regulations, candidates must be either a U.S. citizen '
            'or national, U.S. permanent resident (i.e., current Green Card holder), or lawfully admitted into '
            'the U.S. as a refugee or granted asylum.', RULES))
        # The same sentence with a licence route stays open.
        self.assertFalse(jsearch.us_person_required(
            'Due to applicable export control laws and regulations, candidates must be either a U.S. citizen '
            'or national, U.S. permanent resident (i.e., current Green Card holder), or lawfully admitted into '
            'the U.S. as a refugee or granted asylum, or be able to obtain a US export license.', RULES))


class LiveTitleTests(unittest.TestCase):
    """Non-engineering functions on the live queue's related tabs, 2026-09-27.
    Red on a348a85."""

    def excluded(self, title):
        return jsearch.excluded(title, RULES)

    def test_177_business_functions(self):
        for title in ('Advanced Packaging TD/Substrate Finance Specialist', 'Business Analyst I, Verification Services',
                      'Business Planning Specialist', 'Career Accelerator Program - Accounting Analyst',
                      'Career Accelerator Program - Brand Specialist', 'Career Accelerator Program - Financial Planning Analyst',
                      'Career Accelerator Program - Procurement Specialist', 'Communications Specialist, HBM Engineering',
                      'Logistics Coordinator', 'Production Finance', 'Provider Credentialing & Verification Specialist',
                      'Silicon Design IP Licensing Specialist', 'Staff Business Development Specialist',
                      'Staff Business Systems Analyst'):
            with self.subTest(title=title):
                self.assertTrue(self.excluded(title))
        for title in ('Wireless Communications ASIC Engineer', 'Communications Systems FPGA Engineer',
                      'Silicon Design Engineer - Business Unit'):
            with self.subTest(title=title):
                self.assertFalse(self.excluded(title))

    def test_178_graphic_and_web_design(self):
        self.assertTrue(self.excluded('Graphic or Web Layout Designer - Internship'))
        self.assertTrue(self.excluded('Web Designer'))
        self.assertFalse(self.excluded('Mask Layout Designer'))

    def test_179_building_facilities(self):
        for title in ('Facilities Electrical Engineer', 'High Voltage Facilities Electrical Engineer',
                      'Career Accelerator Program - Facilities Engineer'):
            with self.subTest(title=title):
                self.assertTrue(self.excluded(title))


class LiveBandTests(unittest.TestCase):
    """Trade titles the live queue put on the Low relevance tab (the last band).
    Red on cd39d79."""

    def band(self, title):
        from jobdisco import ranking
        return ranking.bucket(title)

    def test_180_timing_methodology(self):
        self.assertEqual(self.band('Design Engineer - Timing Methodology'), 2)
        self.assertEqual(self.band('Staff Engineer, Timing'), 2)

    def test_181_designer(self):
        self.assertEqual(self.band('Physical Designer Engineer, Google Cloud'), 2)
        self.assertEqual(self.band('Logic Designer'), 2)
        self.assertEqual(self.band('Package Designer'), 3)

    def test_182_rtl2gds(self):
        self.assertEqual(self.band('RTL2GDS, Product Engineering Architect'), 2)

    def test_183_mixed_signal(self):
        self.assertEqual(self.band('Mixed-Signal Behavioral Modeling Engineer'), 3)
        self.assertEqual(self.band('NVIDIA 2027 Internships: Mixed Signal Design'), 1)

    def test_184_digital_and_system_level_test(self):
        for title in ('Digital Test Engineer, Staff', 'System Level Test Engineer - Staff',
                      'Staff High-Speed I/O Test Engineer'):
            with self.subTest(title=title):
                self.assertEqual(self.band(title), 3)

    def test_185_chipset(self):
        self.assertEqual(self.band('IoT Chipset PE'), 3)

    def test_186_digital_signal_processing(self):
        self.assertEqual(self.band('Summer 2027 Masters Digital Signal Processing Engineer Intern'), 1)
        self.assertEqual(self.band('DSP Engineer'), 3)

    def test_187_electrical_engineering_and_design(self):
        for title in ('Electrical Engineering Internship (6-Month Program)', 'Display Electrical Design Engineer',
                      'iPhone Touch Sensing Electrical Design Engineer', 'ENGINEER, SIG ELECTRICAL DESIGN'):
            with self.subTest(title=title):
                self.assertIn(self.band(title), (1, 3))


class LiveSoftBlockTests(unittest.TestCase):
    """Found reading what #180-187 moved to the main tabs. Red on cd39d79."""

    def test_188_field_applications_in_the_plural(self):
        for title in ('Field Applications Engineer', 'DSP Specialist FAE (Field Applications Engineer) – West Region',
                      'Field Applications Program - Digital'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.title_blocked(title, RULES))

    def test_189_program_analyst(self):
        for title in ('Program Analyst – Mixed Signal IP', 'Program Analyst, Staff - Automotive Chipset'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.title_blocked(title, RULES))


class LiveAbroadTests(unittest.TestCase):
    """Places abroad the live queue read as the U.S. Red on f808a1c."""

    def test_190_the_country_code_first_with_a_region_that_is_a_state_code(self):
        from jobdisco.location import country
        for place in ('IN, TN, Chennai', 'IN, TN, Chennai - Virtual', 'IT, MI, Milan', 'IT, CT, Catania'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'foreign')
        for place in ('US, IN, Bristol', 'US, TN, Lebanon', 'US, NY, Greece', 'Chennai, TN', 'Carmel, IN'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'us')

    def test_191_an_accented_city_beside_its_code(self):
        """Regression from #88: accents stripped from the place, not from the list."""
        from jobdisco.location import country
        self.assertEqual(country('DE, München'), 'foreign')
        self.assertEqual(country('München, DE'), 'foreign')
        self.assertEqual(country('Montréal, CA'), 'foreign')


class LiveDuplicateTests(unittest.TestCase):
    """A paid listing that links to the employer's own posting was a second
    group beside the direct one: AMD's ".../jobs/88075?lang=en-us" and
    ".../jobs/88075", Micron's ".../job/44540988-new-college-grad-..." and
    ".../job/44540988" (live queue, 2026-09-27). Red on b5f8f78."""

    def test_192_the_same_posting_through_a_paid_listing(self):
        import json
        import sqlite3
        import tempfile
        from contextlib import closing
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from jobdisco import applications
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        db, ledger = root / 'jobs.sqlite', root / 'operational/applications.ndjson'
        now = datetime.now(timezone.utc)
        seen = (now - timedelta(days=1)).isoformat()
        rows = [
            ('https://careers.amd.com/careers-home/jobs/88075', 'amd', '88075', 'amd_careers', 'FPGA Engineer'),
            ('https://careers.amd.com/careers-home/jobs/88075?lang=en-us', 'discovered_amd', 'j1', 'jsearch',
             'FPGA Engineer'),
            ('https://careers.micron.com/careers/job/44540988', 'micron', '44540988', 'eightfold', 'ASIC Engineer'),
            ('https://careers.micron.com/careers/job/44540988-new-college-grad-engineer', 'discovered_micron', 'j2',
             'jsearch', 'ASIC Engineer'),
            # A different requisition on the same host stays.
            ('https://careers.amd.com/careers-home/jobs/99999?lang=en-us', 'discovered_amd', 'j3', 'jsearch',
             'RTL Engineer'),
        ]
        with closing(sqlite3.connect(db)) as con, con:
            con.executescript('''CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE jobs(url TEXT PRIMARY KEY, company_key TEXT, title TEXT, location TEXT,
                                  source_job_id TEXT, first_seen TEXT, posted_at TEXT, provider_key TEXT,
                                  relevance REAL, closed_at TEXT, raw TEXT, last_seen TEXT);''')
            for url, company, ident, provider, title in rows:
                con.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (url, company, title, 'Austin, TX', ident, seen, None, provider, 80, None,
                             json.dumps({'description': '<p>Design hardware.</p>'}), seen))
        state = applications.queue(db, ledger, now)
        urls = sorted(job['url'] for group in state['pending'] for job in group['jobs'])
        self.assertEqual(urls, ['https://careers.amd.com/careers-home/jobs/88075',
                                'https://careers.amd.com/careers-home/jobs/99999?lang=en-us',
                                'https://careers.micron.com/careers/job/44540988'])


class LiveLocationTests(unittest.TestCase):
    def test_170_amazons_leading_country_codes(self):
        """Amazon writes "NG, Lagos", "BH, Manama", "JO, Amman": codes missing
        from the list, so those postings abroad were unplaced and kept."""
        from jobdisco.location import country
        for place in ('NG, Lagos', 'BH, Manama', 'JO, Amman', 'KW, Kuwait City', 'QA, Doha'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'foreign')
        # A code that is also a state stays a state: "Athens, GA".
        self.assertEqual(country('Athens, GA'), 'us')
        self.assertEqual(country('US, WA, Seattle'), 'us')


if __name__ == '__main__':
    unittest.main()
