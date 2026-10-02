"""Fifth bug hunt, 2026-10-02: #230-268 (autofill #227-229 are in
tests/autofill-scanner.cjs).

Found on the live queue rebuilt with the code of 2026-10-02 (6,583 groups),
except where a test says it is a wording fed to a rule. Each case is red on
f8f38b7.
"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from jobdisco import export, jsearch, ranking
from jobdisco.experience import evaluate
from jobdisco.job_text import clean_title
from jobdisco.location import country

RULES = jsearch.load_plan()[0]['filter']


def matched(description, title='Engineer'):
    """The strong and common terms a posting's text scores for."""
    return jsearch.relevance({'title': title, 'raw': {'description': description}}, RULES)[1]


def refused(title):
    return jsearch.excluded(title, RULES) or jsearch.title_blocked(title, RULES)


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


class StrongTermTests(unittest.TestCase):
    """Trade-only vocabulary that is ordinary English, or another trade's, in
    postings with no chip in them: counted on the open index's last-band
    postings, and each scored as evidence of the trade."""

    def test_230_cadence_as_a_rhythm(self):
        # 233 postings: "the weekly deal-room cadence", "WBR/MBR cadence".
        self.assertNotIn('cadence', matched('Run the weekly reporting cadence with finance.'))
        self.assertIn('cadence', matched('Experience with Cadence Virtuoso and Spectre.'))

    def test_231_questa_in_italian(self):
        # 28 postings: Amazon's Italian pay notice, "per questa posizione".
        self.assertNotIn('questa', matched('La retribuzione per questa posizione è indicata di seguito.'))
        self.assertIn('questa', matched('Simulation with Questa and VCS.'))

    def test_232_noc_as_a_network_operations_centre(self):
        # 41 postings: "Network Operations Center (NOC) team".
        self.assertNotIn('noc', matched('Join the Network Operations Center (NOC) team, 24x7 shifts.'))
        self.assertIn('noc', matched('Design the NoC fabric connecting CPU clusters.'))

    def test_233_vcs_as_venture_capitalists(self):
        # 18 postings: "accelerators, incubators and VCs".
        self.assertNotIn('vcs', matched('Partner with accelerators, incubators and VCs.'))
        self.assertIn('vcs', matched('Run regressions in VCS and Xcelium.'))

    def test_234_synthesis_of_research(self):
        # 25 postings: "research synthesis", "image/video synthesis".
        self.assertNotIn('synthesis', matched('Lead research synthesis and present insights.'))
        self.assertNotIn('synthesis', matched('Experience with image and video synthesis models.'))
        self.assertIn('synthesis', matched('Own logic synthesis and timing closure.'))

    def test_235_soc_2_compliance(self):
        # 20 postings: "SOC 2 Type II", "SOC reports".
        self.assertNotIn('soc', matched('Maintain SOC 2 Type II controls and SOC reports.'))
        self.assertNotIn('soc', matched('Work in the Security Operations Center (SOC).'))
        self.assertIn('soc', matched('Integrate IP into the SoC and the SoC team.'))

    def test_236_silicon_valley(self):
        self.assertNotIn('silicon', matched('Our office is in Silicon Valley.'))
        self.assertIn('silicon', matched('Bring up first silicon in the lab.'))

    def test_237_foundry_the_product(self):
        self.assertNotIn('foundry', matched('Build agents on Azure AI Foundry and Palantir Foundry.'))
        self.assertIn('foundry', matched('Work with external foundry partners on tape-out.'))

    def test_238_cdc_as_change_data_capture(self):
        self.assertNotIn('cdc', matched('Own change data capture (CDC) pipelines with Debezium.'))
        self.assertNotIn('cdc', matched('Build CDC pipelines into the lakehouse.'))
        self.assertIn('cdc', matched('Run CDC and RDC checks before sign-off.'))


