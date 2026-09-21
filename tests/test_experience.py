"""Required experience is a mechanical gate, not a seniority guess."""
import unittest

from jobdisco import jsearch
from jobdisco import experience
from jobdisco.experience import evaluate


class ExperienceTests(unittest.TestCase):
    def test_keep(self):
        cases = [
            ('New Grad', '5+ years experience required'),
            ('Intern', '4+ years required'),
            ('Engineer', '2+ years required'),
            ('Engineer', '2-5 years experience'),
            ('Engineer', '5+ years preferred'),
            ('Engineer', '5+ years experience, preferred'),
            ('Engineer', 'BS+4 / MS+2'),
            ('Engineer', 'BS + 4 years OR MS + 2 years'),
            ('Engineer', 'BS degree and 4 years experience or MS degree and 2 years experience'),
            ('Engineer', 'Bachelor\'s degree with 4 years experience or Master\'s degree with 2 years experience'),
            ('Engineer', 'Preferred qualifications:\n5+ years experience\n6 years industry experience'),
            ('Engineer', '2 years required, 5 years preferred'),
            ('Engineer', '5-year roadmap; 2-year degree; 3-year program'),
            ('Engineer', '5 year roadmap required'),
            ('Engineer', ''),
        ]
        for title, text in cases:
            with self.subTest(title=title, text=text):
                self.assertEqual(evaluate(title, text)['hard_pass_reason'], '')

    def test_hard_pass(self):
        cases = [
            ('Engineer', '3+ years required'),
            ('Engineer', 'minimum 4 years'),
            ('Engineer', 'at least 3 years'),
            ('Engineer', '3-5 years experience'),
            ('Engineer', '3-5 years'),
            ('Engineer', '3 years required and 5 years preferred'),
            ('Engineer', '3 to 5 years experience'),
            ('Engineer', '4+ years RTL/ASIC/verification/professional/industry experience'),
            ('Engineer', 'BS+5 / MS+3'),
            ('Engineer', 'BS + 5 years OR MS + 3 years'),
            ('Early Career', '4+ years experience'),
            ('Entry Level', '4+ years required'),
            ('Junior', '4+ years required'),
            ('Associate', '4+ years required'),
            ('Engineer', 'Preferred qualifications:\n5 years experience\nMinimum qualifications:\n3 years experience'),
            ('Engineer', '2 years experience with RTL; 4 years industry experience required'),
            ('Engineer', 'MS degree. 4 years experience required'),
        ]
        for title, text in cases:
            with self.subTest(title=title, text=text):
                self.assertEqual(evaluate(title, text)['hard_pass_reason'], 'required_experience_over_2_years')

    def test_debug(self):
        info = evaluate('RTL Engineer', 'BS+4 / MS+2')
        self.assertEqual(info, dict(entry_override=False, internship_experience=False,
                                   required_experience_years=4,
                                   effective_experience_years=2, matched_text=['BS+4 / MS+2'],
                                   hard_pass_reason=''))
        self.assertIsNone(evaluate('Engineer', '')['effective_experience_years'])

    def test_override_words_and_boundaries(self):
        for word in ('intern', 'internship', 'new grad', 'new graduate', 'new college grad', 'university graduate'):
            self.assertTrue(evaluate('Engineer', word + '; 5 years required')['entry_override'])
        for word in ('internal', 'international', 'early career', 'entry level', 'junior', 'associate'):
            self.assertFalse(evaluate(word, '5 years required')['entry_override'])

    def test_existing_keep_cannot_bypass_experience(self):
        rules = jsearch.load_plan()[0]['filter']
        row = {'title': 'RTL Engineer', 'raw': {'description': '3 years required'}}
        self.assertEqual(jsearch.rejection_reason(row, rules), 'required_experience_over_2_years')
        self.assertEqual(row['raw']['experience_filter']['effective_experience_years'], 3)
        # Repeat evaluation must not treat its own debug strings as JD evidence.
        self.assertEqual(jsearch.experience_debug(row)['effective_experience_years'], 3)

    def test_structured_preferred_and_html(self):
        for raw in ({'preferred_qualifications': ['5 years experience']},
                    {'description': '<h3>Preferred qualifications</h3><ul><li>5 years experience</li></ul>'}):
            self.assertEqual(jsearch.experience_debug({'title': 'RTL Engineer', 'raw': raw})['hard_pass_reason'], '')

    def test_optional_vocabulary(self):
        for word in ('preferred', 'desired', 'nice to have', 'a plus', 'bonus', 'ideally'):
            with self.subTest(word=word):
                self.assertEqual(evaluate('Engineer', '5 years experience ' + word)['hard_pass_reason'], '')

    def test_hr_title_only_and_override_does_not_bypass_other_rules(self):
        rules = jsearch.load_plan()[0]['filter']
        for title in ('HR Business Partner, Hardware', 'HR Intern', 'Human Resources Specialist'):
            self.assertEqual(jsearch.rejection_reason({'title': title, 'raw': {}}, rules), 'excluded')
        self.assertEqual(jsearch.rejection_reason({'title': 'RTL Engineer', 'raw': {'description': 'Contact HR for details.'}}, rules), '')


