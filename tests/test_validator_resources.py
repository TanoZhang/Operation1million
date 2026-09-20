"""Catalog reads release SQLite resources on both success and failure."""
import sqlite3
import unittest
from unittest.mock import patch

from jobdisco import validate_sources


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