class TitleFamilyTests(unittest.TestCase):
    """Functions with no engineering in them, as the user's other title blocks
    (sales, marketing, technician, legal, assistants) already refuse; each
    family counted on the queue, most of it on the Low relevance tab."""

    def assertRefused(self, *titles):
        for title in titles:
            self.assertTrue(refused(title), title)

    def test_239_tech_for_technician(self):
        self.assertRefused('Data Center Tech Mid Shift', 'Mechatronics & Robotics Tech',
                           'Infra Delivery Install Tech IV, DCC Communities')
        self.assertFalse(refused('Health Tech Hardware Engineer'))

    def test_240_pharmacy_and_medicine(self):
        self.assertRefused('Staff Pharmacist - San Antonio, TX, Amazon Pharmacy', 'Onsite Medical Representative')

    def test_241_events_and_talent_pools(self):
        self.assertRefused('DCO-Adamstown In-Person Hiring Event , DCC Communities',
                           'Open Career Opportunities, GFiber', '2026 TSMC Virtual Series Registration',
                           'HBM Talent Pool – Engineering, Manufacturing')

    def test_242_delivery_and_customer_service(self):
        self.assertRefused('Delivery Station Customer Service Associate, DSL', 'Delivery Associate')

    def test_243_aviation_ground_operations(self):
        self.assertRefused('Prime Air Ground Handler, Amazon Prime Air', 'Flight Monitor, Amazon - Prime Air')

    def test_244_operators_and_clerks(self):
        self.assertRefused('Machine Operator', 'Engineering Lab Operator', 'Ship Clerk, CMH5')

    def test_245_auditors_and_investigators(self):
        self.assertRefused('IT Auditor, AWS, Internal Audit', 'Corporate Security Investigator')

    def test_246_creative_work(self):
        self.assertRefused('Localization Producer - Apple Music', 'UX Writer, Apple Ads', 'Staff UX Designer',
                           '3D Game Artist, Platform Architecture', 'Instructional Designer - Mainframe Education')

    def test_247_strategists_and_negotiators(self):
        self.assertRefused('Account Strategist, SBS Engage, Google Customer Solutions', 'Strategic Negotiator')

    def test_248_retail_stores(self):
        self.assertRefused('US-Genius', 'US-Creative', 'Community Specialist, Channel Retail')
        self.assertFalse(refused('Embedded Engineer (Part-time)'))

    def test_249_consultants(self):
        self.assertRefused('Customer Solutions Consultant, Platform, Google Cloud',
                           'EMEA LCS International Growth Consultant, Retail Vertical')

    def test_250_trainers(self):
        self.assertRefused('Interim Driver Trainer', 'Critical Environment Technical Trainer',
                           'Associate Learning & Development Trainer')

    def test_251_safety_and_security_staff(self):
        self.assertRefused('EHS Specialist', 'Fire Protection Specialist_ 2nd Shift',
                           'Security and Loss Prevention Expert, NA', 'Executive Protection Advisor')
        self.assertFalse(refused('Working Student (f/m/d) NPU Physical Security Testing'))

    def test_252_linguists_and_raters(self):
        self.assertRefused('Machine Learning Data Linguist, Alexa AI')

    def test_253_it_support(self):
        self.assertRefused('IT Support Engineer I, Ops Tech Solutions (OTS)',
                           'Entry-Level Computer Support Specialist', 'HelpLine Technical Support Analyst')

    def test_254_administration(self):
        self.assertRefused('Administrative Business Partner, Cloud AI', 'Executive Business Administrator',
                           'Program Administrative Support, NAST ACES')

    def test_255_maintenance_apprenticeships(self):
        self.assertRefused('Mechatronic Apprentice, DAL3 RME', 'RME Operator (RMEO), Make On Demand')

    def test_256_economics_and_policy(self):
        self.assertRefused('Economist, Stores Economics and Science', 'Immigration Policy Specialist')

    def test_257_real_estate_and_construction_planning(self):
        self.assertRefused('Real Estate Portfolio Executive', 'NY US Construction Scheduler', 'Strategic Space Planner')


