"""Twenty more defects found on 2026-09-27, each red on 411c6ab, and one decision.

Numbered 41-60, continuing `test_third_bug_hunt.py`; the bug log entry in
`docs/architecture.md` is "A third twenty, 2026-09-27 UTC".
"""
import unittest

from operation1million import jsearch, ranking
from operation1million.degree import description_only
from operation1million.experience import evaluate
from operation1million.job_text import clean_title
from operation1million.location import country

RULES = jsearch.load_plan()[0]['filter']


def years(text, title='RTL Design Engineer'):
    return evaluate(title, text)['effective_experience_years']


def us_person(text):
    return jsearch.us_person_required(text, RULES)


class ExperienceTests(unittest.TestCase):
    def test_41_months(self):
        self.assertEqual(years('36 months of experience'), 3)
        self.assertEqual(years('18-24 months of experience'), 1.5)
        self.assertEqual(years('24+ months of experience in RTL design'), 2)
        self.assertIsNone(years('Graduated within the past 6 months'))

    def test_42_the_masters_path_with_its_unit_left_out(self):
        self.assertEqual(years("3+ years of experience (or 1+ with Master's)"), 1)
        self.assertEqual(years('3+ years of experience, or 1+ with an MS'), 1)

    def test_43_exp_for_experience(self):
        self.assertEqual(years('Exp: 3+ yrs'), 3)

    def test_53_hyphenated_and_plural_headings(self):
        self.assertEqual(years('<h3>Must-Haves</h3><ul><li>5+ years in RTL</li></ul>'), 5)
        self.assertIsNone(years('<h3>Nice-to-Haves</h3><ul><li>5+ years of experience</li></ul>'))

    def test_54_pluses(self):
        self.assertIsNone(years('<h3>Pluses</h3><ul><li>5+ years of experience</li></ul>'))
        self.assertIsNone(years('5+ years of experience would be a big plus'))

    def test_55_or_after_a_full_stop(self):
        """Qualcomm's standard wording."""
        text = ("Bachelor's degree in Electrical Engineering and 3+ years of Hardware Engineering "
                "experience. OR Master's degree in Electrical Engineering and 2+ years of Hardware "
                "Engineering experience. OR PhD in Electrical Engineering and 1+ year of Hardware "
                "Engineering experience.")
        self.assertEqual(years(text), 2)

    def test_52_a_senior_title_is_not_made_an_internship_by_boilerplate(self):
        for boilerplate in ('Join our talent community for internship and new grad updates.',
                            'Refer a friend for our internship program.',
                            'We partner with universities to hire co-op students.'):
            with self.subTest(boilerplate=boilerplate):
                found = evaluate('Staff ASIC Engineer',
                                 '10+ years of experience in ASIC design.\n' + boilerplate)
                self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')
        # The title still decides when it says intern.
        self.assertTrue(evaluate('Senior Design Intern', '5 years of experience')['entry_override'])


class DecisionTests(unittest.TestCase):
    """The user's decision, 2026-09-27: BS and MS paths listed apart are
    alternatives, whether joined by a comma, a semicolon, a bullet or a new
    sentence. A requirement stated beside them still stands."""

    def test_paths_listed_apart_are_alternatives(self):
        for text in ("- Bachelor's degree and 4+ years of experience\n- Master's degree and 2+ years of experience",
                     '4 years of experience with BS; 2 years with MS; 0 years with PhD',
                     'Experience: BS 4+ years, MS 2+ years',
                     'Minimum 4 years of experience with a BS degree, 2 years with an MS',
                     'Requirements: BS with 5 years of RTL/FPGA verification experience, MS with 2 years'):
            with self.subTest(text=text):
                self.assertEqual(years(text), 2)

    def test_a_requirement_beside_the_paths_still_stands(self):
        self.assertEqual(years('5 years of experience. MS with 2 years. BS with 4 years.'), 5)
        self.assertEqual(years("Bachelor's degree with 4+ years of experience."), 4)


