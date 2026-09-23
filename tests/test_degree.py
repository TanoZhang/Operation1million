"""Only a PhD will do -- and nothing broader is removed.

Asked for on 2026-09-22: "delete PhD-only postings, keep ones a PhD may apply
to, and do not remove the wrong ones". Every case below is a wording seen in
the live queue that day, or its nearest counterpart.
"""
import unittest

from jobdisco import jsearch
from jobdisco.degree import phd_only


class PhdOnlyTests(unittest.TestCase):
    def test_a_title_naming_only_a_phd(self):
        for title in ('Software Engineer, PhD, Early Career, 2026', 'Ph.D. Intern - Analog, Mixed Signal',
                      'Silicon RTL Design Engineer, PhD, Google Cloud', 'PhD Research Intern, Circuits - 2027',
                      'Design/DSP/Verification Intern - PhD Degree', 'Post-Doctoral Researcher, PhD, 2026 Start'):
            with self.subTest(title=title):
                self.assertTrue(phd_only(title, ''))

    def test_a_title_naming_another_degree_is_kept(self):
        for title in ('Design Verification Intern, MS/PhD', 'ASIC Intern, BS/MS/PhD',
                      '2027 Masters/PhD AI Intern', 'Graduate Intern (BS, MS or PhD)'):
            with self.subTest(title=title):
                self.assertFalse(phd_only(title, 'Currently pursuing a PhD in EE.'))

    def test_a_title_saying_a_phd_is_optional_is_kept(self):
        for title in ('Engineer - PhD Preferred', 'Engineer (PhD preferred)',
                      'Engineer - PhD a plus', 'Ideally PhD - Hardware Engineer',
                      'Engineer - PhD not required', 'Engineer - No PhD Required',
                      'Engineer - PhD Optional', 'Engineer - PhD or relevant experience',
                      'Engineer - PhD or comparable industry experience'):
            with self.subTest(title=title):
                self.assertFalse(phd_only(title, ''))

    def test_a_description_requiring_only_a_phd(self):
        for text in ('Minimum qualifications:\nCurrently pursuing a PhD in Electrical Engineering.\n'
                     'You must be able to work in a team.',
                     'Basic Qualifications\n- PhD in computer science, machine learning, engineering, '
                     'or related fields\n- Experience with Python'):
            with self.subTest(text=text[:40]):
                self.assertTrue(phd_only('Applied Scientist', text))

    def test_a_phd_that_is_only_allowed_or_preferred_is_kept(self):
        for text in ("Currently pursuing a Bachelor's, Master's or PhD in EE.",
                     'Preferred qualifications:\nPhD in Electrical Engineering',
                     'Requirements: MS in EE. PhD preferred.',
                     "Master's degree required. PhD a plus.",
                     'PhD or equivalent practical experience is required.',
                     'PhD or relevant experience is required.',
                     'Doctorate or comparable industry experience required.',
                     'A PhD is not required.', 'No PhD required.', 'PhD optional.',
                     "Basic Qualifications\n- PhD, or Master's degree and 4+ years of CS experience",
                     "Minimum:\nPursuing a PhD in EE.\nOr a Master's degree with 2 years of research experience.",
                     'Our team includes PhDs from top universities.',
                     'We work with PhD students on research projects.'):
            with self.subTest(text=text[:40]):
                self.assertFalse(phd_only('RTL Design Intern', text))

    def test_negation_does_not_swallow_a_real_requirement(self):
        for text in ('PhD required.', 'A PhD is required.', 'PhD mandatory.',
                     'Must have a doctorate degree.'):
            with self.subTest(text=text):
                self.assertTrue(phd_only('RTL Design Intern', text))

    def test_additional_experience_is_not_an_alternative_degree(self):
        for text in ('PhD required. Relevant experience with Python.',
                     'PhD required and relevant experience with Python.',
                     'PhD required. Comparable industry experience with Python.'):
            with self.subTest(text=text):
                self.assertTrue(phd_only('RTL Engineer', text))
        for text in ('PhD required or relevant experience.',
                     'PhD required or comparable industry experience.'):
            with self.subTest(text=text):
                self.assertFalse(phd_only('RTL Engineer', text))

    def test_short_degree_forms_are_read_as_degrees_not_words(self):
        """Read without case, "B.E." is "be" and "M.E." is "me", and every
        description would have seemed to offer another degree."""
        self.assertTrue(phd_only('RTL Intern', 'Requirements\nCurrently pursuing a PhD. You must be on site; '
                                                'let me know your dates.'))
        self.assertFalse(phd_only('RTL Intern', 'Requirements\nCurrently pursuing a PhD. BS or MS students '
                                                 'with research experience also considered.'))

    def test_structured_field_end_stops_heading_scope(self):
        """Qualification headings belong only to their raw payload field."""
        preferred_then_required = {
            'preferred_qualifications': ['PhD in EE is a plus'],
            'description': 'Candidates must be currently pursuing a PhD.',
        }
        required_then_biography = {
            'required_qualifications': ['Python experience'],
            'description': 'PhD in electrical engineering, Jane Doe leads our research team.',
        }
        self.assertTrue(phd_only(
            'Applied Scientist',
            jsearch.description_text({'raw': preferred_then_required}, structured=True)))
        self.assertFalse(phd_only(
            'Applied Scientist',
            jsearch.description_text({'raw': required_then_biography}, structured=True)))

    def test_it_is_a_hard_pass_in_the_paid_filter(self):
        rules = jsearch.load_plan()[0]['filter']
        row = {'title': 'Hardware Engineering Intern, PhD, Summer 2027', 'raw': {'description': 'RTL UVM ASIC'}}
        self.assertEqual(jsearch.rejection_reason(row, rules), 'phd_only')
        self.assertIn('phd_only', jsearch.HARD_REJECTIONS)

    def test_shared_eligibility_entry_point_keeps_paid_and_review_checks_together(self):
        rules = jsearch.load_plan()[0]['filter']
        cases = (
            ({'title': 'Engineer', 'raw': {'description': 'Requires 5 years of experience.'}},
             'required_experience_over_2_years'),
            ({'title': 'Engineer', 'raw': {'description': 'Applicants must be a U.S. citizen.'}},
             'us_person_required'),
            ({'title': 'Engineer', 'raw': {'description': 'Currently pursuing a PhD.'}},
             'phd_only'),
            ({'title': 'Engineer - PhD Preferred', 'raw': {'description': 'RTL UVM ASIC'}}, ''),
        )
        for row, expected in cases:
            with self.subTest(expected=expected):
                reason, experience = jsearch.eligibility_rejection(row, rules)
                self.assertEqual(reason, expected)
                self.assertEqual(row['raw']['experience_filter'], experience)


