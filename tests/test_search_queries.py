"""Migration contracts for the persistent search query catalog."""
import sqlite3
import unittest
from contextlib import closing
from jobdisco.query_catalog import MIGRATION, ROOT
from jobdisco.paths import CONFIG


class QueryCatalogTests(unittest.TestCase):
    def test_migration_preserves_edits_and_deletions(self):
        sql = MIGRATION.read_text(encoding='utf-8')
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript(sql)
            self.assertEqual(db.execute('SELECT count(*) FROM search_queries').fetchone()[0], 18)
            db.execute("UPDATE search_queries SET enabled=0, location='California' WHERE query_key='electrical_engineer'")
            db.execute("DELETE FROM search_queries WHERE query_key='hardware_engineer'")
            db.executescript(sql)
            self.assertEqual(db.execute('SELECT count(*) FROM search_queries').fetchone()[0], 17)
            self.assertEqual(db.execute("SELECT enabled, location FROM search_queries WHERE query_key='electrical_engineer'").fetchone(), (0, 'California'))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE search_queries SET tier=0")

    def test_fresh_schema_matches_migration(self):
        with closing(sqlite3.connect(':memory:')) as fresh, closing(sqlite3.connect(':memory:')) as migrated:
            fresh.executescript((CONFIG / 'schema.sql').read_text(encoding='utf-8'))
            migrated.executescript(MIGRATION.read_text(encoding='utf-8'))
            query = 'SELECT query_key, keyword, tier, sort_order FROM search_queries ORDER BY query_key'
            self.assertEqual(fresh.execute(query).fetchall(), migrated.execute(query).fetchall())