class DegreeTests(unittest.TestCase):
    def test_45_a_phd_student_stated_as_who_you_are(self):
        for text in ('Currently a PhD student in EE.', 'You are a PhD student in EE',
                     'This internship is for PhD students.'):
            with self.subTest(text=text):
                self.assertTrue(description_only(text))
        self.assertFalse(description_only('This internship is for PhD and MS students.'))


class CitizenshipTests(unittest.TestCase):
    def test_44_an_active_clearance_required(self):
        for text in ('Active TS/SCI clearance required', 'Must have an active Top Secret clearance',
                     'An active Secret security clearance is required.'):
            with self.subTest(text=text):
                self.assertTrue(us_person(text))
        for text in ('Ability to obtain a security clearance', 'Must be eligible for a DoD clearance',
                     'Security clearance is a plus'):
            with self.subTest(text=text):
                self.assertFalse(us_person(text))

    def test_56_citizens_of_the_united_states(self):
        self.assertTrue(us_person('Must be a citizen of the United States'))
        self.assertTrue(us_person('Applicants must be citizens of the United States'))

    def test_57_usa_american_and_hyphenated(self):
        for text in ('USA citizenship required', 'U.S.A. citizenship is required',
                     'American citizenship required', 'Must be a US-citizen'):
            with self.subTest(text=text):
                self.assertTrue(us_person(text))

    def test_58_non_citizens_ruled_out(self):
        self.assertTrue(us_person('This job is not open to non-U.S. citizens'))
        self.assertTrue(us_person('Non-US citizens need not apply'))
        self.assertFalse(us_person('Candidates who are not U.S. citizens may be required to obtain an export license'))


class TitleTests(unittest.TestCase):
    def test_46_graduate_titles(self):
        for title in ('Graduate RTL Engineer', 'RTL Design Engineer (Grad)', 'Class of 2027 - ASIC Engineer'):
            with self.subTest(title=title):
                self.assertTrue(ranking.early_career(title))
        self.assertFalse(ranking.early_career('Gradle Build Engineer'))

    def test_47_apprentice(self):
        self.assertTrue(ranking.early_career('Hardware Engineering Apprentice'))
        self.assertTrue(ranking.early_career('Apprenticeship - ASIC'))


class LocationTests(unittest.TestCase):
    def test_48_places_joined_by_and(self):
        self.assertEqual(country('Austin, TX & Toronto, ON'), 'us')
        self.assertEqual(country('Austin, TX and Toronto, Canada'), 'us')
        self.assertEqual(country('Toronto and Ottawa, Canada'), 'foreign')


class CleanTitleTests(unittest.TestCase):
    def test_49_in_before_the_location(self):
        self.assertEqual(clean_title('RTL Engineer in Austin, TX', 'Austin, TX'), 'RTL Engineer')

    def test_50_the_location_in_brackets(self):
        self.assertEqual(clean_title('RTL Engineer (Austin, TX)', 'Austin, TX'), 'RTL Engineer')

    def test_51_posted_on_a_numeric_date(self):
        self.assertEqual(clean_title('RTL Engineer | Posted on 09/07/2026'), 'RTL Engineer')

    def test_60_reposted_and_posted_with_a_colon(self):
        self.assertEqual(clean_title('RTL Engineer - Reposted 3 days ago'), 'RTL Engineer')
        self.assertEqual(clean_title('RTL Engineer - Posted: 3 days ago'), 'RTL Engineer')


class DateTests(unittest.TestCase):
    def test_59_ages_without_a_bare_posted(self):
        as_of = '2026-09-27T12:00:00+00:00'
        for text in ('Posted: 3 days ago', 'Reposted 3 days ago', '3 days ago'):
            with self.subTest(text=text):
                self.assertEqual(ranking.relative_day(text, as_of), '2026-09-24')


if __name__ == '__main__':
    unittest.main()