class WordingTests(unittest.TestCase):
    """Wordings fed to the rules; no live posting uses them yet."""

    def test_258_years_of_a_degree_are_not_experience(self):
        self.assertIsNone(years('Must have completed at least 3 years of a 4-year degree.'))
        self.assertIsNone(years('Must have completed two years of undergraduate study.'))
        self.assertEqual(years('3 years of experience in RTL design.'), 3)

    def test_259_a_decade(self):
        self.assertEqual(years('A decade of experience in ASIC design.'), 10)

    def test_260_restricted_to_citizens(self):
        self.assertTrue(jsearch.us_person_required('Position is restricted to U.S. citizens.', RULES))
        self.assertTrue(jsearch.us_person_required('This role is limited to United States citizens only.', RULES))
        self.assertFalse(jsearch.us_person_required(
            'A U.S. Person (which includes but is not limited to U.S. citizens or nationals).', RULES))

    def test_261_others_are_not_eligible(self):
        self.assertTrue(jsearch.us_person_required(
            'Non-U.S. citizens are not eligible for this position.', RULES))
        self.assertTrue(jsearch.us_person_required(
            'We are unable to consider candidates who are not U.S. citizens.', RULES))


class PlaceTests(unittest.TestCase):
    def test_262_towns_abroad_with_no_country(self):
        for place in ('Saclay', 'Sibiu', 'Espoo', 'Palestine, Rawabi'):
            self.assertEqual(country(place), 'foreign', place)


class DisplayTitleTests(unittest.TestCase):
    def test_263_the_work_arrangement(self):
        self.assertEqual(clean_title('ASIC Engineer (hybrid)'), 'ASIC Engineer')
        self.assertEqual(clean_title('ASIC Design Hardware Engineer - SDC/STA (Hybrid)'),
                         'ASIC Design Hardware Engineer - SDC/STA')
        self.assertEqual(clean_title('Customer Delivery Architect (Remote)'), 'Customer Delivery Architect')
        self.assertEqual(clean_title('Remote Sensing Engineer'), 'Remote Sensing Engineer')

    def test_264_the_gender_marker(self):
        self.assertEqual(clean_title('SoC Physical Design Intern (m/f/d)'), 'SoC Physical Design Intern')
        self.assertEqual(clean_title('Intern (f/m/d) Agentic AI for Signal Processing'),
                         'Intern Agentic AI for Signal Processing')


class BandTests(unittest.TestCase):
    def test_265_product_development_engineering(self):
        for title in ('Product Development Engineer', 'Board Product Development Engineer',
                      'Characterization Product Development Engineer', 'NAND Product Engineer'):
            self.assertEqual(ranking.bucket(title), 3, title)

    def test_266_failure_analysis(self):
        for title in ('Package Failure Analysis Engineer', 'Failure Analysis Engineer - Nanoprobing'):
            self.assertEqual(ranking.bucket(title), 3, title)

    def test_267_the_cpu_and_its_interconnect(self):
        for title in ('Load Store Design Engineer', 'NoC Interconnect Design Engineer and Architect',
                      'Interconnect Design Engineer', 'Cache Verification Engineer'):
            self.assertEqual(ranking.bucket(title), 2, title)


class ExportLimitTests(unittest.TestCase):
    def test_268_excel_refuses_more_than_65530_links(self):
        """Measured in Excel 16: a sheet with 66,000 hyperlinks did not open."""
        group = {'id': 'g', 'company': 'A', 'title': 'T', 'confidence': 1, 'bucket': 2,
                 'jobs': [{'url': f'https://example.test/{i}'} for i in range(export.MAX_LINKS + 5)]}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'review-queue.xlsx'
            export.write(path, [('pending', group)])
            with zipfile.ZipFile(path) as book:
                sheet = book.read('xl/worksheets/sheet1.xml').decode()
        self.assertEqual(sheet.count('<hyperlink '), export.MAX_LINKS)
        self.assertIn(f'https://example.test/{export.MAX_LINKS + 4}', sheet)


