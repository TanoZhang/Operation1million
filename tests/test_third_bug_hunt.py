"""Twenty more defects found on 2026-09-27, each red on 9dfc8b4.

Numbered 21-40, continuing `test_second_bug_hunt.py`; the bug log entry in
`docs/architecture.md` is "Twenty more again, 2026-09-27 UTC".
"""
import unittest

from jobdisco import jsearch, ranking
from jobdisco.collector import posted_from_text
from jobdisco.degree import description_only
from jobdisco.experience import evaluate
from jobdisco.job_text import clean_title

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


class TitleRuleTests(unittest.TestCase):
    def test_21_low_energy_is_not_the_energy_industry(self):
        self.assertFalse(jsearch.excluded('Low-Energy Bluetooth SoC Engineer', RULES))
        self.assertTrue(jsearch.excluded('Energy Storage Engineer', RULES))

    def test_22_a_posting_hiring_up_to_senior_is_open_below_it(self):
        self.assertFalse(jsearch.excluded('SoC RTL Design Engineer (Up to Senior Level)', RULES))
        self.assertTrue(jsearch.excluded('Senior SoC RTL Design Engineer', RULES))


class CitizenshipTests(unittest.TestCase):
    def required(self, text):
        return jsearch.us_person_required(text, RULES)

    def test_23_citizenship_or_permanent_residency_is_required(self):
        self.assertTrue(self.required('U.S. citizenship or permanent residency is required.'))
        self.assertTrue(self.required('US citizenship or permanent resident status required'))

    def test_24_citizens_or_green_card_holders_only(self):
        self.assertTrue(self.required('US Citizens or Green Card holders only'))
        self.assertTrue(self.required('U.S. citizens or permanent residents only.'))

    def test_25_a_labelled_requirement(self):
        self.assertTrue(self.required('Required: U.S. Citizenship'))
        self.assertTrue(self.required('Requirement: US Citizen'))

    def test_26_work_authorization_as_another_way_in(self):
        self.assertFalse(self.required(
            'Must be a US Citizen, Green Card holder, or authorized to work in the US'))
        self.assertFalse(self.required(
            'Must be a U.S. citizen or otherwise legally eligible to work in the United States.'))
        self.assertTrue(self.required('Must be a U.S. citizen or permanent resident.'))


class DateTests(unittest.TestCase):
    def test_27_a_board_age_in_hours_or_weeks(self):
        as_of = '2026-09-27T12:00:00+00:00'
        self.assertEqual(ranking.relative_day('Posted 2 hours ago', as_of), '2026-09-27')
        self.assertEqual(ranking.relative_day('Posted a day ago', as_of), '2026-09-26')
        self.assertEqual(ranking.relative_day('Posted 2 weeks ago', as_of), '2026-09-13')
        self.assertIsNone(ranking.relative_day('Posted 30+ Days Ago', as_of))

    def test_28_sept_and_abbreviations_with_a_point(self):
        for text in ('Sept 7, 2026', 'Sep. 7, 2026', 'Sept. 7, 2026'):
            with self.subTest(text=text):
                self.assertEqual(str(ranking.posted_day(text)), '2026-09-07')

    def test_29_a_board_row_that_says_posted_on(self):
        for text in ('Posted on Sep 7, 2026', 'Posted on: 09/07/2026', 'Posted 7 September 2026',
                     'Posted: Sept 7, 2026'):
            with self.subTest(text=text):
                self.assertEqual(posted_from_text(text), '2026-09-07')


class CleanTitleTests(unittest.TestCase):
    def test_30_an_en_or_em_dash_before_the_location(self):
        self.assertEqual(clean_title('RTL Engineer – Austin, TX', 'Austin, TX'), 'RTL Engineer')
        self.assertEqual(clean_title('RTL Engineer — Austin, TX', 'Austin, TX'), 'RTL Engineer')

    def test_31_a_posted_date_abbreviated_with_a_point(self):
        self.assertEqual(clean_title('RTL Engineer - Posted Sep. 7, 2026'), 'RTL Engineer')

    def test_32_the_location_without_its_country(self):
        self.assertEqual(clean_title('RTL Engineer - Austin, TX', 'Austin, TX, US'), 'RTL Engineer')
        # A country alone is not a place in the title.
        self.assertEqual(clean_title('RTL Engineer - US', 'US'), 'RTL Engineer')
        self.assertEqual(clean_title('New York Hardware Engineer', 'New York, NY, US'),
                         'New York Hardware Engineer')


class ExperienceTests(unittest.TestCase):
    def test_33_desirable_beneficial_and_helpful_are_preferences(self):
        for word in ('desirable', 'is beneficial', 'is helpful'):
            with self.subTest(word=word):
                self.assertIsNone(years(f'3+ years of experience {word}'))

    def test_34_years_the_job_offers_are_not_asked_for(self):
        self.assertIsNone(years('You will gain 3 years of experience in our rotational program'))

    def test_35_a_masters_degree_as_the_other_path(self):
        self.assertEqual(years("3 years of experience OR a Master's degree"), 0)
        self.assertEqual(years("Bachelor's degree + 3 years of experience, or Master's degree"), 0)
        # Still owed where the alternative is a degree the posting cannot mean as a path.
        self.assertEqual(years('3 years of experience or a PhD'), 3)

    def test_36_an_age(self):
        self.assertIsNone(years('Must be at least 18 years old'))

    def test_37_schooling(self):
        self.assertIsNone(years('At least 3 years of college'))
        self.assertIsNone(years('Minimum 2 years of undergraduate study completed'))

    def test_39_the_degree_in_brackets_after_the_years(self):
        self.assertEqual(years('Minimum 4 years (BS) or 2 years (MS) of experience'), 2)

    def test_40_a_degree_written_with_its_field(self):
        self.assertEqual(years('BSEE + 5 years or MSEE + 3 years'), 3)
        self.assertEqual(years('MSEE with 3 years of experience or BSEE with 5 years'), 3)
        self.assertEqual(years('BSc with 5 years of experience or MSc with 3 years of experience'), 3)
        # Paths joined only by a comma stay unjoined, as test_experience holds.
        self.assertEqual(years('BSEE with 5 years of experience, MSEE with 2 years'), 5)


class DegreeTests(unittest.TestCase):
    def test_38_a_masters_welcomed_is_another_way_in(self):
        for text in ('Currently pursuing a PhD. MS students with strong research also welcome.',
                     "Pursuing a PhD; Master's students are also encouraged to apply"):
            with self.subTest(text=text):
                self.assertFalse(description_only(text))
        self.assertTrue(description_only('Required qualifications:\n- PhD in EE\n'
                                         'Preferred qualifications:\n- MS in CS'))


if __name__ == '__main__':
    unittest.main()
