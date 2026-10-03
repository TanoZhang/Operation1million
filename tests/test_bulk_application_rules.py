"""VLSI scope: preserve the original hardware-related software/JD policy."""
import unittest
from jobdisco import jsearch

class VLSIScopeTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def test_embedded_and_silicon_software_still_use_jd_evidence(self):
        for title in ('Embedded Software Engineer', 'ASIC Software Engineer',
                      'Silicon Validation Software Engineer', 'Firmware Engineer'):
            row = {'title': title, 'raw': {'description': 'RTL ASIC FPGA UVM silicon verification ' * 100}}
            with self.subTest(title=title):
                self.assertFalse(jsearch.rejection_reason(row, self.rules))
        row = {'title': 'Embedded Software Engineer',
               'raw': {'description': 'Cloud web commerce services and user accounts. ' * 100}}
        self.assertEqual(jsearch.rejection_reason(row, self.rules), 'off_domain')

    def test_standalone_software_and_compiler_expansion_is_removed(self):
        for title in ('Compiler Software Engineer', 'Software Engineer - Compiler LLVM',
                      'Full Stack Software Engineer'):
            self.assertEqual(jsearch.rejection_reason({'title': title, 'raw': {}}, self.rules), 'title_mismatch')
        _, queries = jsearch.load_plan()
        self.assertFalse(any('compiler' in q.query.lower() for q in queries))

    def test_equivalent_vlsi_role_names_pass_the_filter(self):
        # No longer searched (the user's 2026-10-03 query list); still kept by the filter.
        expected = {'Logic Design Intern', 'Formal Verification Intern',
                    'Design for Test New Grad', 'Physical Implementation New Grad',
                    'Static Timing Analysis Entry Level', 'Silicon Validation Entry Level'}
        for title in expected:
            with self.subTest(title=title):
                self.assertFalse(jsearch.rejection_reason({'title': title, 'raw': {
                    'description': 'RTL ASIC UVM netlist timing closure ATPG scan chain ' * 100}}, self.rules))
