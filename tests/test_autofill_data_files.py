"""Lossless private split-data initialization with fictional source records."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('autofill_data_files', ROOT / 'application-autofill/data-files.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AutofillDataFilesTests(unittest.TestCase):
    def test_split_round_trip_preserves_extended_records_and_original_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.json'
            data = {'version': 1, 'fields': {'example.name': {'label': 'Example', 'type': 'text',
                    'policy': 'review', 'answer': 'Fictional Person'}},
                    'questions': {'q1': {'label': 'Example name', 'site': 'https://example.test',
                    'kind': 'text', 'options': [], 'field_key': 'example.name'}},
                    'education': [{'id': 'fictional-record', 'extra': {'preserve': True}}],
                    'extensions': {'future': [1, 2, 3]}}
            source.write_text(json.dumps(data), encoding='utf-8')
            directory = root / 'data'
            self.assertEqual(MODULE.initialize(directory, [source]), (1, 1, 0))
            self.assertEqual(MODULE.combine(directory), data)
            self.assertEqual(MODULE.read_json(directory / 'sources.json')['sources'][0]['document'], data)
            with self.assertRaisesRegex(ValueError, 'not empty'):
                MODULE.initialize(directory, [source])
            self.assertEqual(MODULE.combine(directory), data)

    def test_conflicting_source_is_archived_without_overwriting_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for number, answer in enumerate(('First fictional answer', 'Second fictional answer')):
                source = root / f'{number}.json'
                source.write_text(json.dumps({'version': 1, 'fields': {'example': {
                    'label': 'Example', 'type': 'text', 'policy': 'review', 'answer': answer}},
                    'questions': {}}), encoding='utf-8')
                sources.append(source)
            directory = root / 'data'
            self.assertEqual(MODULE.initialize(directory, sources), (1, 0, 1))
            self.assertEqual(MODULE.combine(directory)['fields']['example']['answer'], 'First fictional answer')
            self.assertEqual(MODULE.read_json(directory / 'conflicts.json')['conflicts'][0]['alternative']['answer'],
                             'Second fictional answer')
