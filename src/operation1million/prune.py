"""Keep the published log to a rolling window.

The log is a backup, not the working state: the VPS keeps the derived SQLite and
the point of the thing is to apply to what is open today. A posting lost from
deep history is a posting that would have closed, and anything genuinely missed
is collected again on the next pass rather than recovered from an archive.

What this deliberately does not preserve: a rebuild from a pruned log
reconstructs only what the window holds. `seen`, `closed` and `score` events are
UPDATE statements, so a posting whose full job line lived in a pruned file is
not recreated by the events that follow it -- it is simply absent.

That was once called the accepted cost, on the reading that pruning would never
trigger a rebuild. It does: the daily pass rebuilds whenever `data/config`
changes, and by 2026-10-04 the live index had lost 2,136 postings that had
never closed, 579 of them scoring 50 or more, among them 36 Micron openings
applied to that week (#318). So a posting still open is never left to live
only in a day about to go: `carry_forward` writes its current row into today's
log first, and a rebuild from the window holds everything open.

What is never pruned: everything under `operational/`. The credit ledger, the
cooldowns and the applications log are records of decisions and of money, not of
the world, and nothing regenerates them.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import re
import sys

from .paths import DATA, DB

KEEP_DAYS = 14

# runs/2026-09-18.ndjson.gz and its shards, runs/2026-09-18-0001.ndjson.gz
DAY = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:-\d{4})?$')


def day_of(path):
    """The calendar day a log or manifest file belongs to, or None."""
    name = path.name.split('.', 1)[0]
    found = DAY.match(name)
    return found.group(1) if found else None


def plan(store, keep_days=KEEP_DAYS, today=None):
    """Return (kept_days, removable_paths) without touching anything.

    A day is kept or dropped whole: a run file and its manifest are a matched
    pair, and dropping one without the other leaves a store that fails its own
    verification.
    """
    store = Path(store)
    today = today or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    cutoff = (datetime.strptime(today, '%Y-%m-%d').replace(tzinfo=timezone.utc)
              - timedelta(days=keep_days - 1)).strftime('%Y-%m-%d')

    by_day = {}
    for folder, pattern in (('runs', '*.ndjson.gz'), ('manifests', '*.json')):
        for path in sorted((store / folder).glob(pattern)):
            day = day_of(path)
            if day:
                by_day.setdefault(day, []).append(path)

    kept = sorted(day for day in by_day if day >= cutoff)
    # Never prune everything. A store with no log at all cannot be rebuilt into
    # anything, and an empty window is far more likely to be a clock or
    # configuration mistake than an intention.
    if not kept and by_day:
        kept = [max(by_day)]
    removable = [path for day, paths in sorted(by_day.items())
                 if day not in kept for path in paths]
    return kept, removable


def job_urls(paths):
    """Every URL a job line in these run files describes."""
    urls = set()
    for path in paths:
        if not path.name.endswith('.ndjson.gz'):
            continue
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            for line in handle:
                if '"type": "job"' in line:
                    urls.add(json.loads(line)['url'])
    return urls


def carry_forward(store, removable, db_path):
    """Write today the open postings whose only job line is in a day about to go.

    Their current row, from the index, so a rebuild from the window recreates
    them with the first_seen they already had (#318). Returns how many.
    """
    from . import store as job_store
    kept = [path for path in (Path(store) / 'runs').glob('*.ndjson.gz') if path not in removable]
    leaving = sorted(job_urls(removable) - job_urls(kept))
    if not leaving:
        return 0
    if db_path is None or not Path(db_path).is_file():
        # Pruning without carrying forward is how the index lost what was open.
        raise FileNotFoundError(f'no index at {db_path}; nothing pruned')
    # Into the store being pruned, which history compaction stages apart from
    # the one OPERATION1MILLION_STORE names.
    written_to = job_store.LOG
    job_store.LOG = Path(store)
    try:
        with closing(job_store.connect(db_path)) as db:
            still_open = []
            for chunk in job_store.chunks(leaving):
                still_open.extend(url for (url,) in db.execute(
                    'SELECT url FROM jobs WHERE closed_at IS NULL AND url IN (%s)'
                    % ','.join('?' * len(chunk)), chunk))
            job_store.append_log(db, still_open, [], job_store.now())
    finally:
        job_store.LOG = written_to
    return len(still_open)


def prune(store, keep_days=KEEP_DAYS, today=None, dry_run=False, db_path=None):
    """Delete whole days that fall outside the window. Returns what it removed.

    The open postings those days alone describe are carried into today's log
    first, from the index at `db_path`; a failure there removes nothing.
    """
    kept, removable = plan(store, keep_days, today)
    carried = 0
    if not dry_run:
        if removable:
            carried = carry_forward(store, removable, db_path)
        for path in removable:
            path.unlink()
    return {'kept_days': kept, 'removed': [str(p) for p in removable],
            'removed_days': sorted({day_of(p) for p in removable}), 'carried': carried}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path,
                        default=Path(os.environ.get('OPERATION1MILLION_STORE', DATA / 'store')))
    parser.add_argument('--keep', type=int, default=KEEP_DAYS,
                        help=f'Days of log to keep, including today (default {KEEP_DAYS})')
    parser.add_argument('--db', type=Path, default=DB,
                        help='The index whose open postings are carried forward')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.keep < 1:
        parser.error('--keep must be at least 1')
    result = prune(args.store, args.keep, dry_run=args.dry_run, db_path=args.db)
    if result['carried']:
        print(f"carried {result['carried']} open postings into today's log")
    verb = 'would remove' if args.dry_run else 'removed'
    if result['removed_days']:
        print(f"{verb} {len(result['removed'])} files over "
              f"{len(result['removed_days'])} days: {', '.join(result['removed_days'])}")
    else:
        print('nothing outside the window')
    print(f"keeping {len(result['kept_days'])} days: "
          f"{result['kept_days'][0]}..{result['kept_days'][-1]}"
          if result['kept_days'] else 'keeping nothing')
    return 0


if __name__ == '__main__':
    sys.exit(main())
