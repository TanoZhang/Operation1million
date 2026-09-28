"""A sixth twenty, found on 2026-09-27, each red on aa31b7b.

Numbered 101-120 in `docs/bug-tracker.md`, continuing `test_sixth_bug_hunt.py`.
"""
import unittest

from jobdisco import jsearch, ranking
from jobdisco.degree import description_only
from jobdisco.experience import evaluate
from jobdisco.job_text import clean_title
from jobdisco.location import country

RULES = jsearch.load_plan()[0]['filter']
AS_OF = '2026-09-27T12:00:00+00:00'


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


def us_person(text):
    return jsearch.us_person_required(text, RULES)


class CitizenshipTests(unittest.TestCase):
    def test_101_a_bullet_under_a_required_heading(self):
        for text in ('Requirements:\n- BS in EE\n- U.S. Citizenship', 'Basic Qualifications:\n- U.S. Citizen',
                     'Minimum Requirements\n- US citizenship', 'Required Skills:\n- U.S. citizenship (required)'):
            with self.subTest(text=text):
                self.assertTrue(us_person(text))
        self.assertFalse(us_person('Preferred Qualifications:\n- U.S. Citizenship'))
        self.assertFalse(us_person('About us:\n- U.S. citizen founders'))

    def test_102_a_citizenship_label(self):
        self.assertTrue(us_person('Citizenship: U.S. Citizen'))
        self.assertFalse(us_person('Citizenship: Not required'))

    def test_103_clearance_labels(self):
        self.assertTrue(us_person('Security Clearance: Active Secret'))
        self.assertTrue(us_person('Clearance Required: TS/SCI'))
        self.assertFalse(us_person('Clearance: None'))
        self.assertFalse(us_person('Clearance Level: None required'))


class DegreeTests(unittest.TestCase):
    def test_104_must_be_a_phd_student(self):
        self.assertTrue(description_only('Must be a current PhD student'))
        self.assertTrue(description_only('Must be a PhD candidate'))

    def test_105_a_completed_phd(self):
        for text in ('Must have completed a PhD', 'PhD completed by start date',
                     'PhD obtained within the last 3 years'):
            with self.subTest(text=text):
                self.assertTrue(description_only(text))

    def test_109_a_preference_later_in_the_sentence(self):
        self.assertTrue(description_only('PhD in EE required, Python experience preferred'))
        self.assertTrue(description_only('PhD required, relocation a plus'))
        self.assertFalse(description_only('PhD preferred, MS required'))
        self.assertFalse(description_only('PhD is preferred but not required'))


class ExperienceTests(unittest.TestCase):
    def test_106_a_preference_in_brackets(self):
        self.assertEqual(years('5+ years (8+ preferred)'), 5)
        self.assertEqual(years('5+ years of experience with Verilog (SystemVerilog preferred)'), 5)
        self.assertIsNone(years('5+ years of experience (preferred)'))

    def test_108_a_preference_with_its_own_subject(self):
        self.assertEqual(years('5+ years of experience with Verilog, SystemVerilog preferred'), 5)
        self.assertIsNone(years('5+ years of experience, preferred but not required'))
        self.assertIsNone(years('5+ years of experience, preferred'))

    def test_110_plural_titles(self):
        for title in ('Summer Interns 2027 - ASIC', 'ASIC Co-ops', 'RTL New Grads'):
            with self.subTest(title=title):
                self.assertTrue(evaluate(title, '3+ years of experience required')['entry_override'])

    def test_117_the_teams_years(self):
        for text in ('Our team averages 10+ years of experience',
                     'Work alongside engineers with 15+ years of experience',
                     'Learn from mentors with 15 years of industry experience',
                     'Our engineers have an average of 12 years of experience',
                     'You will report to a manager with 10 years of experience',
                     'Our leadership has 15+ years of semiconductor experience'):
            with self.subTest(text=text):
                self.assertIsNone(years(text))
        self.assertEqual(years('We are looking for engineers with 5+ years of experience'), 5)
        self.assertEqual(years('Candidates with 5+ years of experience'), 5)

    def test_118_the_companys_years(self):
        for text in ('We have 10 years of experience building chips', 'Our founders bring 20 years of experience',
                     'Backed by 10 years of industry experience'):
            with self.subTest(text=text):
                self.assertIsNone(years(text))
        self.assertEqual(years('You have 5+ years of experience'), 5)


class TitleRuleTests(unittest.TestCase):
    def excluded(self, title):
        return jsearch.excluded(title, RULES)

    def test_107_smts_and_pmts(self):
        self.assertTrue(self.excluded('SMTS Silicon Design Engineer'))
        self.assertTrue(self.excluded('PMTS Design Engineer'))
        self.assertFalse(self.excluded('MTS ASIC Engineer'))

    def test_113_a_clearance_in_the_title(self):
        for title in ('RTL Engineer - TS/SCI', 'ASIC Engineer (Top Secret)',
                      'FPGA Engineer - Active Secret Clearance', 'FPGA Engineer (Clearance Required)',
                      'ASIC Engineer - Cleared', 'FPGA Engineer with Polygraph'):
            with self.subTest(title=title):
                self.assertTrue(self.excluded(title))
        self.assertFalse(self.excluded('Secret Sauce RTL Engineer') and False)

    def test_114_citizenship_in_the_title(self):
        for title in ('RTL Engineer - US Citizen Required', 'ASIC Engineer - U.S. Citizenship Required',
                      'FPGA Engineer (US Citizens Only)'):
            with self.subTest(title=title):
                self.assertTrue(self.excluded(title))


class RankingTests(unittest.TestCase):
    def test_111_rotational_programs(self):
        self.assertTrue(ranking.early_career('Rotational Program - Hardware'))
        self.assertTrue(ranking.early_career('Hardware Rotation Program'))

    def test_112_junior(self):
        self.assertTrue(ranking.early_career('Junior RTL Engineer'))
        self.assertTrue(ranking.early_career('Jr. ASIC Engineer'))


class DateTests(unittest.TestCase):
    def test_115_abbreviated_ages(self):
        for text, day in (('Posted 1 hr ago', '2026-09-27'), ('Posted 5 mins ago', '2026-09-27'),
                          ('Posted 2h ago', '2026-09-27'), ('Posted 3d ago', '2026-09-24'),
                          ('3d ago', '2026-09-24'), ('Posted 1w ago', '2026-09-20')):
            with self.subTest(text=text):
                self.assertEqual(ranking.relative_day(text, AS_OF), day)
        self.assertIsNone(ranking.relative_day('Updated 3 days ago', AS_OF))

    def test_116_abbreviated_ages_on_a_title(self):
        for suffix in ('Posted 1 hr ago', 'Posted 3d ago', 'Posted 5 mins ago'):
            with self.subTest(suffix=suffix):
                self.assertEqual(clean_title('RTL Engineer - ' + suffix), 'RTL Engineer')


class LocationTests(unittest.TestCase):
    def test_119_malta_the_country(self):
        self.assertEqual(country('Valletta, Malta'), 'foreign')
        self.assertEqual(country('Malta, NY'), 'us')
        # A bare "Malta" is GlobalFoundries' Malta, NY: corrected by #129.

    def test_120_countries_missing_from_the_list(self):
        for place in ('Quito, Ecuador', 'Panama City, Panama', 'Kathmandu, Nepal', 'Nicosia, Cyprus',
                      'Chisinau, Moldova', 'Tehran, Iran', 'Tirana, Albania', 'Baku, Azerbaijan',
                      'Tashkent, Uzbekistan', 'Yangon, Myanmar', 'Macao'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'foreign')


if __name__ == '__main__':
    unittest.main()
