"""Keep sweep progress consistent with the job history published by Actions."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def restore_cursors(ledger, baseline):
    """Discard unpublished progress without refunding credits or cooldowns."""
    rows = []
    if Path(baseline).exists():
        with closing(sqlite3.connect(baseline)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='backfill_cursor'").fetchone():
                rows = db.execute('SELECT * FROM backfill_cursor').fetchall()
    if not Path(ledger).exists():
        return
    with closing(sqlite3.connect(ledger)) as db, db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='backfill_cursor'").fetchone():
            db.execute('DELETE FROM backfill_cursor')
            db.executemany('INSERT INTO backfill_cursor VALUES (?, ?, ?, ?, ?)', rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('baseline', type=Path)
    args = parser.parse_args()
    restore_cursors(args.ledger, args.baseline)


if __name__ == '__main__':
    main()
