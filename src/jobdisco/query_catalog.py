"""Initialize and read the SQLite search keyword catalog without paid requests."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from .paths import ROOT, DB, CONFIG

MIGRATION = CONFIG / 'migrations/001_search_queries.sql'


def migrate(path=DB):
    if not path.exists():
        raise FileNotFoundError('Existing job catalog database required')
    with closing(sqlite3.connect(path)) as db:
        # Back up before the first migration, including the existing source catalog.
        applied = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_queries'").fetchone()
        if not applied:
            backup = ROOT / '.local/backups/job_discovery_before_search_queries.sqlite'
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                raise FileExistsError('Migration backup already exists; inspect it before retrying')
            with closing(sqlite3.connect(backup)) as destination:
                db.backup(destination)
        db.executescript(MIGRATION.read_text(encoding='utf-8'))


def load_queries(path=DB):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            'SELECT * FROM search_queries WHERE enabled=1 ORDER BY tier, sort_order, query_key')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--migrate', action='store_true')
    args = parser.parse_args()
    if args.migrate:
        migrate(args.db)
    for row in load_queries(args.db):
        print(f"{row['query_key']} | tier={row['tier']} | {row['keyword']} | {row['location']}")


if __name__ == '__main__':
    main()
