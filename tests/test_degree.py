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
                     "Basic Qualifications\n- PhD, or Master's degree and 4+ years of CS experience",
                     "Minimum:\nPursuing a PhD in EE.\nOr a Master's degree with 2 years of research experience.",
                     'Our team includes PhDs from top universities.',
                     'We work with PhD students on research projects.'):
            with self.subTest(text=text[:40]):
                self.assertFalse(phd_only('RTL Design Intern', text))

    def test_short_degree_forms_are_read_as_degrees_not_words(self):
        """Read without case, "B.E." is "be" and "M.E." is "me", and every
        description would have seemed to offer another degree."""
        self.assertTrue(phd_only('RTL Intern', 'Requirements\nCurrently pursuing a PhD. You must be on site; '
                                                'let me know your dates.'))
        self.assertFalse(phd_only('RTL Intern', 'Requirements\nCurrently pursuing a PhD. BS or MS students '
                                                 'with research experience also considered.'))

    def test_it_is_a_hard_pass_in_the_paid_filter(self):
        rules = jsearch.load_plan()[0]['filter']
        row = {'title': 'Hardware Engineering Intern, PhD, Summer 2027', 'raw': {'description': 'RTL UVM ASIC'}}
        self.assertEqual(jsearch.rejection_reason(row, rules), 'phd_only')
        self.assertIn('phd_only', jsearch.HARD_REJECTIONS)


if __name__ == '__main__':
    unittest.main()