if __name__ == '__main__':
    unittest.main()


class EscapedMarkupTests(unittest.TestCase):
    def test_269_escaped_markup_keeps_its_lines(self):
        """Greenhouse escapes its HTML; as one line, a citizenship line under
        "Preferred" read as required, and would have hidden the posting once
        #207 fetched the descriptions."""
        html = ('<h3>Requirements</h3><ul><li>BS in EE</li></ul><h3>Preferred Qualifications</h3>'
                '<ul><li>Must be a U.S. citizen</li></ul>')
        escaped = html.replace('<', '&lt;').replace('>', '&gt;')
        for content in (html, escaped):
            text = jsearch.description_text({'title': 'RTL Engineer', 'raw': {'content': content}}, structured=True)
            self.assertFalse(jsearch.us_person_required(text, RULES), content[:20])
        self.assertEqual(jsearch.description_text({'raw': {'content': escaped}}),
                         jsearch.description_text({'raw': {'content': html}}))


class MoreStrongTermTests(unittest.TestCase):
    def test_270_software_emulators(self):
        self.assertNotIn('emulation', matched('Experience with virtualization or emulation (KVM, QEMU).'))
        self.assertNotIn('emulation', matched('Test apps on the Android emulation.'))
        self.assertIn('emulation', matched('Bring up the design on hardware emulation platforms.'))

    def test_271_patent_assertions(self):
        self.assertNotIn('assertion', matched('Experience with patent assertions, invalidity and infringement.'))
        self.assertIn('assertion', matched('Write SystemVerilog assertions for the arbiter.'))

    def test_272_conformal_coating(self):
        self.assertNotIn('conformal', matched('Own underfill and conformal coating processes.'))
        self.assertIn('conformal', matched('Equivalence checking with Conformal LEC.'))

    def test_273_amazons_strategic_vendor_acceleration(self):
        self.assertNotIn('sva', matched('Manage a portfolio of sva vendors.'))
        self.assertNotIn('sva', matched('The Strategic Vendor Acceleration (SVA) team was created.'))
        self.assertIn('sva', matched('Write SVA properties for the protocol checker.'))

    def test_274_amazon_private_brands(self):
        self.assertNotIn('apb', matched('Amazon Private Brands (APB) owns paid social.'))
        self.assertIn('apb', matched('Design the AXI to APB bridge.'))


class EarlyCareerLevelTests(unittest.TestCase):
    def test_276_engineer_i_is_the_entry_level(self):
        """"Digital Design Engineer I" and Annapurna's "Design Verification
        Engineer I" sat with the experienced roles, off the Early career tab."""
        for title in ('Digital Design Engineer I', 'MLA Design Verification Engineer I, Annapurna Labs',
                      'Hardware Engineer I (Full Time) - United States', 'Embedded Engineer 1'):
            self.assertTrue(ranking.early_career(title), title)
        for title in ('Design Engineer II', 'Engineer III, RTL', 'Staff Engineer I, System Structure Design',
                      'Engineer IV', 'Physical Design Engineer'):
            self.assertFalse(ranking.early_career(title), title)


class OlderThanTests(unittest.TestCase):
    def test_277_thirty_days_or_more_is_not_new(self):
        """Workday's "Posted 30+ Days Ago" was ignored, and the posting sorted
        by the day it was first seen, ahead of newer ones (409 queued)."""
        from jobdisco import applications
        job = {'posted_at': None, 'posted_relative': 'Posted 30+ Days Ago',
               'last_seen': '2026-09-27T10:00:00+00:00', 'first_seen': '2026-09-20T10:00:00+00:00'}
        applications.stated_age(job)
        self.assertIsNone(job['posted_at'])
        self.assertEqual(job['posted_before'], '2026-08-28')
        older = {'id': 'a', 'title': 'RTL Engineer', 'jobs': [job]}
        dated = {'id': 'b', 'title': 'RTL Engineer', 'jobs': [{'posted_at': '2026-09-01', 'first_seen': '2026-09-02'}]}
        self.assertEqual([group['id'] for group in ranking.order([older, dated])], ['b', 'a'])
        script = (Path(__file__).resolve().parents[1] / 'src/jobdisco/review_static/app.js').read_text(encoding='utf-8')
        self.assertIn('posted_before', script)


