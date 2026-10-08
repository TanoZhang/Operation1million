"""Employers that cap applications: a stricter filter, and the slots used.

Asked for on 2026-10-08. OpenAI refuses a sixth application in 180 days (its
Ashby posting says so), Amazon a candidate's eleventh active one, Google a
fourth in 30 days. A provider can be capped as a whole; Ashby is not, since
it lets each employer choose (see the configuration). A slot spent on a posting barely related to the
search is one the next good posting cannot have, so a capped employer's
posting has to be worth a slot to stay in the queue, and the page says how
many of the employer's slots are already used.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from .employers import display, identity
from .paths import CONFIG

PATH = CONFIG / 'application_limits.toml'
# The band of titles that name neither the trade nor its neighbourhood
# (`ranking.bucket`), never worth a capped slot whatever they score.
OTHER = 4


def load(path=PATH):
    with open(path, 'rb') as handle:
        rules = tomllib.load(handle)
    for item in rules.get('limit', ()):
        if ('employer' in item) == ('provider' in item):
            raise ValueError('An application limit names an employer or a provider, not both')
        if ('active' in item) == ('applications' in item and 'days' in item):
            raise ValueError('An application limit is a count of active applications or of applications per days')
    return rules


def _employers_on(db, providers):
    """Employers the index has seen post through a capped provider."""
    if not providers or not db or not Path(db).exists():
        return {}
    found = {}
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as con:
        if len({name for (name,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('jobs', 'companies')")}) < 2:
            return {}
        marks = ','.join('?' * len(providers))
        for name, provider in con.execute(
                f'''SELECT DISTINCT COALESCE(c.name, json_extract(j.raw, '$.employer_name'), j.company_key),
                           j.provider_key
                    FROM jobs j LEFT JOIN companies c USING(company_key)
                    WHERE j.provider_key IN ({marks})''', list(providers)):
            found.setdefault(identity(name), providers[provider])
    return found


def apply(state, db=None, rules=None, now=None):
    """Drop a capped employer's postings not worth a slot, and label the rest, in place."""
    rules = rules if rules is not None else load()
    now = now or datetime.now(timezone.utc)
    minimum = rules.get('filter', {}).get('min_confidence', 40)
    by_employer = {identity(item['employer']): item for item in rules.get('limit', ()) if 'employer' in item}
    by_provider = {item['provider']: item for item in rules.get('limit', ()) if 'provider' in item}
    capped = dict(_employers_on(db, by_provider))
    for name in ('pending', 'backlog', 'applied', 'skipped'):
        for group in state[name]:
            for job in group['jobs']:
                if job.get('provider_key') in by_provider:
                    capped.setdefault(identity(group['company']), by_provider[job['provider_key']])
    # A named employer's own cap wins over its provider's.
    capped.update(by_employer)

    def worth_a_slot(group):
        # A pasted posting is the user's own choice of where to spend one.
        return group.get('manual_import') or (group.get('bucket') != OTHER
                                              and (group.get('confidence') or 0) >= minimum)

    for name in ('pending', 'backlog'):
        state[name] = [group for group in state[name]
                       if identity(group['company']) not in capped or worth_a_slot(group)]

    applied = {}
    for group in state['applied']:
        applied.setdefault(identity(group['company']), []).append(group)
    labels = {}
    for name in ('pending', 'backlog'):
        for group in state[name]:
            key = identity(group['company'])
            if key not in capped:
                continue
            if key not in labels:
                labels[key] = _label(display(group['company']), capped[key], applied.get(key, ()), now)
            group['application_limit'] = labels[key]
    return state


def _label(company, limit, applied, now):
    if 'active' in limit:
        # Amazon frees a slot when an application is decided; a decline is the
        # only decision the ledger hears of, so a closed requisition still counts.
        used = sum(1 for group in applied if group.get('outcome') != 'declined')
        return (f"{company} allows {limit['active']} active applications; {used} applied and not declined"
                + _full(used, limit['active']))
    since = now - timedelta(days=limit['days'])
    used = 0
    for group in applied:
        try:
            at = datetime.fromisoformat(str(group.get('at')).replace('Z', '+00:00'))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        used += at >= since
    return (f"{company} allows {limit['applications']} applications per {limit['days']} days; {used} used"
            + _full(used, limit['applications']))


def _full(used, allowed):
    return ' -- full' if used >= allowed else ''
