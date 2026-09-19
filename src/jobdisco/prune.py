"""Keep the published log to a rolling window.

The log is a backup, not the working state: the VPS keeps the derived SQLite and
the point of the thing is to apply to what is open today. A posting lost from
deep history is a posting that would have closed, and anything genuinely missed
is collected again on the next pass rather than recovered from an archive.

What this deliberately does not preserve: a rebuild from a pruned log
reconstructs only what the window holds. `seen`, `closed` and `score` events are
UPDATE statements, so a posting whose full job line lived in a pruned file is
not recreated by the events that follow it -- it is simply absent. That is the
accepted cost, and it is why pruning must never be allowed to trigger an
automatic rebuild of a live database.

What is never pruned: everything under `operational/`. The credit ledger, the
cooldowns and the applications log are records of decisions and of money, not of
the world, and nothing regenerates them.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys

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


def prune(store, keep_days=KEEP_DAYS, today=None, dry_run=False):
    """Delete whole days that fall outside the window. Returns what it removed."""
    kept, removable = plan(store, keep_days, today)
    if not dry_run:
        for path in removable:
            path.unlink()
    return {'kept_days': kept, 'removed': [str(p) for p in removable],
            'removed_days': sorted({day_of(p) for p in removable})}


def main(argv=None):
    import argparse
    from .paths import DATA
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path,
                        default=Path(os.environ.get('JOBDISCO_STORE', DATA / 'store')))
    parser.add_argument('--keep', type=int, default=KEEP_DAYS,
                        help=f'Days of log to keep, including today (default {KEEP_DAYS})')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.keep < 1:
        parser.error('--keep must be at least 1')
    result = prune(args.store, args.keep, dry_run=args.dry_run)
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
