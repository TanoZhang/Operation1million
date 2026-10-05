"""A seventh twenty, found on 2026-09-27, each red on e79a5fd.

Numbered 121-140 in `docs/bug-tracker.md`, continuing `test_seventh_bug_hunt.py`.
"""
import unittest

from operation1million import jsearch, ranking
from operation1million.degree import description_only, phd_only
from operation1million.experience import evaluate
from operation1million.location import country

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


class ExperienceTests(unittest.TestCase):
    def test_121_the_masters_path_in_brackets(self):
        self.assertEqual(years('10+ years of experience (5+ with MS)'), 5)

    def test_122_thirteen_to_nineteen(self):
        self.assertEqual(years('thirteen years of experience'), 13)
        self.assertEqual(years('Sixteen+ years of experience'), 16)

    def test_138_a_graduation_window(self):
        for body in ('Candidates must be graduating between December 2026 and June 2027.',
                     'Expected graduation date: May 2027.'):
            with self.subTest(body=body):
                found = evaluate('Hardware Engineer', body + ' 3+ years of hands-on project experience.')
                self.assertTrue(found['entry_override'])

    def test_139_currently_enrolled(self):
        for body in ("Must be currently enrolled in a Master's program.", 'Currently pursuing a BS or MS in EE.'):
            with self.subTest(body=body):
                found = evaluate('Hardware Engineer', body + ' 3+ years of project experience.')
                self.assertTrue(found['entry_override'])
        # Someone else's enrolment is not the opening.
        self.assertFalse(evaluate('Staff Engineer', 'You will mentor currently enrolled students. '
                                  '8+ years of experience.')['entry_override'])

    def test_140_student_trainee_apprentice_titles(self):
        for title in ('Student Researcher - Hardware', 'Hardware Trainee', 'Apprentice Engineer'):
            with self.subTest(title=title):
                self.assertTrue(evaluate(title, '3+ years of hands-on experience')['entry_override'])


class DegreeTests(unittest.TestCase):
    def test_123_doctor_of_philosophy_and_dphil(self):
        for text in ('Doctor of Philosophy in EE required', 'DPhil required', 'D.Phil. in Engineering required'):
            with self.subTest(text=text):
                self.assertTrue(description_only(text))
        self.assertTrue(phd_only('Doctor of Philosophy Intern', ''))
        self.assertTrue(phd_only('DPhil Intern', ''))


class CitizenshipTests(unittest.TestCase):
    def test_124_us_person_required_or_only(self):
        for text in ('ITAR: U.S. Person required', 'U.S. Persons only', 'US Person Required',
                     'US Persons Only - ITAR'):
            with self.subTest(text=text):
                self.assertTrue(jsearch.us_person_required(text, RULES))
        self.assertFalse(jsearch.us_person_required('U.S. Person status is not required', RULES))


class RankingTests(unittest.TestCase):
    def test_125_early_and_emerging_talent(self):
        self.assertTrue(ranking.early_career('Early Talent - RTL'))
        self.assertTrue(ranking.early_career('Emerging Talent Program - Hardware'))

    def test_126_fresher(self):
        self.assertTrue(ranking.early_career('Fresher - VLSI'))
        self.assertTrue(ranking.early_career('Fresh Graduate - ASIC'))

    def test_127_trainee(self):
        self.assertTrue(ranking.early_career('Engineering Trainee'))
        self.assertTrue(ranking.early_career('Graduate Trainee - Hardware'))

    def test_128_undergraduate(self):
        self.assertTrue(ranking.early_career('Undergraduate Researcher'))

    def test_130_sta(self):
        self.assertEqual(ranking.bucket('STA Engineer'), 2)
        self.assertNotEqual(ranking.bucket('Stadium Engineer'), 2)

    def test_131_physical_design_steps(self):
        for title in ('PnR Engineer', 'CTS Engineer', 'Signoff Engineer', 'Floorplanning Engineer',
                      'Placement Engineer', 'Tapeout Engineer'):
            with self.subTest(title=title):
                self.assertEqual(ranking.bucket(title), 2)

    def test_132_library_characterization(self):
        self.assertEqual(ranking.bucket('Standard Cell Library Characterization Engineer'), 2)
        self.assertEqual(ranking.bucket('Library Characterization Engineer'), 2)

    def test_133_verilog_and_vhdl(self):
        self.assertEqual(ranking.bucket('Verilog Engineer'), 2)
        self.assertEqual(ranking.bucket('VHDL Engineer'), 2)

    def test_134_dfx(self):
        self.assertEqual(ranking.bucket('DFx Engineer'), 2)

    def test_135_microarchitect(self):
        self.assertEqual(ranking.bucket('Microarchitect'), 2)
        self.assertEqual(ranking.bucket('CPU Micro-Architect'), 2)

    def test_136_mask_design_and_design_automation(self):
        self.assertEqual(ranking.bucket('Mask Design Engineer'), 3)
        self.assertEqual(ranking.bucket('Design Automation Engineer'), 3)


class LocationTests(unittest.TestCase):
    def test_129_a_bare_malta_is_malta_new_york(self):
        """Regression from #119: GlobalFoundries' Malta, NY, written alone."""
        self.assertEqual(country('Malta'), 'us')
        self.assertEqual(country('Valletta, Malta'), 'foreign')

    def test_137_us_semiconductor_sites(self):
        for place in ('Boxborough', 'Manassas', 'Tucson', 'Essex Junction', 'Bothell', 'Scottsdale',
                      'San Ramon', 'Taylor, Texas'):
            with self.subTest(place=place):
                self.assertEqual(country(place + '; Bangalore, India'), 'us')


if __name__ == '__main__':
    unittest.main()
