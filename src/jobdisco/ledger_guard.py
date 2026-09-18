"""Refuse to collect behind a credit ledger that has gone backwards.

On a machine that keeps its disk the local ledger is authoritative: it records
what has already been charged, and a pass whose push failed leaves it ahead of
the copy published to the data repository. It may be ahead. It may never be
behind -- being behind means it has lost charges the provider has already
counted, and collecting against it would spend those credits a second time.

The obvious check, "is the file there and non-empty", does not catch this. A
ledger created by an interrupted run, a restore from the wrong place, or a
diagnostic that opened the path and built the schema is a perfectly valid
SQLite file of several kilobytes with nothing in it. It passes every test but
the only one that matters, which is whether it still knows what was spent.
"""
import sys

from . import jsearch
from .jsearch_access import RequestGuard


def credits_recorded(path, settings=None):
    """Return credits this ledger says were spent in the current period."""
    settings = settings or jsearch.load_plan()[0]
    guard = RequestGuard(path=path,
                         target_limit=settings['monthly_target'],
                         cycle_start=settings['cycle_start'],
                         cycle_days=settings['cycle_days'])
    return guard.balance()['period_used']


def compare(local, published, settings=None):
    """Return (local_used, published_used, ok)."""
    settings = settings or jsearch.load_plan()[0]
    here = credits_recorded(local, settings)
    there = credits_recorded(published, settings)
    return here, there, here >= there


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print('usage: python -m jobdisco.ledger_guard <local> <published>', file=sys.stderr)
        return 64
    here, there, ok = compare(argv[0], argv[1])
    if ok:
        print(f'credit ledger ok: local {here} >= published {there}')
        return 0
    print(f'REFUSING TO COLLECT: the local credit ledger records {here} credits this '
          f'period but the published one records {there}. The local ledger has lost '
          f'charges the provider has already counted, and collecting against it would '
          f'spend them again. Restore it from the data repository:\n'
          f'    cp {argv[1]} {argv[0]}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
