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
        self.assertEqual(info, dict(entry_override=False, required_experience_years=4,
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

    def test_a_real_floor_is_still_a_floor(self):
        for body in ('Requirements: at least 3 years of experience.',
                     'Minimum 4 years of ASIC design experience.',
                     'Requirements: 3-5 years of RTL experience.',
                     'Requirements: 3+ years professional experience.'):
            with self.subTest(body=body):
                found = experience.evaluate('ASIC Design Engineer', body)
                self.assertEqual(found['hard_pass_reason'],
                                 'required_experience_over_2_years', body)
