"""Offline contracts for reusable answers and conservative heading learning."""
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jobdisco.answer_bank import AnswerBank, main


class AnswerBankTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bank = AnswerBank(self.root)
        self.bank.initialize()

    def observe(self, label, **kwargs):
        return self.bank.observe(label, site='https://careers.example.test/apply?token=private', **kwargs)

    def test_synonyms_share_one_updated_answer(self):
        self.bank.set_answer('name.first', 'Example')
        first = self.observe('First name')
        given = self.observe('  GIVEN   NAME: *')
        self.assertEqual(first['answer'], given['answer'])
        self.bank.set_answer('name.first', 'Updated')
        for item in (first, given):
            self.assertEqual(self.bank.resolve(item['question_id'])['answer'], 'Updated')

    def test_ambiguous_name_is_pending_until_explicit_binding(self):
        self.bank.set_answer('name.legal_full', 'Example Person')
        item = self.observe('Formal name')
        self.assertEqual(item['status'], 'unknown')
        self.assertIsNone(item['answer'])
        self.assertEqual(len(self.bank.pending()), 1)
        matched = self.bank.bind(item['question_id'], 'name.legal_full')
        self.assertEqual(matched['answer'], 'Example Person')
        self.assertEqual(self.observe('Formal name')['answer'], 'Example Person')
        self.assertEqual(self.bank.pending(), [])

    def test_repeated_unknowns_are_deduplicated_and_urls_are_not_retained(self):
        one = self.observe('Name')
        two = self.observe(' name: * ')
        self.assertEqual(one['question_id'], two['question_id'])
        self.assertEqual(self.bank.pending()[0]['observations'], 2)
        self.assertNotIn('token', self.bank.path.read_text())

    def test_binding_does_not_spread_to_other_sites_sections_or_controls(self):
        one = self.observe('Name', section='Applicant')
        self.bank.bind(one['question_id'], 'name.legal_full')
        self.bank.set_answer('name.legal_full', 'Example Person')
        cases = [self.observe('Name', section='Reference'),
                 self.bank.observe('Name', site='https://other.example.test', section='Applicant'),
                 self.observe('Name', section='Applicant', kind='select', options=['Example Person'])]
        self.assertTrue(all(case['status'] == 'unknown' for case in cases))

    def test_preferred_and_legal_names_are_distinct(self):
        self.bank.set_answer('name.legal_full', 'Example Person')
        self.assertEqual(self.observe('Preferred name')['status'], 'missing_answer')
        self.assertEqual(self.observe('Full legal name')['answer'], 'Example Person')
        self.assertEqual(self.observe('First name', section='Reference')['status'], 'unknown')

    def test_personal_fields_require_review_and_preserve_false(self):
        self.bank.add_field('personal.enrolled', 'Currently enrolled', 'boolean')
        self.bank.set_answer('personal.enrolled', False)
        item = self.observe('Currently enrolled?', kind='checkbox')
        self.assertEqual(self.bank.bind(item['question_id'], 'personal.enrolled')['status'], 'requires_review')
        self.assertIsNone(self.bank.resolve(item['question_id'])['answer'])
        state = json.loads(self.bank.path.read_text())
        self.assertIs(state['fields']['personal.enrolled']['answer'], False)

    def test_changed_options_and_negative_wording_require_new_binding(self):
        self.bank.add_field('personal.available', 'Available', 'choice', 'fill')
        self.bank.set_answer('personal.available', 'Yes')
        item = self.observe('Are you available?', kind='select', options=['Yes', 'No'])
        self.assertEqual(self.bank.bind(item['question_id'], 'personal.available')['status'], 'ready')
        self.assertEqual(self.observe('Are you available?', kind='select', options=['No', 'Yes'])['status'], 'ready')
        self.assertEqual(self.observe('Are you available?', kind='select', options=['Yes', 'No', 'Maybe'])['status'], 'unknown')
        self.assertEqual(self.observe('Are you NOT available?', kind='select', options=['Yes', 'No'])['status'], 'unknown')

    def test_answer_must_match_current_options_and_control(self):
        self.bank.set_answer('address.state', 'California')
        item = self.observe('State', kind='select', options=['CA', 'NY'])
        self.assertEqual(self.bank.bind(item['question_id'], 'address.state')['status'], 'option_mismatch')
        wrong = self.observe('Graduation year')
        self.bank.set_answer('education.graduation_year', 2028)
        self.assertEqual(self.bank.bind(wrong['question_id'], 'education.graduation_year')['status'], 'incompatible_control')

    def test_invalid_answers_and_rebinding_preserve_original_state(self):
        self.bank.set_answer('education.graduation_year', 2028)
        with self.assertRaises(ValueError):
            self.bank.set_answer('education.graduation_year', True)
        item = self.observe('First name')
        with self.assertRaises(ValueError):
            self.bank.bind(item['question_id'], 'name.last')
        self.assertEqual(self.bank.resolve(item['question_id'])['field_key'], 'name.first')

    def test_reinitialization_and_sqlite_rebuild_preserve_answers_and_bindings(self):
        self.bank.set_answer('name.first', 'Example')
        item = self.observe('First name')
        self.bank.initialize()
        self.bank.rebuild_index()
        self.bank.index.unlink()
        reopened = AnswerBank(self.root)
        reopened.rebuild_index()
        with closing(sqlite3.connect(reopened.index)) as db:
            self.assertEqual(json.loads(db.execute("SELECT answer_json FROM fields WHERE field_key='name.first'").fetchone()[0]), 'Example')
        self.assertEqual(reopened.resolve(item['question_id'])['answer'], 'Example')

    def test_interrupted_replacement_keeps_previous_authoritative_file(self):
        self.bank.set_answer('name.first', 'Original')
        before = self.bank.path.read_bytes()
        with patch('jobdisco.answer_bank.os.replace', side_effect=OSError('Injected failure')):
            with self.assertRaises(OSError):
                self.bank.set_answer('name.first', 'Lost')
        self.assertEqual(self.bank.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_corrupt_authoritative_file_is_not_silently_replaced(self):
        self.bank.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.bank.initialize()
        self.assertEqual(self.bank.path.read_text(), '{broken')

    def test_cli_initializes_real_database_and_registers_unknown(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--directory', str(self.root), 'init']), 0)
        self.assertTrue(Path(json.loads(output.getvalue())['index']).exists())
        with redirect_stdout(io.StringIO()) as output:
            main(['--directory', str(self.root), 'observe', 'Formal name', '--site', 'https://example.test'])
        self.assertEqual(json.loads(output.getvalue())['status'], 'unknown')

    def test_multiselect_and_clear_answer(self):
        self.bank.add_field('preferences.locations', 'Locations', 'multi_choice', 'fill')
        self.bank.set_answer('preferences.locations', ['Austin', 'San Diego'])
        item = self.observe('Locations', kind='multiselect', options=['Austin', 'San Diego', 'Santa Clara'])
        self.assertEqual(self.bank.bind(item['question_id'], 'preferences.locations')['answer'], ['Austin', 'San Diego'])
        self.bank.set_answer('preferences.locations', None)
        self.assertEqual(self.bank.resolve(item['question_id'])['status'], 'missing_answer')

    def test_sqlite_view_is_updated_after_each_observation_and_answer(self):
        item = self.observe('Formal name')
        self.bank.bind(item['question_id'], 'name.legal_full')
        self.bank.set_answer('name.legal_full', 'Example Person')
        with closing(sqlite3.connect(self.bank.index)) as db:
            self.assertEqual(db.execute('SELECT field_key FROM questions WHERE question_id=?',
                                       (item['question_id'],)).fetchone()[0], 'name.legal_full')
            self.assertEqual(json.loads(db.execute("SELECT answer_json FROM fields WHERE field_key='name.legal_full'").fetchone()[0]), 'Example Person')

    def test_failed_sqlite_refresh_preserves_saved_source_for_rebuild(self):
        with patch.object(self.bank, '_build_index', side_effect=OSError('Index busy')):
            with self.assertRaises(OSError):
                self.bank.set_answer('name.first', 'Saved')
        self.bank.rebuild_index()
        self.assertEqual(self.observe('First name')['answer'], 'Saved')

    def test_job_specific_answer_requires_matching_position_on_every_read(self):
        self.bank.add_field('internship.availability', 'Availability', 'choice', 'fill')
        self.bank.set_answer('internship.availability', 'Yes')
        question = self.observe('Available next summer?', kind='select', options=['Yes', 'No'])
        ident = question['question_id']
        self.assertEqual(self.bank.bind(ident, 'internship.availability', position_id='job-2027')['status'], 'ready')
        for context in (None, 'job-2028'):
            result = self.bank.resolve(ident, position_id=context)
            self.assertEqual(result['status'], 'position_context_required')
            self.assertIsNone(result['answer'])
            self.assertEqual(self.observe('Available next summer?', kind='select', options=['Yes', 'No'],
                                         position_id=context)['status'], 'position_context_required')
        self.assertEqual(self.bank.resolve(ident, position_id='job-2027')['answer'], 'Yes')
        with self.assertRaises(ValueError):
            self.bank.bind(ident, 'internship.availability', position_id='job-2028')
        self.assertEqual(self.bank.bind(ident, 'internship.availability')['status'], 'position_context_required')
        self.bank.rebuild_index()
        with closing(sqlite3.connect(self.bank.index)) as db:
            self.assertEqual(db.execute('SELECT required_position_id FROM questions WHERE question_id=?',
                                       (ident,)).fetchone()[0], 'job-2027')