if __name__ == '__main__':
    unittest.main()


class ReportedBugTests(unittest.TestCase):
    """Reported 2026-09-22 after the rule went live."""

    def test_an_alternative_stated_as_its_own_short_line_is_read(self):
        """"Or Master's degree required." is four words and names a required
        section, and was taken for a heading and skipped -- losing the
        alternative that keeps the posting."""
        self.assertFalse(phd_only('Engineer', "PhD required.\nOr Master's degree required."))
        self.assertFalse(phd_only('Engineer', "PhD required.\nMS accepted."))

    def test_a_short_preference_is_not_a_preferred_section(self):
        """"Python preferred." was read as a Preferred heading, and suppressed
        the requirement on the line after it."""
        self.assertTrue(phd_only('Engineer', 'Python preferred.\nPhD required.'))
        self.assertTrue(phd_only('Engineer', 'Travel preferred.\nCurrently pursuing a PhD.'))
        # A real heading still opens a section.
        self.assertFalse(phd_only('Engineer', 'Preferred qualifications:\nPhD in Electrical Engineering'))
        self.assertFalse(phd_only('Engineer', 'Nice to have\nPhD in EE'))

    def test_a_requirement_behind_its_own_heading_on_one_line(self):
        self.assertTrue(phd_only('Engineer', 'Required: PhD in EE'))
        self.assertTrue(phd_only('Engineer', 'Minimum qualification: PhD in Physics'))
        self.assertFalse(phd_only('Engineer', 'Preferred: PhD in EE'))
        self.assertFalse(phd_only('Engineer', 'Requirements: PhD in EE or MS with 5 years'))


class PreferenceWordingTests(unittest.TestCase):
    """A PhD that is welcome rather than demanded, found reviewing 583bfd7."""

    def test_preference_words_beyond_preferred_keep_the_posting(self):
        for text in ('Pursuing a PhD is an advantage.',
                     'A PhD would be advantageous.',
                     'PhD is highly desirable.',
                     'Candidates currently pursuing a PhD are encouraged to apply.',
                     'PhD students are welcome to apply.',
                     'The ideal candidate will have a PhD in EE.',
                     'Preferably pursuing a PhD in EE.',
                     'We prefer candidates pursuing a PhD.',
                     'PhD is a big plus.'):
            with self.subTest(text=text):
                self.assertFalse(phd_only('RTL Engineer', text))
        for title in ('Engineer - PhD Welcome', 'Engineer (PhD desirable)',
                      'Engineer - PhD Preferably', 'Engineer (PhD a big plus)'):
            with self.subTest(title=title):
                self.assertFalse(phd_only(title, ''))

    def test_a_preference_in_the_next_sentence_qualifies_the_phd(self):
        for text in ('Pursuing a Ph.D. Preferred but not required.',
                     'Currently pursuing a Ph.D. Strongly preferred.',
                     'Currently pursuing a PhD. Strongly preferred.'):
            with self.subTest(text=text):
                self.assertFalse(phd_only('RTL Engineer', text))
        # Abbreviated requirements are still read, and an unrelated short
        # preference after a requirement does not soften it.
        for text in ('Currently pursuing a Ph.D. in EE.', 'Ph.D. required.',
                     'Minimum qualifications:\nPh.D. in EE', 'PhD required.\nPython preferred.'):
            with self.subTest(text=text):
                self.assertTrue(phd_only('RTL Engineer', text))

    def test_a_later_heading_ends_the_required_section(self):
        for heading in ('Desirable:', 'Nice-to-have:', 'Pluses:', 'Ideal Qualifications:',
                        'What sets you apart:', 'Extra credit:'):
            with self.subTest(heading=heading):
                self.assertFalse(phd_only(
                    'RTL Engineer', 'Requirements:\n- 2 years of Verilog\n' + heading + '\n- PhD in EE'))
        # A neutral sub-heading stays inside the section it belongs to.
        self.assertTrue(phd_only('RTL Engineer', 'Minimum qualifications:\nEducation:\n- PhD in EE'))