class MentionedPeopleTests(unittest.TestCase):
    """A posting that talks about interns is not thereby an internship."""

    def senior(self, body):
        return experience.evaluate('Staff RTL Design Engineer', body)

    def test_supervising_an_intern_is_seniority_not_an_override(self):
        for body in ('You will mentor our interns. 8+ years of experience required.',
                     'Responsibilities include managing the internship program. '
                     '10 years of experience required.',
                     'Leading interns and new grads on the team. '
                     'Minimum 6 years of industry experience.',
                     'You will be training new graduates. 5 years experience required.'):
            with self.subTest(body=body[:40]):
                found = self.senior(body)
                self.assertFalse(found['entry_override'], body)
                self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_a_denied_internship_is_not_an_internship(self):
        """The word is there to rule the reading out, not to invite it."""
        for body in ('This is not an internship. 8+ years of experience required.',
                     'No internships are available for this role. '
                     '10 years of experience required.',
                     'We are hiring an experienced engineer rather than an intern. '
                     'Minimum 6 years of industry experience.',
                     'This posting is for full-time staff, not new graduates. '
                     '5 years experience required.'):
            with self.subTest(body=body[:40]):
                found = self.senior(body)
                self.assertFalse(found['entry_override'], body)
                self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_the_posting_describing_itself_still_overrides(self):
        for title, body in (
                ('ASIC Engineer Intern', 'Requirements: 5+ years of experience.'),
                ('Silicon Engineer', 'This internship runs for 12 weeks. '
                                     '4 years of experience required.'),
                ('Hardware Engineer', 'We are hiring a new graduate for this role. '
                                      'Minimum 5 years of experience.')):
            with self.subTest(title=title):
                found = experience.evaluate(title, body)
                self.assertTrue(found['entry_override'])
                self.assertEqual(found['hard_pass_reason'], '')


class SectionsAndFormatsTests(unittest.TestCase):
    """What a requirement may look like, and where its scope comes from."""

    def found(self, body, title='ASIC Design Engineer'):
        return experience.evaluate(title, body)

    def test_an_optional_skill_does_not_erase_the_requirement_beside_it(self):
        found = self.found('5 years experience required, FPGA knowledge preferred.')
        self.assertEqual(found['required_experience_years'], 5)
        self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_a_marker_attaching_to_the_years_still_makes_them_optional(self):
        for body in ('5+ years experience, preferred',
                     '5 years experience, preferred',
                     '5 years experience preferred, FPGA knowledge a plus.'):
            with self.subTest(body=body):
                self.assertEqual(self.found(body)['hard_pass_reason'], '')

    def test_a_required_heading_makes_the_bullet_under_it_mandatory(self):
        """The words are in the heading, not in the line carrying the number."""
        found = self.found('Required qualifications:\n3 years of RTL design.')
        self.assertEqual(found['required_experience_years'], 3)
        self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_a_preferred_heading_below_it_governs_its_own_bullets(self):
        found = self.found('Required qualifications:\n2 years of RTL design.\n'
                           'Preferred qualifications:\n6 years of DFT.')
        self.assertEqual(found['hard_pass_reason'], '')

    def test_a_deadline_under_a_required_heading_is_not_experience(self):
        found = self.found('Required qualifications:\nDeliver two tape-outs within 3 years.')
        self.assertEqual(found['hard_pass_reason'], '')

    def test_responsibilities_end_the_required_section(self):
        found = self.found('Requirements:\nBS in EE.\nResponsibilities:\n'
                           'Own the block for 4 years.')
        self.assertEqual(found['hard_pass_reason'], '')

    def test_a_hyphen_can_carry_the_unit(self):
        found = self.found('Minimum 3-year experience in RTL design.')
        self.assertEqual(found['required_experience_years'], 3)
        self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_a_fractional_bound_is_neither_rounded_down_nor_split(self):
        found = self.found('Minimum 2.5 years of professional experience.')
        self.assertEqual(found['required_experience_years'], 2.5)
        self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_hyphenated_durations_that_are_not_work_stay_out(self):
        for body in ('5-year roadmap required', '2-year degree required',
                     '3-year program required', '5-year roadmap; 2-year degree'):
            with self.subTest(body=body):
                self.assertEqual(self.found(body)['hard_pass_reason'], '')

    def test_exactly_two_years_is_still_within_the_gate(self):
        for body in ('Minimum 2 years of experience.',
                     'Required: 2.0 years of experience.'):
            with self.subTest(body=body):
                self.assertEqual(self.found(body)['hard_pass_reason'], '')


