"""Synthetic policy cases, not provider transport fixtures."""
import unittest

from operation1million import jsearch


class SoftwareEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def reason(self, title, raw):
        return jsearch.rejection_reason({'title': title, 'raw': raw}, self.rules)

    def test_generic_validation_words_do_not_establish_vlsi(self):
        prose = 'Validate autonomous robotics software, embedded hardware and simulation. '
        for title in ('Software Systems Validation Intern', 'ASIC Software Engineer',
                      'Embedded Software Engineer', 'Software Engineer'):
            for description in (prose, prose * 100):
                with self.subTest(title=title, length=len(description)):
                    self.assertEqual(self.reason(title, {'description': description}),
                                     'no_vlsi_evidence')

    def test_missing_jd_cannot_be_replaced_by_metadata_or_old_payload(self):
        for raw in ({}, {'externalPath': '/job/ASIC-Software-Engineer_123',
                        'locationsText': 'Silicon Valley', 'title': 'ASIC Software Engineer'},
                    {'department': 'ASIC RTL FPGA', 'url': 'https://example.test/ASIC',
                     'discovery_queries': ['VLSI Intern'],
                     'jsearch': {'job_description': 'Develop RTL simulation tools.'}}):
            with self.subTest(raw=raw):
                self.assertEqual(self.reason('ASIC Software Engineer', raw), 'missing_software_jd')

    def test_real_chip_jd_can_justify_generic_or_explicit_software_titles(self):
        for title in ('Software Engineer', 'Software Systems Validation Intern',
                      'ASIC Software Engineer', 'Embedded Software Engineer'):
            for field in ('description', 'job_description', 'descriptionPlain', 'content'):
                with self.subTest(title=title, field=field):
                    self.assertEqual(self.reason(title, {field:
                        'Develop RTL simulation and ASIC verification tools using SystemVerilog.'}), '')

    def test_structured_qualifications_are_real_evidence(self):
        self.assertEqual(self.reason('Software Engineer', {'job_highlights': {
            'Qualifications': ['Experience with FPGA verification and UVM.']}}), '')

    def test_generic_silicon_and_soc_are_not_evidence(self):
        self.assertEqual(self.reason('Software Engineer', {'description':
            'Our Silicon Valley team builds SOC 2 compliance tools on CPU and GPU servers.'}),
            'no_vlsi_evidence')

    def test_hard_reject_still_precedes_software_evidence(self):
        self.assertEqual(self.reason('Senior ASIC Software Engineer', {'description':
            'Develop RTL simulation and ASIC verification tools.'}), 'excluded')

    def test_board_automation_vocabulary_is_not_chip_evidence(self):
        self.assertEqual(self.reason('Software Engineering Intern - Design Automation', {
            'description': 'Automate PCB layout in Cadence Allegro and OrCAD. '
                           'Check netlists and design rules before tape-out. '
                           'Build electronic design automation scripts.'}), 'no_vlsi_evidence')
