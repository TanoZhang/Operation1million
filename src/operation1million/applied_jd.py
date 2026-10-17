"""Every Applied entry has its description (the user, 2026-10-16).

Half of Applied showed no description: Muse imported submissions as
`muse.invalid` entries, applied to postings that closed, or to boards with no
detail reader. What the index cannot give, Muse is asked for. Each pass writes
the entries still without one (`applied-missing-jd.csv` / `.json`, by group
id), and reads what Muse returns (`job-applications/applied-jds.jsonl`) into
`applied_descriptions.ndjson` beside the ledger, which Review shows when the
index has nothing better.

A supplied description is bound to one Applied entry by its group id, by one
of its links, or by its employer and requisition when exactly one entry has
both -- never by title, which matched the wrong posting six times out of
fourteen when Gmail declines were sorted (2026-10-13).
"""
import argparse
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import sqlite3

from . import applications
from .job_text import display_description, readable_text

# Less than this is a heading or an excerpt, not a description to apply from.
MINIMUM = 200
MISSING_COLUMNS = ('Group', 'Company', 'Title', 'Location', 'Requisition', 'Link', 'Applied')


def path_for(ledger):
    return Path(ledger).with_name('applied_descriptions.ndjson')


def read(ledger):
    """The latest supplied description per group id."""
    return {record['group_id']: record for record in applications.read_records(path_for(ledger))
            if record.get('group_id') and readable_text(record.get('description') or '').strip()}


def shown(con, url, decided):
    """What Review shows for the posting at `url` under a decision: (text, kind).

    `decided` is the decision's own copy of the job, or None. The same reading
    the description endpoint gives, so the missing list says what the page shows.
    """
    if decided and decided.get('manual_import'):
        return readable_text(decided.get('manual_description') or '').strip(), 'manual'
    row = None
    if con is not None:
        row = con.execute('SELECT raw, company_key, provider_key, source_job_id, title, location '
                          'FROM jobs WHERE url=?', (url,)).fetchone()
        if row is not None and decided is not None and (
                not applications.describes_decision(con, url, dict(row), decided)):
            return '', 'replaced'
    raw = json.loads(row['raw'] or '{}') if row else {}
    description, kind = display_description(raw)
    return readable_text(str(description)).strip(), kind


def lacking(text, kind):
    """Whether this is short of a description to apply from."""
    return len(text) < MINIMUM or kind in ('excerpt', 'discovery', 'replaced')


def missing(state, db, supplied):
    """Applied groups whose every listing lacks a description and none was supplied."""
    con = None
    if db and Path(db).exists():
        con = sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
    try:
        out = []
        for group in state['applied']:
            if group['id'] in supplied:
                continue
            if all(lacking(*shown(con, job['url'], job)) for job in group['jobs']):
                out.append(group)
        return out
    finally:
        if con is not None:
            con.close()


def write_missing(folder, groups):
    """`applied-missing-jd.csv` and `.json` in `folder`, rewritten. Returns the row count."""
    from .export import _replace
    table = []
    for group in groups:
        job = next((j for j in group['jobs'] if not j['url'].startswith('https://muse.invalid/')),
                   group['jobs'][0])
        imported = next((j for j in group['jobs'] if j.get('manual_import')), job)
        table.append([group['id'], group.get('company') or '', group.get('title') or '',
                      job.get('location') or '', imported.get('source_job_id') or job.get('source_job_id') or '',
                      job['url'], (group.get('at') or '')[:10]])
    out = StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(MISSING_COLUMNS)
    writer.writerows(table)
    _replace(Path(folder) / 'applied-missing-jd.csv', out.getvalue())
    _replace(Path(folder) / 'applied-missing-jd.json', json.dumps(
        {'rows': len(table), 'answer_in': 'job-applications/applied-jds.jsonl',
         'answer_format': {'group_id': 'Group', 'description': 'the full JD text'},
         'listings': [dict(zip(MISSING_COLUMNS, row)) for row in table]},
        ensure_ascii=False, indent=1) + '\n')
    return len(table)


def _applied(ledger):
    """The groups whose latest decision is Applied, by id."""
    with applications.locked(ledger):
        events = applications.read_events(ledger)
    latest = {}
    for event in events:
        latest[event.get('group_id') or event['url']] = event
    return {ident: event.get('group') or {} for ident, event in latest.items() if event['status'] == 'applied'}


def match(record, applied):
    """(group id, how) for a supplied record, or (None, why not)."""
    ident = str(record.get('group_id') or '').strip()
    if ident:
        return (ident, 'group id') if ident in applied else (None, 'no Applied entry has this group id')
    url = str(record.get('url') or '').strip()
    if url:
        found = [i for i, g in applied.items() if any(j.get('url') == url for j in g.get('jobs') or ())]
        if len(found) == 1:
            return found[0], 'link'
        if found:
            return None, 'several Applied entries have this link'
    requisition = str(record.get('requisition') or '').strip().upper()
    company = applications.employer_name(record.get('company') or '')
    if requisition and company:
        found = [i for i, g in applied.items()
                 if applications.employer_name(g.get('company') or '') == company
                 and any(str(j.get('source_job_id') or '').strip().upper() == requisition
                         for j in g.get('jobs') or ())]
        if len(found) == 1:
            return found[0], 'employer and requisition'
        if found:
            return None, 'several Applied entries have this employer and requisition'
    return None, 'no group id, link or employer and requisition matched'


def import_supplied(source, ledger):
    """Append each new, matched description from `source`. Returns (written, refused)."""
    applied = _applied(ledger)
    known = read(ledger)
    written, refused = 0, []
    for number, record in enumerate(applications.read_records(source), 1):
        text = readable_text(str(record.get('description') or '')).strip()
        if len(text) < MINIMUM:
            refused.append((number, f'description shorter than {MINIMUM} characters'))
            continue
        ident, how = match(record, applied)
        if ident is None:
            refused.append((number, how))
            continue
        if known.get(ident, {}).get('description') == record['description']:
            continue
        event = {'group_id': ident, 'description': record['description'], 'matched': how,
                 'by': str(record.get('by') or 'muse'), 'at': datetime.now(timezone.utc).isoformat()}
        path = path_for(ledger)
        with applications.locked(path):
            applications._append_line(path, event)
        known[ident] = event
        written += 1
    return written, refused


def main():
    parser = argparse.ArgumentParser(description="Read the descriptions Muse supplied for Applied entries.")
    parser.add_argument('source', type=Path, help='job-applications/applied-jds.jsonl')
    parser.add_argument('--ledger', type=Path, default=None)
    args = parser.parse_args()
    ledger = args.ledger or applications.ledger_path()
    written, refused = import_supplied(args.source, ledger)
    print(f'{args.source}: {written} descriptions added, {len(refused)} not matched', flush=True)
    for number, why in refused[:20]:
        print(f'  line {number}: {why}', flush=True)


if __name__ == '__main__':
    main()
