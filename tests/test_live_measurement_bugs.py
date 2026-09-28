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


if __name__ == '__main__':
    unittest.main()
