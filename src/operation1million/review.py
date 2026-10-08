"""Local application review server. User-directed collection and durable application decisions."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import requests
import sqlite3
import threading
from urllib.parse import urlsplit, parse_qs

from . import applications, export, ranking, jsearch, manual_intake, collection_policy, gmail_outcomes, resume_fit
from .queue_snapshot import QueueSnapshot
from .job_text import display_description, readable_text
from .paths import DB


# What review_static/app.js actually reads. `queue()` carries more than this
# because writing a decision needs the scoped requisition identity -- source_job_id
# and company_key are what decision_key is computed from for direct sources --
# but the browser reads a fraction, and the difference is 3.6 of the 12.5 MB this
# endpoint returned before. Measured on 21,222 groups: the five per-job fields
# nothing renders cost title 1.13, source_job_id 0.91, company 0.65, company_key
# 0.53 and confidence 0.35 MB. posted_at stays: a contract test below reads
# app.js and found the page showing it, which a hand-audit of the field list had
# missed.
#
# Only the response is trimmed. `do_POST` rebuilds the group from its own
# `queue()` call and never from what the client sends back, so a decision is
# still written against the full row. Adding a field to the page means adding
# it here; leaving it out shows as undefined rather than as stale data.
GROUP_FIELDS = ('id', 'company', 'title', 'confidence', 'at', 'reason',
                'bucket', 'flagged', 'internship_experience', 'less_related',
                'early_career', 'outcome', 'outcome_at', 'outcome_by')
JOB_FIELDS = ('url', 'location', 'provider_key', 'first_seen', 'posted_at',
              'posted_before', 'publisher', 'employer_site', 'official_link', 'third_party_site')
STATUSES = ('pending', 'backlog', 'applied', 'skipped')
# The page and its two assets, by path.
ASSETS = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css')}


def each_group(state):
    """(status, group) for every group in a queue, a status at a time."""
    return ((status, group) for status in STATUSES for group in state[status])


def find_group(state, group_id):
    """(status, group) for a group id in a queue, or (None, None)."""
    return next(((status, group) for status, group in each_group(state)
                 if group['id'] == group_id), (None, None))


def slim(state):
    """Project the queue down to what the page renders."""
    trimmed = {}
    for key, value in state.items():
        if not isinstance(value, list):
            trimmed[key] = value
            continue
        trimmed[key] = [
            dict({name: group[name] for name in GROUP_FIELDS if name in group},
                 jobs=[dict({name: job[name] for name in JOB_FIELDS if name in job},
                            third_party_site=export.third_party_site(job))
                       for job in group.get('jobs', [])])
            for group in value]
    return trimmed


def local_host(header):
    """Whether a Host header names this machine. The IPv6 loopback too: a tunnel
    opened on [::1] was refused (2026-09-27)."""
    try:
        host = urlsplit('http://' + (header or '')).hostname
    except ValueError:
        return False
    return host in {'127.0.0.1', 'localhost', '::1'}


def fingerprint(path):
    """What a file looks like from outside: when it changed, and how long."""
    try:
        state = Path(path).stat()
    except OSError:
        return None
    return state.st_mtime_ns, state.st_size


def wal_fingerprint(path):
    """The same, for a WAL sidecar -- except an empty one says nothing.

    An empty or absent sidecar holds no commit; everything is in the main
    file, whose own fingerprint covers it. But every reader that opens the
    index recreates an empty sidecar and moves its timestamp, and keying on
    that threw the cache away whenever anything read the index: measured on
    the VPS, a 0-byte `-wal` touched at 03:03 UTC with no pass running, and the
    next page load paid a 28-second build.
    """
    state = fingerprint(path)
    return state if state and state[1] else None


def ledger_fingerprint(path):
    """Detect append, deletion and atomic replacement, even at equal mtime/size."""
    try:
        state = Path(path).stat()
    except FileNotFoundError:
        return None
    return state.st_mtime_ns, state.st_size, state.st_ino, state.st_ctime_ns


def make_server(db, ledger, port=8765, export_path=None):
    token = secrets.token_urlsafe(32)
    export_path = export_path or export.DEFAULT_PATH
    links = applications.links_path(ledger)
    outcomes = applications.outcomes_path(ledger)
    assets = Path(__file__).with_name('review_static')
    # One decision at a time, now that requests are served in parallel. Reading
    # the queue and appending to the ledger is a read-modify-write, and the
    # ledger is the one file here nothing regenerates.
    writing = threading.Lock()
    building = threading.Lock()
    cached = {'key': None, 'state': None, 'attachments': None, 'response': None}
    snapshot = QueueSnapshot(ledger, db)
    parsed_ledgers = {}

    def invalidate():
        """Called under building after every in-memory queue mutation."""
        cached['attachments'] = None
        cached['response'] = None

    def read_cached(path, reader):
        # Only these two side ledgers are cached; callers hold the building lock.
        # A concurrent writer makes this read uncacheable, never a permanent hit.
        before = ledger_fingerprint(path)
        previous = parsed_ledgers.get(path)
        if previous is not None and previous[0] == before:
            return previous[1]
        value = reader(path)
        if ledger_fingerprint(path) == before:
            parsed_ledgers[path] = (before, value)
        else:
            parsed_ledgers.pop(path, None)
        return value

    def queue_key():
        return (fingerprint(ledger), fingerprint(db), wal_fingerprint(str(db) + '-wal'),
                datetime.now(timezone.utc).date(),
                jsearch.filter_fingerprint(jsearch.load_plan()[0]['filter']),
                fingerprint(manual_intake.path_for(ledger)),
                fingerprint(resume_fit.profile_path(ledger)))

    def record_decision(before, state, source, group, written):
        """Move a just-decided group in the cached queue instead of rebuilding it.

        A decision changes the ledger, and a changed ledger meant a full build:
        about 28 seconds on the live queue, during which the page showed the
        posting still waiting and the next decision queued behind the build.
        Replaying one appended event against the queue it was decided from is
        the same answer, and `ApplicationsTests` holds the two equal. It is
        taken only when the ledger is the one input that moved since `before`;
        anything else -- a pass committing, the date turning -- leaves the cache
        stale and the next request builds it in full, as before.
        """
        if written['status'] not in {'applied', 'skipped'} or source not in {'pending', 'backlog'}:
            return
        after = queue_key()
        if after[1:] != before[1:]:
            return
        with building:
            if cached['key'] != before or cached['state'] is not state:
                return
            state[source] = [item for item in state[source] if item is not group]
            if written['status'] == 'applied':
                # An application also answers its namesakes, as the full build says.
                index = applications.application_index([group])
                for name in ('pending', 'backlog'):
                    state[name] = [item for item in state[name]
                                   if not applications.covered_by_application(item, index)]
            decided = dict(group, jobs=list(group['jobs']), at=written['at'],
                           reason=written.get('reason', ''))
            state[written['status']].insert(0, decided)
            cached['key'] = after
            invalidate()

    def current_queue():
        """The queue, rebuilt only when what it is derived from has changed.

        Building it replays the whole ledger and reads every open posting, and
        a decision paid for that twice: once to find the group to write, and
        once through the refresh that follows the write. Track the ledger and
        index files, plus the active filter fingerprint: editing title rules
        must invalidate the queue even before the index is rescored.

        The UTC date is in the key as well, because the three-day window is a
        function of the clock and nothing else. Within a day the window drifts
        rather than moving: a posting stays in the recent tab a little longer
        than it strictly should, and is in the backlog either way.

        The index is read in WAL mode, and that is where a commit lands: the
        main file's timestamp and length do not move until a checkpoint, which
        a pass only reaches when it closes its connection. So the whole of a
        collection pass -- every posting it found, every one it closed -- was
        invisible to this page while the pass ran, and Refresh answered from
        the cache with nothing to say it was stale. The sidecar is where the
        commit is, so it is part of the question. A reader that recreates a
        checkpointed sidecar moves its timestamp too, which costs one extra
        build and never a missed one.
        """
        key = queue_key()
        with building:
            side_keys = (ledger_fingerprint(links), ledger_fingerprint(outcomes))
            signature = snapshot.signature(key, side_keys)
            if cached['key'] != key:
                restored = snapshot.load(signature) if cached['state'] is None else None
                cached['state'] = restored if restored is not None else manual_intake.augment_queue(applications.queue(db, ledger), ledger)
                cached['key'] = key
                invalidate()
            if queue_key() == key:
                if cached['attachments'] != side_keys:
                    invalidate()
                    applications.attach_links(cached['state'], read_cached(links, applications.read_links))
                    applications.attach_outcomes(cached['state'], read_cached(outcomes, applications.read_outcomes))
                    if side_keys == (ledger_fingerprint(links), ledger_fingerprint(outcomes)):
                        cached['attachments'] = side_keys
                snapshot.save(signature, cached['state'])
            return cached['state']

    def queue_response():
        # Mutations take writing -> building in this order. Serialize under the
        # same locks, then release them before sending bytes to a slow client.
        with writing:
            current_queue()
            with building:
                if cached['response'] is None:
                    cached['response'] = json.dumps(dict(slim(cached['state']),
                        token=token, labels=list(ranking.LABELS))).encode()
                return cached['response']

    class Handler(BaseHTTPRequestHandler):
        # A socket that connects and then says nothing used to stop the server
        # dead: requests were served one at a time, and the read of a request
        # line that never arrives does not return. A browser opens such sockets
        # by itself, speculatively, so the review page could hang the service it
        # was talking to. Threads answer the other requests; the timeout stops
        # the idle socket holding a thread forever.
        timeout = 30

        def log_message(self, *args):
            pass

        def send(self, body, code=200, mime='application/json'):
            data = json.dumps(body).encode() if mime == 'application/json' and not isinstance(body, bytes) else body
            self.send_response(code)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            # An SSH tunnel may use a different local port than the server.
            if not local_host(self.headers.get('Host', '')):
                return self.send({'error': 'Local access only'}, 403)
            route = urlsplit(self.path)
            try:
                if route.path == '/api/queue':
                    if cached['state'] is None and building.locked():
                        return self.send({'error': 'Preparing the job queue'}, 503)
                    return self.send(queue_response())
                if route.path == '/api/job':
                    return self.job(parse_qs(route.query))
                if route.path == '/api/gmail':
                    # Replies the Gmail check could not settle (2026-10-05).
                    return self.send({'items': gmail_outcomes.read_unsorted()})
                if route.path in ASSETS:
                    name, mime = ASSETS[route.path]
                    return self.send((assets / name).read_bytes(), mime=mime)
                self.send({'error': 'Not found'}, 404)
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.send({'error': str(exc)}, 500)

        def job(self, query):
            """One posting's description, unless the decision shown was about another."""
            url = query.get('url', [''])[0]
            group_id = query.get('id', [''])[0]
            # The decision's own record of the job, from the queue this
            # server already holds, rather than the provider and title
            # the page sends back: whether a posting moved or was
            # replaced is decided on the snapshot, as the queue decides it.
            decided = None
            if group_id and not group_id.startswith('legacy:'):
                state = cached['state'] or current_queue()
                _, group = find_group(state, group_id)
                if group:
                    decided = next((job for job in group['jobs'] if job['url'] == url),
                                   group['jobs'][0] if group['jobs'] else None)
            if decided and decided.get('manual_import'):
                return self.send({'description': decided.get('manual_description', '')})
            with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as con:
                con.row_factory = sqlite3.Row
                row = con.execute(
                    'SELECT raw, company_key, provider_key, source_job_id, title, location '
                    'FROM jobs WHERE url=?', (url,)).fetchone()
                # A decided group is replayed from the snapshot it was
                # decided on, and a board may since have advertised
                # another requisition at the same address. Showing that
                # opening's prose under the earlier decision says the
                # applicant applied to something they never read. A
                # posting that only changed provider -- found through
                # JSearch, then on the company's own board -- is still
                # the one decided on, and the store's aliases say which
                # of the two happened.
                if row is not None and decided is not None and (
                        not applications.describes_decision(con, url, dict(row), decided)):
                    return self.send({'description': '', 'replaced': True})
            raw = json.loads(row['raw'] or '{}') if row else {}
            description, kind = display_description(raw)
            description = str(description)
            # Parsed only where there is markup to parse. Everything
            # used to go through the parser, including descriptions the
            # provider states as plain text, and a plain-text sentence
            # about `vector<T>` came back missing the type.
            description = readable_text(description)
            body = {'description': description.strip()}
            if kind in ('excerpt', 'discovery'):
                body['kind'] = kind
            return self.send(body)

        def read_json(self, limit):
            """The request's JSON body, refused past `limit` bytes."""
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= limit:
                raise ValueError('Invalid request size')
            return json.loads(self.rfile.read(size))

        def do_POST(self):
            routes = {'/api/decision': self.decide, '/api/export': self.export,
                      '/api/export/download': self.export,
                      '/api/link': self.link, '/api/manual': self.manual,
                      '/api/outcome': self.outcome}
            if self.path not in routes:
                return self.send({'error': 'Not found'}, 404)
            if self.headers.get('X-Review-Token') != token:
                return self.send({'error': 'Reload the review page before saving'}, 403)
            try:
                routes[self.path]()
            except (requests.RequestException, collection_policy.SourcePaused, collection_policy.RobotsThrottled) as exc:
                self.send({'error': str(exc) + '. Supply Company and Title to save without fetching.'}, 400)
            except export.ExportLocked as exc:
                self.send({'error': str(exc)}, 409)
            except (ValueError, TypeError, AttributeError) as exc:
                self.send({'error': str(exc)}, 400)
            except (OSError, sqlite3.Error) as exc:
                self.send({'error': str(exc)}, 500)

        def decide(self):
            data = self.read_json(10000)
            with writing:
                state = current_queue()
                before = cached['key']
                source, group = find_group(state, data.get('id'))
                if group is None:
                    return self.send({'error': 'This item changed. Refresh the queue.'}, 409)
                written = applications.append_decision(
                    ledger, group, data.get('status'), data.get('reason', ''))
                record_decision(before, state, source, group, written)
            self.send(written)

        def export(self):
            """Write the groups the page is showing, in its order, to the one workbook.

            The page sends only which groups and in what order; every value
            written comes from this server's own queue, as a decision does.
            """
            ids = self.read_json(4_000_000).get('ids')
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise ValueError('Send the ids of the groups to export')
            state = current_queue()
            where = {group['id']: (status, group) for status, group in each_group(state)}
            entries = [where[item] for item in dict.fromkeys(ids) if item in where]
            if self.path == '/api/export/download':
                data = export.workbook_bytes(export.rows(entries))
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', 'attachment; filename="selected-positions.xlsx"')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(data)
                return
            with writing:
                count = export.write(export_path, entries)
            self.send({'path': str(Path(export_path).resolve()), 'rows': count,
                       'groups': len(entries), 'at': datetime.now(timezone.utc).isoformat()})

        def manual(self):
            data = self.read_json(200000)
            url = manual_intake.normalized_url(data.get('url', ''))
            requested = data.get('status', 'pending')
            if requested not in ('pending', 'applied'):
                raise ValueError('Choose Add job or Already applied')
            state = current_queue()
            source, group = manual_intake.match_group(state, url)
            metadata = None
            final_url = url
            if group is None:
                official = data.get('official') is True
                if data.get('company') and data.get('title'):
                    metadata = manual_intake.posting_metadata(
                        '', data, url, manual_intake.catalog_source(url, db), official)
                else:
                    final_url, metadata = manual_intake.read_posting(url, ledger, db, data, official)
                # Recording an application already made is a fact, not a choice.
                refused = manual_intake.refusal(metadata) if requested != 'applied' else None
                if refused:
                    raise ValueError(f'{refused}. Not added; Already applied still records it.')
            with writing:
                state = current_queue()
                before = cached['key']
                source, group = manual_intake.match_group(state, url, metadata)
                if group is None and final_url != url:
                    source, group = manual_intake.match_group(state, final_url, metadata)
                replaced = None
                if group is not None and metadata and data.get('official') is True and all(export.third_party_site(job) for job in group['jobs']):
                    replaced = group
                    group = None
                created = group is None
                if created:
                    group = manual_intake.create_group(final_url, metadata)
                    manual_intake.save_manual(ledger, group,
                        [replaced['id']] if replaced else [], [replaced] if replaced else [])
                    if replaced and source in ('applied', 'skipped') and requested != 'applied':
                        applications.append_decision(ledger, group, source, replaced.get('reason', ''))
                if requested == 'applied':
                    written = applications.append_decision(ledger, group, 'applied', 'Marked applied from pasted link')
                    if not created:
                        record_decision(before, state, source, group, written)
                if created:
                    after = queue_key()
                    with building:
                        if cached['state'] is state and cached['key'] == before and after[1:5] == before[1:5]:
                            cached['state'] = manual_intake.augment_queue(state, ledger)
                            cached['key'] = after
                            invalidate()
            self.send({'id': group['id'], 'created': created, 'replaced': bool(replaced),
                       'confidence': group.get('confidence', 0), 'status': requested})

        def link(self):
            """The company's own link for a third-party listing, as the user found it.

            Asked for on 2026-10-02. Recorded beside the ledger and set on the
            cached queue in place, so the page shows it without a rebuild.
            """
            data = self.read_json(10000)
            url = data.get('url')
            with writing:
                state = current_queue()
                listed = [job for _, group in each_group(state)
                          for job in group['jobs'] if job.get('url') == url]
                if not listed:
                    return self.send({'error': 'This listing is not in the queue. Refresh the page.'}, 409)
                written = applications.append_link(links, url, data.get('link', ''))
                with building:
                    for job in listed:
                        if written['link']:
                            job['official_link'] = written['link']
                        else:
                            job.pop('official_link', None)
                    invalidate()
            self.send(written)

        def outcome(self):
            """Passed or Declined for an applied position (2026-10-05).

            Recorded beside the ledger and set on the cached queue in place.
            The ledger itself is untouched: the position stays applied.
            """
            data = self.read_json(10000)
            with writing:
                state = current_queue()
                status, group = find_group(state, data.get('id'))
                if status != 'applied':
                    return self.send({'error': 'Only an applied position has an outcome. Refresh the page.'}, 409)
                written = applications.append_outcome(outcomes, group['id'], data.get('outcome'))
                with building:
                    applications.attach_outcomes(
                        {'applied': [group]}, {group['id']: written} if written['outcome'] else {})
                    invalidate()
            self.send(written)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.current_queue = current_queue
    return server


def keep_warm(server, every=30, stop=None):
    """Rebuild the queue when its inputs change, before anyone asks for it.

    A cold build takes about half a minute on the live queue, and every pass
    makes the next build cold. The first person to open the page after a pass
    paid for it, looking at a page with no jobs on it. A build here costs the
    same and nobody waits for it; when nothing has changed it is a few stat
    calls. A failure is left for the request that repeats it to report.
    """
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            server.current_queue()
        except Exception as exc:
            print(f'Queue warm-up failed: {exc}', flush=True)
        stop.wait(every)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB)
    parser.add_argument('--ledger', type=Path, default=None)
    parser.add_argument('--port', type=int, default=8765)
    # A shared folder -- OneDrive, a network drive -- puts the workbook where
    # other people can open it. Job data is private: never inside this repo
    # except under the ignored .local/.
    parser.add_argument('--export', type=Path, default=export.DEFAULT_PATH,
                        help='The one Excel file the page exports to (default %(default)s)')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Job database missing. Restore private history and run job-store --bootstrap first.')
    server = make_server(args.db, args.ledger or applications.ledger_path(), args.port, args.export)
    print(f'Review: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'Export: {Path(args.export).resolve()}', flush=True)
    threading.Thread(target=keep_warm, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
