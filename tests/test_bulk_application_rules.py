"""Bulk-application policy grounded in the 2026-10-02 record audit."""
import unittest
from jobdisco import jsearch, ranking

class BulkApplicationRulesTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def row(self, title, description=''):
        return {'title': title, 'url': 'https://careers.example.com/1',
                'raw': {'description': description}}

    def test_adjacent_design_and_toolchain_records_survive(self):
        for title in ('Analog Circuit Design Engineer', 'Analog Layout Design Engineer',
                      'PCB Design Engineer Intern', 'Board Design Engineer',
                      'Signal Integrity/ Power Integrity Engineer',
                      'Compiler Software Engineer', 'Software Engineer II - Compiler/LLVM',
                      'Backend Compiler Engineer - New College Grad 2026'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.rejection_reason(self.row(title), self.rules))
                self.assertIn(ranking.bucket(title), (1, 3))

    def test_generic_applications_and_quality_need_hardware_evidence(self):
        for title in ('Field Applications Engineer', 'FAE - Embedded x86 Specialist', 'Quality Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.rejection_reason(self.row(title,
                    'Develop PCB circuits using Altium; debug silicon, FPGA and PCIe hardware.'), self.rules))
                self.assertEqual(jsearch.rejection_reason(self.row(title,
                    'Manage restaurant food quality and customer requests.'), self.rules), 'no_evidence')

    def test_hard_eligibility_still_wins_over_new_vocabulary(self):
        for title, text, reason in (
            ('Senior Analog Circuit Design Engineer', 'PCB FPGA', 'excluded'),
            ('PCB Design Engineer', 'Applicants must be a U.S. citizen.', 'us_person_required'),
            ('Compiler Software Engineer', 'Minimum 5 years of professional experience required.',
             'required_experience_over_2_years'),
            ('PCB Design Engineer', 'A PhD is required.', 'phd_only')):
            with self.subTest(title=title, reason=reason):
                self.assertEqual(jsearch.rejection_reason(self.row(title, text), self.rules), reason)

    def test_generic_web_software_is_not_a_compiler_role(self):
        self.assertTrue(jsearch.title_blocked('Full Stack Software Engineer', self.rules))
        self.assertTrue(jsearch.title_blocked('GPU Fleet Software Development Engineer', self.rules))

    def test_experimental_query_caps_still_total_existing_budget(self):
        settings, queries = jsearch.load_plan()
        self.assertEqual(sum(q.pages for q in queries), 320)
        names = {q.query for q in queries}
        self.assertIn('Compiler Intern', names)
        self.assertIn('Board Design Intern', names)
