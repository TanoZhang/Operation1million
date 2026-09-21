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
from pathlib import Path
import sys

from . import jsearch
from .jsearch_access import RequestGuard


def usage(path, settings=None):
    """What this ledger says was spent this billing period and this budget day."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'No credit ledger at {path}')
    settings = settings or jsearch.load_plan()[0]
    guard = RequestGuard(path=path,
                         target_limit=settings['monthly_target'],
                         cycle_start=settings['cycle_start'],
                         cycle_days=settings['cycle_days'],
                         day_zone=settings['budget_timezone'],
                         day_resets_at=settings['budget_day_resets_at'])
    balance = guard.balance()
    return {'period': balance['period_used'], 'day': balance['day_used']}


def credits_recorded(path, settings=None):
    """Return credits this ledger says were spent in the current period.

    Opening a ledger creates it. That is right for a pass, which needs somewhere
    to record what it spends, and wrong for a check, which must not manufacture
    the very thing it is asking about: a missing published ledger would be
    created empty, compare equal-or-below the local one, and report that all was
    well. So a check reads only what is already there.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'No credit ledger at {path}')
    settings = settings or jsearch.load_plan()[0]
    guard = RequestGuard(path=path,
                         target_limit=settings['monthly_target'],
                         cycle_start=settings['cycle_start'],
                         cycle_days=settings['cycle_days'],
                         day_zone=settings['budget_timezone'],
                         day_resets_at=settings['budget_day_resets_at'])
    return guard.balance()['period_used']


def compare(local, published, settings=None):
    """Return (local_used, published_used, ok) for the billing period.

    B64: `ok` also requires the local ledger to know the current budget day's
    spend. The two clocks differ on purpose, so a budget day can hold credits
    from the previous billing period -- just after the UTC cycle rolls, before
    the Pacific day does. A ledger that had lost those events compared equal
    on the period, zero against zero, and was allowed to spend the day's
    allocation a second time.
    """
    settings = settings or jsearch.load_plan()[0]
    here, there = usage(local, settings), usage(published, settings)
    ok = here['period'] >= there['period'] and here['day'] >= there['day']
    return here['period'], there['period'], ok


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print('usage: python -m jobdisco.ledger_guard <local> <published>', file=sys.stderr)
        return 64
    try:
        here, there, ok = compare(argv[0], argv[1])
    except FileNotFoundError as exc:
        print(f'REFUSING TO COLLECT: {exc}. A pass cannot know what it has '
              f'already spent without one.', file=sys.stderr)
        return 1
    if ok:
        print(f'credit ledger ok: local {here} >= published {there}')
        return 0
    day_here, day_there = usage(argv[0])['day'], usage(argv[1])['day']
    if here >= there:
        print(f'REFUSING TO COLLECT: the local credit ledger records {day_here} credits '
              f'for the current budget day but the published one records {day_there}. '
              f'They agree on the billing period, which has just rolled over; the local '
              f'ledger has lost charges that still count against today. Restore it from '
              f'the data repository:\n    cp {argv[1]} {argv[0]}', file=sys.stderr)
        return 1
    print(f'REFUSING TO COLLECT: the local credit ledger records {here} credits this '
          f'period but the published one records {there}. The local ledger has lost '
          f'charges the provider has already counted, and collecting against it would '
          f'spend them again. Restore it from the data repository:\n'
          f'    cp {argv[1]} {argv[0]}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