class MoreDisplayTitleTests(unittest.TestCase):
    def test_279_full_time_is_not_the_role(self):
        """28 queued groups: "... Eng II Full Time - United States",
        "CPU Silicon Validation Engineer - Full-time"."""
        self.assertEqual(clean_title('CPU Silicon Validation Engineer - Full-time'), 'CPU Silicon Validation Engineer')
        self.assertEqual(clean_title('Hardware Engineer I (Full Time)'), 'Hardware Engineer I')
        # A contract or part-time role says so, and keeps saying so.
        self.assertEqual(clean_title('Quality and Reliability System Engineer (Contract)'),
                         'Quality and Reliability System Engineer (Contract)')

    def test_280_the_country_alone(self):
        """26 groups: "Hardware Engineer II Intern - United States", "(US)"."""
        self.assertEqual(clean_title('Hardware Engineer II Intern - United States'), 'Hardware Engineer II Intern')
        self.assertEqual(clean_title('FPGA Engineer - Intern (US)'), 'FPGA Engineer - Intern')
        self.assertEqual(clean_title('ASIC Design Verification Eng II Full Time - United States'),
                         'ASIC Design Verification Eng II')
        self.assertEqual(clean_title('US Persons Only'), 'US Persons Only')

    def test_281_zero_width_characters(self):
        """27 index titles; searching "Internship/Co-op" missed them."""
        self.assertEqual(clean_title('Silicon Engineering Internship​/Co-op'), 'Silicon Engineering Internship/Co-op')


class SpelledPlusTests(unittest.TestCase):
    def test_285_three_plus_bracketed(self):
        """"Three plus (3+) years" read as no requirement (wording)."""
        self.assertEqual(years('Three plus (3+) years of experience in RTL design.'), 3)
        self.assertEqual(years('Five (5) years of experience.'), 5)


class MainTabTitleTests(unittest.TestCase):
    """The last band's titles still shown in the main tabs on 2026-10-02."""

    def test_286_mechanical_misspelled(self):
        self.assertTrue(refused('Mechancial / Thermal Intern'))

    def test_287_electrical_and_electronics_work(self):
        for title in ('Electronics Design Engineer', 'Electrical Platform Intern',
                      'Electrical Test Engineering Co-op Intern January-June 2027'):
            self.assertIn(ranking.bucket(title), (1, 3), title)

    def test_288_computer_engineering_and_digital_systems(self):
        for title in ('Computer Engineering Internship', 'Digital Systems Engineering Intern'):
            self.assertEqual(ranking.bucket(title), 1, title)

    def test_289_semiconductor_test_by_its_initials(self):
        for title in ('SLT Test Engineer', 'Staff Test Engineer - Automated Test Equipment'):
            self.assertEqual(ranking.bucket(title), 3, title)

    def test_290_hdl_and_digital_logic_design(self):
        for title in ('Bluespec Design Engineer (Haskell)', 'Technical Staff Engineer-Design (Digital Logic)'):
            self.assertEqual(ranking.bucket(title), 2, title)

    def test_291_chiplet_and_coherent_interconnects(self):
        for title in ('UCIe Applications Engineering Architect', 'CXL Platform Engineer'):
            self.assertEqual(ranking.bucket(title), 3, title)

    def test_292_fab_support_roles(self):
        for title in ('Wafer Fab Material Handler', 'Wafer Fab Training Coordinator, Raxium'):
            self.assertTrue(refused(title), title)
