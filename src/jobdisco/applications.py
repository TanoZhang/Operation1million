"""Append-only application decisions, independent of the disposable job index."""
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .paths import DB, DATA
from .job_text import clean_title
from . import jsearch, ranking


def ledger_path():
    return Path(os.environ.get('JOBDISCO_STORE', DATA / 'store')) / 'operational/applications.ndjson'


def decision_key(job):
    """One requisition: what a decision may cover, and nothing wider.

    Company and title used to be the identity, on the reasoning that one role
    advertised in eleven locations should not be answered eleven times. It is
    the right thought about the wrong rows. Measured on the live queue, 1,656
    groups held more jobs than locations -- Apple's Design Verification
    Engineer was 48 postings across 14 locations, so at least 34 of them were
    separate requisitions -- and skipping that group once would have silently
    buried all 48.

    So the identity is the provider's requisition id, scoped the same way the
    store scopes job_identities: JSearch ids are provider-wide, while direct
    source ids are only guaranteed within that company's board. The url is used
    only where a provider publishes no id of its own. Several rows may still
    share a decision, but only when they carry the same scoped id, which is the
    one case where they are provably the same opening. The cost is that a role
    genuinely listed once per location now appears once per location; showing a
    posting twice is recoverable, and hiding one is not.
    """
    provider = job.get('provider_key') or ''
    requisition = str(job.get('source_job_id') or '').strip() or job['url']
    scope = '' if provider == 'jsearch' else (job.get('company_key') or '')
    return hashlib.sha256(
        json.dumps([provider, scope, requisition]).encode()).hexdigest()


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
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    for order, event in enumerate(events):
        event = dict(event, replay_order=order)
        # Replay old snapshots through the same normalization without rewriting
        # the append-only ledger or losing decisions made before title cleanup.
        snapshot = event.get('group')
        if snapshot and snapshot.get('jobs') and not event.get('group_id', '').startswith('legacy:'):
            # Old title groups may contain several requisitions. Split every
            # snapshot so each retains its decision across URL changes and can
            # be reopened independently, without rewriting the ledger.
            requisitions = {}
            for job in snapshot['jobs']:
                requisitions.setdefault(decision_key(job), []).append(job)
            for key, jobs in requisitions.items():
                first = jobs[0]
                title = clean_title(snapshot['title'], first.get('location', ''))
                group_states[key] = dict(event, group_id=key, group=dict(
                    snapshot, id=key, title=title, jobs=jobs))
            continue
        # Only records without a scoped snapshot may fall back to URL identity.
        # Applying a modern decision by URL too hides a replacement requisition
        # when a board reuses an address.
        url_states[event['url']] = event
        for job in event.get('group', {}).get('jobs', []):
            url_states[job['url']] = event

    def decision_for(job):
        candidates = [event for event in (
            group_states.get(decision_key(job)), url_states.get(job['url'])) if event]
        return max(candidates, key=lambda event: event['replay_order'], default=None)
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    groups, backlog, legacy_history = {}, {}, []
    rules = jsearch.load_plan()[0]['filter']
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        select = '''SELECT j.url, j.company_key, j.source_job_id,
                            COALESCE(c.name, json_extract(j.raw, '$.employer_name'), j.company_key) AS company,
                            j.title, j.location, j.first_seen, j.posted_at, j.provider_key,
                            COALESCE(j.relevance, 0) AS confidence, j.raw
                            FROM jobs j LEFT JOIN companies c USING(company_key)'''

        # Both checks are pure functions of a string, and the strings repeat.
        # Measured on 39,765 open postings: 413 distinct company keys and 29,088
        # distinct titles, against 2.5 million regex searches a request. The
        # rules do not change inside one call, so remembering an answer is the
        # same answer.
        titles, employers = {}, {}
        minimum = rules.get('min_confidence', 25)

        def verdict(title):
            """(refused outright, must be justified by its description)."""
            if title not in titles:
                titles[title] = (jsearch.excluded(title, rules),
                                 jsearch.needs_evidence(title, rules))
            return titles[title]

        def collect_into(target, rows):
            for row in rows:
                job = dict(row)
                job['title'] = clean_title(job['title'], job['location'])
                # Keyed on what employer_excluded actually reads -- the display
                # name -- not on company_key. One key can carry several names:
                # the select COALESCEs a catalog name, the provider's
                # employer_name and the key itself, so caching by key would
                # answer for "AMD" with the answer for "Advanced Micro Devices".
                employer = job.get('company')
                if employer not in employers:
                    employers[employer] = jsearch.employer_excluded(job, rules)
                if employers[employer]:
                    continue
                refused, evidence = verdict(job['title'])
                if refused:
                    continue
                try:
                    raw = json.loads(job.pop('raw') or '{}')
                except (TypeError, ValueError):
                    raw = {}
                experience = jsearch.experience_debug({'title': job['title'], 'raw': raw})
                if experience['hard_pass_reason']:
                    continue
                job['experience_filter'] = experience
                # An evidence title with supplied prose has to earn its place.
                # Missing prose is not evidence against a posting, so inspect
                # raw before treating a low stored score as a rejection. Raw is
                # already loaded for experience checks, but never sent to the UI.
                # A row scored under rules that hard-rejected these titles still
                # holds a zero, so they stay hidden until the next pass rescores
                # them; `job-store --rescore` does it in one go.
                if evidence and job['confidence'] < minimum:
                    if jsearch.description_text({'raw': raw}):
                        continue
                key = decision_key(job)
                group = target.setdefault(key, {'id': key, 'company': job['company'],
                                                'title': job['title'],
                                                'confidence': job['confidence'],
                                                'bucket': ranking.bucket(job['title']),
                                                'flagged': bool(evidence), 'jobs': []})
                group['jobs'].append(job)

        collect_into(groups, db.execute(
            select + ''' WHERE j.closed_at IS NULL AND julianday(j.first_seen) >= julianday(?)
                         AND julianday(j.first_seen) <= julianday(?)
                         ORDER BY confidence DESC, j.first_seen DESC, j.url''',
            (since, now.isoformat())))
        # Anything still open and still undecided, from before the recent window.
        # A three-day queue is a working rhythm, not an expiry: a posting nobody
        # got to on Friday was silently gone by Monday, with no view that could
        # still reach it.
        collect_into(backlog, db.execute(
            select + ''' WHERE j.closed_at IS NULL AND julianday(j.first_seen) < julianday(?)
                         ORDER BY confidence DESC, j.first_seen DESC, j.url''', (since,)))
        for url, event in url_states.items():
            if event['status'] == 'pending':
                continue
            snapshot_jobs = event.get('group', {}).get('jobs', [])
            row = next((job for job in snapshot_jobs if job['url'] == url), None)
            if row is None:
                row = db.execute(select + ' WHERE j.url=?', (url,)).fetchone()
            if row:
                job = dict(row)
                if decision_for(job) is not event:
                    continue
                job.pop('raw', None)
                legacy_history.append((event['status'], {
                    'id': 'legacy:' + hashlib.sha256(url.encode()).hexdigest(),
                    'company': job['company'], 'title': job['title'], 'confidence': job['confidence'],
                    'jobs': [job], 'at': event['at'], 'reason': event.get('reason', '')}))
    result = {'pending': [], 'backlog': [], 'applied': [], 'skipped': [],
              'ledger': str(path.resolve())}

    def label(group):
        """Give a group its band and its evidence mark, in place."""
        group['bucket'] = ranking.bucket(group.get('title'))
        group['flagged'] = jsearch.needs_evidence(group.get('title'), rules)
        return group

    def undecided(source):
        """Groups nobody has ruled on, with any already-ruled listing removed."""
        out = []
        for key, group in source.items():
            group['jobs'] = [job for job in group['jobs']
                             if (decision_for(job) or {}).get('status', 'pending') == 'pending']
            if group['jobs']:
                out.append(group)
        return out

    # Ranked, not merely scored. The score cannot see an internship or a
    # posting's date, and those are the two things that decide what is worth
    # opening first; see `ranking` for why the bucket is asked before the score
    # rather than folded into it.
    result['pending'] = ranking.order(undecided(groups))
    result['backlog'] = ranking.order(undecided(backlog))
    for key, event in group_states.items():
        if event['status'] != 'pending':
            group = dict(event['group'], at=event['at'], reason=event.get('reason', ''))
            group['jobs'] = [job for job in group['jobs'] if decision_for(job) is event]
            if not group['jobs']:
                continue
            # Decided groups are replayed from their stored snapshot, which
            # predates both marks; recomputing them keeps one vocabulary across
            # every tab rather than leaving history unlabelled.
            label(group)
            result[event['status']].append(group)
    for status, group in legacy_history:
        label(group)
        result[status].append(group)
    for status in ('applied', 'skipped'):
        result[status].sort(key=lambda group: group['at'], reverse=True)
    return result
