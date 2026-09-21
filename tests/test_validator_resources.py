"""Catalog reads release SQLite resources on both success and failure."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jobdisco import validate_sources


class ValidatorReportTests(unittest.TestCase):
    """A run that probed every source must have somewhere to put its answer."""

    def test_the_report_directory_exists_before_the_first_probe(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary) / 'raw' / 'source_validation_results.csv'
            fixture = SimpleNamespace(source_id='fixture')
            probed = []

            def probe(source, session):
                # The directory is gitignored, so a fresh checkout lacks it. Made
                # at the write instead of here, an hour of probes ended by
                # throwing away the report they were run to produce.
                self.assertTrue(out.parent.is_dir(),
                                'the report directory must exist before any request')
                probed.append(source)
                return {'source_id': 'fixture', 'verdict': 'usable'}

            with patch.object(validate_sources, 'OUT_CSV', out), \
                 patch.object(validate_sources, 'load_sources', return_value=[fixture]), \
                 patch.object(validate_sources, 'validate', probe):
                self.assertEqual(validate_sources.main(), 0)
            self.assertEqual(probed, [fixture])
            self.assertIn('usable', out.read_text(encoding='utf-8'))


class ValidatorResourcesTests(unittest.TestCase):
    def test_catalog_connection_closes_after_read_or_decode_failure(self):
        for payload in ('{}', '{broken'):
            with self.subTest(payload=payload):
                connection = sqlite3.connect(':memory:')
                self.addCleanup(connection.close)
                connection.executescript('''
                    CREATE TABLE companies (company_key TEXT, name TEXT);
                    INSERT INTO companies VALUES ('fixture', 'Fixture');
                    CREATE TABLE company_sources (
                        source_instance_id TEXT, company_key TEXT, provider_key TEXT,
                        access_url TEXT, instance_fields_json TEXT, enabled INTEGER);
                    CREATE TABLE company_direct_sources (
                        direct_source_id TEXT, company_key TEXT, provider_key TEXT,
                        access_url TEXT, instance_fields_json TEXT, enabled INTEGER);
                    INSERT INTO company_direct_sources VALUES (
                        'direct', 'fixture', 'apple', 'https://example.test/direct', '{}', 1);
                    INSERT INTO company_sources VALUES (
                        'disabled', 'fixture', 'ashby', 'https://example.test/off', '{}', 0);
                ''')
                connection.execute(
                    'INSERT INTO company_sources VALUES (?, ?, ?, ?, ?, 1)',
                    ('fixture', 'fixture', 'greenhouse', 'https://example.test', payload))
                with patch.object(validate_sources.sqlite3, 'connect', return_value=connection):
                    if payload == '{}':
                        sources = validate_sources.load_sources()
                        self.assertEqual([s.source_id for s in sources], ['fixture', 'direct'])
                        self.assertEqual([s.table_name for s in sources],
                                         ['company_sources', 'company_direct_sources'])
                        self.assertEqual(sources[0].fields, {})
                    else:
                        with self.assertRaises(ValueError):
                            validate_sources.load_sources()
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute('SELECT 1')
