"""Twenty defects found probing the filters on 2026-09-27, each red on d7be20e.

Numbered as in the bug log (`docs/architecture.md`, "Twenty more from probing
the rules, 2026-09-27 UTC"). Every input is a wording the boards use, not a
constructed edge case.
"""
import unittest

from operation1million import jsearch, ranking
from operation1million.degree import description_only
from operation1million.experience import evaluate
from operation1million.job_text import clean_title
from operation1million.location import country


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


def structured(raw):
    return jsearch.description_text({'raw': raw}, structured=True)


class HeadingTests(unittest.TestCase):
    """1-7: what opens a section, and what only looks like it does."""

    def test_1_a_sentence_starting_with_a_heading_word_is_not_a_heading(self):
        for lead in ('Ideally you know Python.', 'Bonus if you know Perl.',
                     'Additional perks are a plus.', 'Ideally, you will join our team.'):
            with self.subTest(lead=lead):
                self.assertEqual(years(lead + '\n5+ years of experience in RTL design.'), 5)

    def test_2_the_same_sentence_does_not_hide_a_phd_requirement(self):
        for lead in ('Ideally you know Python.', 'Bonus if you know Perl.'):
            with self.subTest(lead=lead):
                self.assertTrue(description_only(lead + '\nPhD in EE required.'))

    def test_3_a_heading_without_a_colon_still_opens_a_required_section(self):
        for heading in ('Must Have', 'Job Requirements', 'Required Skills and Experience'):
            with self.subTest(heading=heading):
                text = f'<h3>{heading}</h3><ul><li>5+ years in RTL design</li></ul>'
                self.assertEqual(years(text), 5)

    def test_4_an_inline_preference_does_not_make_the_rest_of_the_list_optional(self):
        text = 'Requirements:\n- Preferred: Python\n- 5+ years of experience in RTL design'
        self.assertEqual(years(text), 5)

    def test_5_nor_does_it_in_the_degree_filter(self):
        text = 'Requirements:\n- Preferred: Python\n- PhD in Electrical Engineering'
        self.assertTrue(description_only(text))
        # The line itself is still a preference, and R7 still holds.
        self.assertFalse(description_only('Preferred: PhD in Electrical Engineering'))
        self.assertTrue(description_only('Preferred qualifications:\nPython\nRequired: PhD in EE'))

    def test_6_a_requirements_field_keeps_its_heading(self):
        """Codex R5."""
        for key in ('requirements', 'job_requirements'):
            with self.subTest(key=key):
                self.assertTrue(description_only(structured({key: ['PhD in Electrical Engineering']})))
                self.assertEqual(years(structured({key: ['5+ years in RTL design']})), 5)

    def test_7_a_field_named_for_a_requirement_is_read_as_its_heading(self):
        self.assertEqual(years(structured({'job_required_skills': ['5+ years in RTL design']})), 5)
        # A preferred field still ends at its own boundary.
        text = structured({'preferred_qualifications': ['Python'],
                           'job_description': '5+ years of experience in RTL design'})
        self.assertEqual(years(text), 5)


class LocationTests(unittest.TestCase):
    """8-10: U.S. places read as abroad."""

    def test_8_a_us_town_named_after_a_country(self):
        for place in ('West Jordan, UT', 'Poland, OH', 'Mexico, MO', 'Peru, IN'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'us')
        self.assertEqual(country('Perth, WA, Australia'), 'foreign')
        self.assertEqual(country('Amman, Jordan'), 'foreign')

    def test_9_a_state_name_with_its_zip_code(self):
        self.assertEqual(country('Albuquerque, New Mexico 87101'), 'us')
        self.assertEqual(country('Anytown, CA 95054; Toronto, Canada'), 'us')

    def test_10_a_bare_us_is_the_united_states(self):
        for place in ('Remote - US; Toronto, Canada', 'Toronto, Canada / Remote US',
                      'Remote (US)', 'Remote US'):
            with self.subTest(place=place):
                self.assertEqual(country(place), 'us')
        # Lower case is the pronoun, not the country.
        self.assertIsNone(country('Join us'))


class ExperienceTests(unittest.TestCase):
    """11-15 and 19: requirements misread."""

    def test_11_the_degree_named_after_the_years(self):
        self.assertEqual(years('4+ years of experience with a BS, or 2+ years with an MS.'), 2)
        self.assertEqual(years("Minimum of 3 years of experience with a Bachelor's degree "
                               "or 1 year with a Master's degree."), 1)
        # A single path is still a requirement.
        self.assertEqual(years("5+ years of experience with a Bachelor's degree."), 5)

    def test_12_alternatives_separated_by_a_semicolon(self):
        self.assertEqual(years("Bachelor's degree and 3+ years of experience; "
                               "or Master's degree and 1+ years of experience."), 1)

    def test_13_a_spelled_out_range_reads_its_lower_bound(self):
        self.assertEqual(years('Five to seven years of experience'), 5)
        self.assertEqual(years('three-five years of experience'), 3)

    def test_14_seven_plus_years(self):
        self.assertEqual(years('Seven plus years of experience'), 7)
        self.assertEqual(years('5 plus years of experience in ASIC design'), 5)

    def test_15_yoe(self):
        self.assertEqual(years('3+ YOE in Verilog'), 3)

    def test_19_a_pointer_to_the_internship_programme_is_not_an_internship(self):
        for boilerplate in ('Students: explore our internship opportunities at careers.acme.com.',
                            'Looking for an internship? Visit our university page.',
                            'Check out our new grad roles on our careers site.'):
            with self.subTest(boilerplate=boilerplate):
                found = evaluate('Senior Design Engineer',
                                 '10+ years of experience in ASIC design.\n' + boilerplate)
                self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')
        # The opening described in the body is still one.
        found = evaluate('Hardware Engineer', 'This internship runs for 12 weeks. 3+ years of coursework.')
        self.assertTrue(found['entry_override'])


class DegreeTests(unittest.TestCase):
    def test_16_a_degree_ruled_out_is_not_another_way_in(self):
        self.assertTrue(description_only('Masters students are not eligible. PhD required.'))
        self.assertTrue(description_only("MS candidates won't be considered. PhD required."))
        self.assertFalse(description_only("PhD required; MS with 5 years of experience will be considered."))


class TitleTests(unittest.TestCase):
    def test_17_a_comma_before_the_location_goes_with_it(self):
        self.assertEqual(clean_title('Engineer, Austin, TX, United States', 'Austin, TX, US'), 'Engineer')
        self.assertEqual(clean_title('RTL Engineer, Austin, TX', 'Austin, TX'), 'RTL Engineer')


class RankingTests(unittest.TestCase):
    def test_18_ncg_is_new_college_grad(self):
        self.assertTrue(ranking.early_career('NCG RTL Design Engineer'))
        self.assertEqual(ranking.bucket('RTL Design Engineer - NCG'), 0)
        self.assertFalse(ranking.early_career('NCGR Liaison'))

    def test_20_a_senior_recruiting_role_is_not_an_early_career_opening(self):
        for title in ('Senior Manager, Campus Recruiting', 'Staff Engineer, Student Programs',
                      'Director, Early Career Programs'):
            with self.subTest(title=title):
                self.assertFalse(ranking.early_career(title))
        self.assertTrue(ranking.early_career('Senior Design Engineer Intern'))
        self.assertTrue(ranking.early_career('Campus Hire - RTL Engineer'))


if __name__ == '__main__':
    unittest.main()
