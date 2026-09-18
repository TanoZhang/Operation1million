"""Append-only application decisions, independent of the disposable job index."""
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unicodedata
import uuid

from .paths import DB, DATA


def ledger_path():
    return Path(os.environ.get('JOBDISCO_STORE', DATA / 'store')) / 'operational/applications.ndjson'


def group_key(company, title):
    normalize = lambda value: ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    return hashlib.sha256(json.dumps([normalize(company), normalize(title)]).encode()).hexdigest()


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def read_events(path):
    if not path.exists():
        return []
    events = []
    with path.open(encoding='utf-8') as handle:
        for number, line in enumerate(handle, 1):
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or not line.endswith('\n') or event['status'] not in {'applied', 'skipped', 'pending'}:
                    raise ValueError('Invalid event')
                if not event.get('url') or not event.get('at'):
                    raise ValueError('Missing event identity')
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f'Invalid application ledger at line {number}; preserve the file for recovery') from exc
            events.append(event)
    return events


def append_decision(path, group, status, reason=''):
    if status not in {'applied', 'skipped', 'pending'}:
        raise ValueError('Invalid application status')
    if not isinstance(reason, str) or len(reason) > 2000:
        raise ValueError('Reason must be at most 2000 characters')
    event = {'id': uuid.uuid4().hex, 'url': group['jobs'][0]['url'],
             'at': datetime.now(timezone.utc).isoformat(), 'status': status,
             'reason': reason.strip(), 'group_id': group['id'], 'group': group}
    with locked(path):
        read_events(path)
        with path.open('ab') as handle:
            handle.write((json.dumps(event, ensure_ascii=True) + '\n').encode())
            handle.flush()
            os.fsync(handle.fileno())
    return event


def queue(db_path=DB, path=None, now=None):
    """Replay decisions each time; rebuilding SQLite cannot erase them."""
    path = path or ledger_path()
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=3)).isoformat()
    with locked(path):
        events = read_events(path)
    group_states, url_states = {}, {}
    for event in events:
        if event.get('group_id'):
            group_states[event['group_id']] = event
        url_states[event['url']] = event
        for job in event.get('group', {}).get('jobs', []):
            url_states[job['url']] = event
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    groups, legacy_history = {}, []
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        select = '''SELECT j.url, j.company_key,
                            COALESCE(c.name, json_extract(j.raw, '$.employer_name'), j.company_key) AS company,
                            j.title, j.location, j.first_seen, j.posted_at, j.provider_key,
                            COALESCE(j.relevance, 0) AS confidence
                            FROM jobs j LEFT JOIN companies c USING(company_key)'''
        rows = db.execute(select + ''' WHERE j.closed_at IS NULL AND julianday(j.first_seen) >= julianday(?)
                            AND julianday(j.first_seen) <= julianday(?)
                            ORDER BY confidence DESC, j.first_seen DESC, j.url''', (since, now.isoformat()))
        for row in rows:
            job = dict(row)
            key = group_key(job['company_key'], job['title'])
            group = groups.setdefault(key, {'id': key, 'company': job['company'], 'title': job['title'],
                                           'confidence': job['confidence'], 'jobs': []})
            group['jobs'].append(job)
        for url, event in url_states.items():
            if event.get('group_id') or event['status'] == 'pending':
                continue
            row = db.execute(select + ' WHERE j.url=?', (url,)).fetchone()
            if row:
                job = dict(row)
                legacy_history.append((event['status'], {
                    'id': 'legacy:' + hashlib.sha256(url.encode()).hexdigest(),
                    'company': job['company'], 'title': job['title'], 'confidence': job['confidence'],
                    'jobs': [job], 'at': event['at'], 'reason': event.get('reason', '')}))
    result = {'pending': [], 'applied': [], 'skipped': [], 'ledger': str(path.resolve())}
    for key, group in groups.items():
        decision = group_states.get(key)
        if decision and decision['status'] != 'pending':
            continue
        group['jobs'] = [job for job in group['jobs']
                         if url_states.get(job['url'], {}).get('status', 'pending') == 'pending']
        if group['jobs']:
            result['pending'].append(group)
    for key, event in group_states.items():
        if event['status'] != 'pending':
            result[event['status']].append(dict(event['group'], at=event['at'], reason=event.get('reason', '')))
    for status, group in legacy_history:
        result[status].append(group)
    for status in ('applied', 'skipped'):
        result[status].sort(key=lambda group: group['at'], reverse=True)
    return result
