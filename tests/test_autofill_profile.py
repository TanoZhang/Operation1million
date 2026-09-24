"""Offline contracts for the extension's ignored local profile seed."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'application_autofill_profile', ROOT / 'application-autofill/prepare-profile.py')
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class AutofillProfileTests(unittest.TestCase):
    def test_profile_copy_is_atomic_and_lossless(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'answers.json'
            target = root / 'local-profile.json'
            data = {'version': 1,
                    'fields': {'name.first': {'answer': 'Example'}},
                    'questions': {'question': {'field_key': 'name.first'}}}
            source.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(PROFILE.copy_profile(source, target), (1, 1))
            self.assertEqual(json.loads(target.read_text()), data)
            self.assertEqual(list(root.glob('profile-*')), [])

    def test_damaged_profile_is_refused_without_replacing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'answers.json'
            target = root / 'local-profile.json'
            source.write_text('{}', encoding='utf-8')
            target.write_text('preserve', encoding='utf-8')
            with self.assertRaises(ValueError):
                PROFILE.copy_profile(source, target)
            self.assertEqual(target.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
