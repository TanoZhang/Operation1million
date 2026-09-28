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
