"""Reject unreadable operational state before rotating a recovery copy."""
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
import sys


def validate(root):
    operational = root / 'operational'
    schemas = {
        'jsearch_usage.sqlite': {'credit_usage': {'period', 'day', 'used'},
                                'credit_events': {'at', 'credits'},
                                'account_pause': {'id', 'retry_at'},
                                'backfill_cursor': {'period', 'query_key', 'page', 'exhausted'}},
        'source_access.sqlite': {'source_pauses': {'company_key', 'retry_at', 'reason'}},
    }
    for name, tables in schemas.items():
        with closing(sqlite3.connect((operational / name).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError(f'{name}: failed integrity check')
            for table, required in tables.items():
                columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
                if not required <= columns:
                    raise ValueError(f'{name}: missing {table} schema')
    with (operational / 'applications.ndjson').open(encoding='utf-8') as handle:
        for line in handle:
            event = json.loads(line)
            if (not isinstance(event, dict) or not line.endswith('\n')
                    or event.get('status') not in {'applied', 'skipped', 'pending'}
                    or not event.get('url') or not event.get('at')):
                raise ValueError('Invalid application ledger event')
    with gzip.open(operational / 'seen_jobs.ndjson.gz', 'rt', encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if (not isinstance(event, dict) or not event.get('provider_key')
                    or not event.get('source_job_id') or not event.get('first_seen')
                    or not event.get('last_seen')):
                raise ValueError('Invalid seen snapshot row')


if __name__ == '__main__':
    validate(Path(sys.argv[1]))
