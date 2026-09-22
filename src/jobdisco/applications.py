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


def scoped_identity(job):
    """The provider's own requisition for a posting, scoped as the store scopes it.

    None where the provider published none: `decision_key` is then standing on
    the address, and the index holds no alias that could confirm or deny it.
    """
    requisition = str(job.get('source_job_id') or '').strip()
    if not requisition:
        return None
    provider = job.get('provider_key') or ''
    return (provider,
            '' if provider == 'jsearch' else (job.get('company_key') or ''),
            requisition)


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


def describes_decision(db, url, row, decided):
    """Whether the posting now at `url` is the opening `decided` was made on.

    `row` is what the index holds at the address now, and `decided` the job as
    the decision's snapshot recorded it. The same test the queue applies before
    letting a decision follow a posting: the same requisition, or a provider
    change with company and title agreeing *and* the decided requisition still
    among the address's aliases. The description view used to accept the
    provider change and the title alone, so a board that reused an address for
    a new opening under the same title showed that opening's prose under an
    application made to the old one.
    """
    if decision_key(dict(row, url=url)) == decision_key(decided):
        return True
    here = (row['provider_key'] or '', row['company_key'] or '',
            clean_title(row['title'] or '', row['location'] or ''))
    under = (decided.get('provider_key') or '', decided.get('company_key') or '',
             decided.get('title') or '')
    if not (under[0] and under[0] != here[0] and under[1:] == here[1:]):
        return False
    identity = scoped_identity(decided)
    if identity is None or not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_identities'").fetchone():
        return True
    held = {(provider or '', scope or '', str(requisition)) for provider, scope, requisition in db.execute(
        'SELECT provider_key, scope, source_job_id FROM job_identities WHERE url=?', (url,))}
    return not held or identity in held


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
    # group_states: scoped requisition -> decision. url_states: the URL
    # fallback, for ledger records too old to carry a scoped snapshot.
    # moved_states: URL -> (provider it was decided under, decision), which is
    # how a decision survives the same posting changing provider.
    group_states, url_states, moved_states = {}, {}, {}
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
                decision = dict(event, group_id=key, group=dict(
                    snapshot, id=key, title=title, jobs=jobs))
                group_states[key] = decision
                for job in jobs:
                    # A posting found first through JSearch and later on the
                    # company's own board keeps its URL -- the store merges the
                    # two discoveries into one row -- but takes the direct
                    # provider, and the key above is scoped by provider. Without
                    # this the decision was lost and a job already applied for
                    # came back as pending.
                    #
                    # A changed provider is not on its own evidence that it is
                    # the same opening: an address can be handed to a different
                    # board carrying a different job. So the company and the
                    # title have to agree as well. A posting that was genuinely
                    # retitled will come back as pending, which is the side to
                    # err on -- showing a posting twice is recoverable, hiding
                    # one is not.
                    moved_states.setdefault(job['url'], []).append(
                        ((job.get('provider_key') or '', job.get('company_key') or '',
                          job.get('title') or ''), scoped_identity(job), decision))
            continue
        # Only records without a scoped snapshot may fall back to URL identity.
        # Applying a modern decision by URL too hides a replacement requisition
        # when a board reuses an address.
        url_states[event['url']] = event
        for job in event.get('group', {}).get('jobs', []):
            url_states[job['url']] = event

    # What the index still lists at each decided address, from `job_identities`.
    # Loaded once the connection is open, and left None where the index keeps no
    # identities at all -- an older or hand-made one -- because a question it
    # cannot answer must not be read as a no.
    aliases = None

    def still_the_decided_opening(url, identity):
        """Whether the requisition a decision was made under is still at this address.

        A changed provider plus an agreeing company and title is not proof on
        its own. A board that reuses an address for a genuinely different
        opening publishes the same company and, often enough, the same title,
        and the decision then went on answering for every future requisition at
        that address -- a posting nobody had seen, hidden behind an application
        nobody had made to it.

        The store says which is which: a provider upgrade leaves the decided
        requisition among the address's aliases, and a replacement removes it.
        Where the decision names no requisition, or the index records none for
        the address, there is nothing to check and the older reading stands.
        """
        if identity is None or aliases is None:
            return True
        held = aliases.get(url)
        return not held or identity in held

    def decision_for(job):
        provider = job.get('provider_key') or ''
        here = (provider, job.get('company_key') or '', job.get('title') or '')
        moved = [decision for under, identity, decision in moved_states.get(job['url'], ())
                 if under[0] and under[0] != here[0] and under[1:] == here[1:]
                 and still_the_decided_opening(job['url'], identity)]
        candidates = [event for event in (group_states.get(decision_key(job)),
                                          url_states.get(job['url']), *moved) if event]
        return max(candidates, key=lambda event: event['replay_order'], default=None)
    uri = Path(db_path).resolve().as_uri() + '?mode=ro'
    groups, backlog, legacy_history = {}, {}, []
    rules = jsearch.load_plan()[0]['filter']
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='job_identities'").fetchone():
            aliases = {}
            decided = sorted(moved_states)
            for start in range(0, len(decided), 400):
                chunk = decided[start:start + 400]
                for row in db.execute(
                        'SELECT url, provider_key, scope, source_job_id FROM job_identities '
                        'WHERE url IN (%s)' % ','.join('?' * len(chunk)), chunk):
                    aliases.setdefault(row['url'], set()).add(
                        (row['provider_key'] or '', row['scope'] or '',
                         str(row['source_job_id'])))
        # A pass that rejects a posting it already holds does not store the
        # description it rejected -- a rejected posting is recognised, not
        # stored -- so the index keeps the text from the pass that accepted it,
        # and the queue went on offering a posting whose published terms now
        # disqualify it. The rejection itself is on record in `seen_jobs`, and
        # it is newer than the copy being shown, which is what this reads.
        #
        # Matched on the requisition and not on the address: a rejected posting
        # would otherwise take down whatever holds its URL now, and one posting
        # refused and another accepted at the same address is precisely what a
        # reused URL produces. `record_seen` stores the provider's id where it
        # gives one and the url where it does not, which is what the COALESCE
        # below mirrors -- and that pair is `seen_jobs`'s primary key, so the
        # lookup is one index seek instead of a scan of every row sharing a URL.
        #
        # Only the same provider, and only the reasons that are properties of
        # the posting rather than of the query that found it: an employer
        # mismatch says the query asked the wrong question, not that the job is
        # wrong. Both stamps are written by this codebase, so they are
        # comparable -- as instants, never as strings.
        settled = ', '.join("'%s'" % reason for reason in sorted(jsearch.HARD_REJECTIONS)
                            if reason.replace('_', '').isalnum())
        # An index built before the seen table, or a hand-made one, simply has
        # no rejections to read; the queue is not the place to insist on them.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='seen_jobs'").fetchone():
            settled = None
        select = '''SELECT j.url, j.company_key, j.source_job_id,
                            COALESCE(c.name, json_extract(j.raw, '$.employer_name'), j.company_key) AS company,
                            j.title, j.location, j.first_seen, j.posted_at, j.provider_key,
                            COALESCE(j.relevance, 0) AS confidence, j.raw,
                            %s AS superseded
                            FROM jobs j LEFT JOIN companies c USING(company_key)''' % (
            '''(SELECT s.decision FROM seen_jobs s
                 WHERE s.provider_key = j.provider_key
                   AND s.source_job_id = COALESCE(NULLIF(j.source_job_id, ''), j.url)
                   AND s.decision IN (%s)
                   AND julianday(s.last_seen) > julianday(j.last_seen)
                LIMIT 1)''' % settled if settled else 'NULL')

        # Both checks are pure functions of a string, and the strings repeat.
        # Measured on 39,765 open postings: 413 distinct company keys and 29,088
        # distinct titles, against 2.5 million regex searches a request. The
        # rules do not change inside one call, so remembering an answer is the
        # same answer.
        titles, employers = {}, {}
        minimum = rules.get('min_confidence', 25)

        def verdict(title):
            """(refused outright, must be justified by its description)."""
            # The soft block as well as the hard one. It used to run only on
            # paid results as they were collected, so a direct board's posting
            # -- most of the queue -- was never asked, and the backlog carried
            # 2,855 software, analog, quality and recruiting titles the rules
            # already said to drop. An evidence title is not blocked by name,
            # here as in `rejection_reason`: its description decides it.
            if title not in titles:
                evidence = jsearch.needs_evidence(title, rules)
                titles[title] = (jsearch.excluded(title, rules)
                                 or (not evidence and jsearch.title_blocked(title, rules)),
                                 evidence)
            return titles[title]

        def collect_into(target, rows):
            for row in rows:
                job = dict(row)
                if job.pop('superseded', None):
                    continue
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
                requirements = jsearch.description_text({'raw': raw}, structured=True)
                experience = jsearch.experience_debug({'title': job['title'], 'raw': raw}, requirements)
                if experience['hard_pass_reason']:
                    continue
                if jsearch.us_person_required(requirements, rules):
                    continue
                if jsearch.publisher_excluded(job['url'], raw, rules):
                    continue
                job['experience_filter'] = experience
                # A paid listing's link is wherever Google Jobs found the
                # posting, and for every open JSearch posting measured on
                # 2026-09-22 that was a third-party site -- LinkedIn, JobLeads,
                # InterviewSense -- with no direct option offered. Say who
                # published it, and where the employer's own site is, so the
                # page can offer the company's copy instead.
                if job['provider_key'] == 'jsearch' and not raw.get('job_apply_is_direct'):
                    publisher = raw.get('job_publisher')
                    site = jsearch.public_link(raw.get('employer_website'))
                    if isinstance(publisher, str) and publisher.strip():
                        job['publisher'] = publisher.strip()
                    if site:
                        job['employer_site'] = site
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
                                                'flagged': bool(evidence),
                                                'internship_experience': False, 'jobs': []})
                # An internship already served is a qualification, not a reason
                # to refuse anything. It is marked because the word `internship`
                # in a posting that is not one is worth seeing, and because this
                # is the same reading that keeps such a posting out of the
                # entry-level override.
                group['internship_experience'] = (group['internship_experience']
                                                  or experience['internship_experience'])
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
        # A requisition can acquire another location after the recent window.
        # Keep the entire decision group in recent when any listing is recent;
        # otherwise POST would snapshot only whichever tab it searched first.
        for key in list(backlog):
            if key in groups:
                groups[key]['jobs'].extend(backlog.pop(key)['jobs'])
        for url, event in url_states.items():
            if event['status'] == 'pending':
                continue
            snapshot_jobs = event.get('group', {}).get('jobs', [])
            row = next((job for job in snapshot_jobs if job['url'] == url), None)
            if row is None:
                row = db.execute(select + ' WHERE j.url=?', (url,)).fetchone()
            if row:
                job = dict(row)
                job.pop('superseded', None)
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