class StatedAndDeniedTests(unittest.TestCase):
    """A number can be named in order to be ruled out, or asked of the past."""

    def found(self, body, title='ASIC Design Engineer'):
        return experience.evaluate(title, body)

    def test_a_requirement_denied_after_the_number_is_not_a_requirement(self):
        for body in ('5 years of experience is not required.',
                     '5 years experience not required.',
                     'Requirements: 4 years of industry experience is not necessary.'):
            with self.subTest(body=body):
                self.assertEqual(self.found(body)['hard_pass_reason'], '')

    def test_the_same_sentence_without_the_denial_still_refuses(self):
        for body in ('5 years of experience is required.',
                     'Requirements: 4 years of industry experience is expected.'):
            with self.subTest(body=body):
                self.assertEqual(self.found(body)['hard_pass_reason'],
                                 'required_experience_over_2_years')

    def test_an_internship_already_served_is_not_an_internship_posting(self):
        """It is a qualification being asked for, and it is marked as one."""
        for body in ('Prior internship experience required. 8 years of experience required.',
                     'Previous internship or co-op experience preferred. '
                     'Minimum 6 years of industry experience.',
                     'Completed internship in silicon design. 5 years experience required.'):
            with self.subTest(body=body[:40]):
                found = self.found(body)
                self.assertFalse(found['entry_override'])
                self.assertTrue(found['internship_experience'])
                self.assertEqual(found['hard_pass_reason'],
                                 'required_experience_over_2_years')

    def test_the_posting_that_is_an_internship_still_overrides(self):
        found = self.found('This internship runs for 12 weeks. 5 years of experience required.')
        self.assertTrue(found['entry_override'])
        self.assertFalse(found['internship_experience'])
        self.assertEqual(found['hard_pass_reason'], '')

    def test_a_slash_inside_a_term_of_the_trade_is_not_a_degree_alternative(self):
        """RTL/FPGA is one skill named two ways, not a bachelor's or a master's."""
        found = self.found('Requirements: BS with 5 years of RTL/FPGA verification '
                           'experience, MS with 2 years')
        self.assertEqual(found['effective_experience_years'], 5)
        self.assertEqual(found['hard_pass_reason'], 'required_experience_over_2_years')

    def test_a_slash_that_does_separate_the_two_paths_still_does(self):
        for body in ('BS+4 / MS+2', 'BS/MS with 2 years of experience'):
            with self.subTest(body=body):
                self.assertEqual(self.found(body)['hard_pass_reason'], '')


class UpperBoundTests(unittest.TestCase):
    """A ceiling or a denial is not a floor."""

    def test_a_maximum_is_not_a_minimum(self):
        for body in ('Requirements: fewer than 3 years of experience.',
                     'Required: no more than 5 years of industry experience.',
                     'Requirements: less than 4 years of professional experience.',
                     'Requirements: under 5 years of experience.',
                     'Requirements: up to 6 years of experience.',
                     'Requirements: no 3 years of professional experience needed.',
                     'Requirements: at most 4 years of experience.'):
            with self.subTest(body=body):
                found = experience.evaluate('ASIC Design Engineer', body)
                self.assertEqual(found['hard_pass_reason'], '', body)

    def test_a_floor_stated_in_the_negative_is_still_a_floor(self):
        """"No less than five years" is the strictest phrasing, not the absent one."""
        for body in ('Requirements: no less than 5 years of experience.',
                     'Required: not less than 4 years of industry experience.',
                     'Requirements: no fewer than 3 years of professional experience.'):
            with self.subTest(body=body):
                found = experience.evaluate('ASIC Design Engineer', body)
                self.assertEqual(found['hard_pass_reason'],
                                 'required_experience_over_2_years', body)

    def test_a_real_floor_is_still_a_floor(self):
        for body in ('Requirements: at least 3 years of experience.',
                     'Minimum 4 years of ASIC design experience.',
                     'Requirements: 3-5 years of RTL experience.',
                     'Requirements: 3+ years professional experience.'):
            with self.subTest(body=body):
                found = experience.evaluate('ASIC Design Engineer', body)
                self.assertEqual(found['hard_pass_reason'],
                                 'required_experience_over_2_years', body)
