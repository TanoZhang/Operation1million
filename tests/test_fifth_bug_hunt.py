"""A fourth twenty, found on 2026-09-27, each red on 1bd0645.

Numbered 61-80, continuing `test_fourth_bug_hunt.py`; the bug log entry in
`docs/architecture.md` is "A fourth twenty, 2026-09-27 UTC".
"""
import unittest

from jobdisco import jsearch
from jobdisco.degree import description_only
from jobdisco.experience import evaluate
from jobdisco.job_text import clean_title
from jobdisco.location import country

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


class ExperienceTests(unittest.TestCase):
    def test_61_yrs_with_a_full_stop(self):
        self.assertEqual(years('5 yrs. of experience'), 5)

    def test_70_the_ideal_candidate(self):
        self.assertIsNone(years('The ideal candidate has 5+ years of experience'))
        self.assertIsNone(years('Ideal candidates will have 5+ years of experience'))

    def test_71_a_floor_stated_as_who_is_turned_away(self):
        self.assertEqual(years('Candidates with less than 5 years of experience will not be considered'), 5)
        self.assertEqual(years('Candidates with fewer than 5 years of experience need not apply'), 5)
        self.assertIsNone(years('Less than 2 years of experience'))

    def test_72_an_upper_bound_after_the_number_or_without_of(self):
        for text in ('5 years of experience or less', '5 years max experience',
                     'Maximum 5 years of experience', '5 years of experience at most'):
            with self.subTest(text=text):
                self.assertIsNone(years(text))


class DegreeTests(unittest.TestCase):
    def test_62_only_phd_holders(self):
        self.assertTrue(description_only('PhD holders only'))
        self.assertTrue(description_only('Only PhD candidates will be considered'))

    def test_63_required_after_a_bracket_dash_or_colon(self):
        for text in ('PhD (required)', 'PhD - required', 'PhD: required'):
            with self.subTest(text=text):
                self.assertTrue(description_only(text))

    def test_64_a_labelled_phd_with_nothing_after_it(self):
        self.assertTrue(description_only('Required: Ph.D.'))
        self.assertTrue(description_only('Required: PhD'))

    def test_65_a_must(self):
        self.assertTrue(description_only('PhD in EE is a must'))
        self.assertTrue(description_only('A PhD is a must.'))

    def test_66_requires_a_phd(self):
        self.assertTrue(description_only('This role requires a PhD'))
        self.assertTrue(description_only('Requires a PhD in EE'))
        self.assertFalse(description_only('Requires a PhD or MS in EE'))

    def test_80_a_curly_apostrophe(self):
        self.assertFalse(description_only('PhD required, or a Master’s degree with 3 years of research.'))


class TitleRuleTests(unittest.TestCase):
    def excluded(self, title):
        return jsearch.excluded(title, RULES)

    def test_67_head_without_of(self):
        self.assertTrue(self.excluded('Head, Silicon Engineering'))
        self.assertTrue(self.excluded('Silicon Engineering Head'))
        self.assertFalse(self.excluded('Head-Mounted Display ASIC Engineer'))
        self.assertFalse(self.excluded('HDD Head Design Engineer'))

    def test_68_leader(self):
        self.assertTrue(self.excluded('ASIC Technical Leader'))
        self.assertTrue(self.excluded('Team Leader, RTL'))
        self.assertFalse(self.excluded('Design Verification Engineer - Leadership Program'))

    def test_69_supervisor(self):
        self.assertTrue(self.excluded('Supervisor, ASIC Verification'))

    def test_75_l3_harris_with_a_space(self):
        self.assertTrue(jsearch.employer_excluded({'company_name': 'L3 Harris'}, RULES))
        self.assertTrue(jsearch.employer_excluded({'company_name': 'L-3 Harris Technologies'}, RULES))

    def test_76_saic_as_corp(self):
        self.assertTrue(jsearch.employer_excluded(
            {'company_name': 'Science Applications International Corp'}, RULES))

    def test_77_rtx_businesses(self):
        for name in ('Collins Aerospace', 'Pratt & Whitney', 'Pratt and Whitney'):
            with self.subTest(name=name):
                self.assertTrue(jsearch.employer_excluded({'company_name': name}, RULES))


class LocationTests(unittest.TestCase):
    def test_73_us_regions(self):
        for place in ('Bay Area', 'Silicon Valley', 'DFW', 'Dallas-Fort Worth Metroplex'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'us')
        self.assertEqual(country('Bay Area; Bangalore, India'), 'us')

    def test_74_regions_abroad(self):
        for place in ('APAC', 'EMEA', 'Asia Pacific'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'foreign')
        self.assertIsNone(country('Remote, Americas'))


class CleanTitleTests(unittest.TestCase):
    def test_78_no_space_after_the_comma(self):
        self.assertEqual(clean_title('RTL Engineer - Austin,TX', 'Austin, TX'), 'RTL Engineer')

    def test_79_a_requisition_number(self):
        for title in ('RTL Engineer - Job ID 12345', 'RTL Engineer (Req #12345)',
                      'RTL Engineer | Requisition ID: R-12345'):
            with self.subTest(title=title):
                self.assertEqual(clean_title(title), 'RTL Engineer')
        self.assertEqual(clean_title('RTL Engineer II'), 'RTL Engineer II')


if __name__ == '__main__':
    unittest.main()
