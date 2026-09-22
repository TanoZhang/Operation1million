"""Local application review server. No collection or external writes."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit, parse_qs

from bs4 import BeautifulSoup
from . import applications, ranking, jsearch
from .job_text import clean_title
from .paths import DB


# A tag this page should render, rather than any text between angle brackets.
# A description that says `<T>` or `<int>` is naming a type, and handing it to
# an HTML parser deleted the word: the reader was shown a sentence with a hole
# in it and no way to know something had been removed.
MARKUP = re.compile(
    r'<\s*/?\s*(?:p|br|div|span|ul|ol|li|strong|b|em|i|h[1-6]|table|tr|td|th|a)\b'
    r'|<!--|&nbsp;|&lt;|&amp;', re.I)


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
                'bucket', 'flagged', 'internship_experience')
JOB_FIELDS = ('url', 'location', 'provider_key', 'first_seen', 'posted_at')


def slim(state):
    """Project the queue down to what the page renders."""
    trimmed = {}
    for key, value in state.items():
        if not isinstance(value, list):
            trimmed[key] = value
            continue
        trimmed[key] = [
            dict({name: group[name] for name in GROUP_FIELDS if name in group},
                 jobs=[{name: job[name] for name in JOB_FIELDS if name in job}
                       for job in group.get('jobs', [])])
            for group in value]
    return trimmed


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


def make_server(db, ledger, port=8765):
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).with_name('review_static')
    # One decision at a time, now that requests are served in parallel. Reading
    # the queue and appending to the ledger is a read-modify-write, and the
    # ledger is the one file here nothing regenerates.
    writing = threading.Lock()
    building = threading.Lock()
    cached = {'key': None, 'state': None}

    def queue_key():
        return (fingerprint(ledger), fingerprint(db), wal_fingerprint(str(db) + '-wal'),
                datetime.now(timezone.utc).date(),
                jsearch.filter_fingerprint(jsearch.load_plan()[0]['filter']))

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
            decided = dict(group, jobs=list(group['jobs']), at=written['at'],
                           reason=written.get('reason', ''))
            state[written['status']].insert(0, decided)
            cached['key'] = after

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
            if cached['key'] != key:
                cached['state'] = applications.queue(db, ledger)
                cached['key'] = key
            return cached['state']

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
            data = json.dumps(body).encode() if mime == 'application/json' else body
            self.send_response(code)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            # An SSH tunnel may use a different local port than the server.
            if urlsplit('http://' + self.headers.get('Host', '')).hostname not in {'127.0.0.1', 'localhost'}:
                return self.send({'error': 'Local access only'}, 403)
            route = urlsplit(self.path)
            try:
                if route.path == '/api/queue':
                    # Added after `slim`, which would read a bare list of names
                    # as a list of groups and project the strings away.
                    return self.send(dict(slim(current_queue()),
                                          token=token, labels=list(ranking.LABELS)))
                if route.path == '/api/job':
                    query = parse_qs(route.query)
                    url = query.get('url', [''])[0]
                    group_id = query.get('id', [''])[0]
                    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as con:
                        con.row_factory = sqlite3.Row
                        row = con.execute(
                            'SELECT raw, company_key, provider_key, source_job_id, title, location '
                            'FROM jobs WHERE url=?', (url,)).fetchone()
                    # A decided group is replayed from the snapshot it was
                    # decided on, and a board may since have advertised another
                    # requisition at the same address. The row there now is a
                    # different opening, and showing its prose under the earlier
                    # decision's title says the applicant applied to something
                    # they never read. Legacy groups carry no requisition to
                    # compare, so they are answered as before.
                    if row is not None and group_id and not group_id.startswith('legacy:'):
                        held = applications.decision_key(
                            {'provider_key': row['provider_key'], 'company_key': row['company_key'],
                             'source_job_id': row['source_job_id'], 'url': url})
                        # The same opening found again on the company's own
                        # board keeps its URL and takes the direct provider,
                        # which changes the key it is identified by. That is a
                        # posting that moved, not one that was replaced, and
                        # reporting it as replaced hid the description of a job
                        # the applicant had actually applied to. The page sends
                        # the provider and title it is showing so the two can be
                        # told apart; the URL already fixes the employer.
                        moved = (query.get('provider', [''])[0] or '') not in (
                            '', row['provider_key'] or '')
                        same = moved and clean_title(
                            row['title'] or '', row['location'] or '') == query.get('title', [''])[0]
                        if held != group_id and not same:
                            return self.send({'description': '', 'replaced': True})
                    raw = json.loads(row['raw'] or '{}') if row else {}
                    description = (raw.get('job_description') or raw.get('description') or
                                   raw.get('descriptionPlain') or raw.get('jobDescription') or
                                   raw.get('descriptionHtml') or raw.get('jobDescriptionHtml') or '') if isinstance(raw, dict) else ''
                    description = str(description)
                    # Parsed only where there is markup to parse. Everything
                    # used to go through the parser, including descriptions the
                    # provider states as plain text, and a plain-text sentence
                    # about `vector<T>` came back missing the type.
                    if MARKUP.search(description):
                        description = BeautifulSoup(description, 'html.parser').get_text('\n', strip=True)
                    return self.send({'description': description.strip()})
                names = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                         '/style.css': ('style.css', 'text/css')}
                if route.path in names:
                    name, mime = names[route.path]
                    return self.send((assets / name).read_bytes(), mime=mime)
                self.send({'error': 'Not found'}, 404)
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.send({'error': str(exc)}, 500)

        def do_POST(self):
            if self.path != '/api/decision':
                return self.send({'error': 'Not found'}, 404)
            if self.headers.get('X-Review-Token') != token:
                return self.send({'error': 'Reload the review page before saving'}, 403)
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 10000:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(size))
                with writing:
                    state = current_queue()
                    before = cached['key']
                    source, group = next(((status, group) for status in ('pending', 'backlog', 'applied', 'skipped')
                                          for group in state[status] if group['id'] == data.get('id')),
                                         (None, None))
                    if group is None:
                        return self.send({'error': 'This item changed. Refresh the queue.'}, 409)
                    written = applications.append_decision(
                        ledger, group, data.get('status'), data.get('reason', ''))
                    record_decision(before, state, source, group, written)
                self.send(written)
            except (ValueError, TypeError, AttributeError) as exc:
                self.send({'error': str(exc)}, 400)
            except (OSError, sqlite3.Error) as exc:
                self.send({'error': str(exc)}, 500)

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
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Job database missing. Restore private history and run job-store --bootstrap first.')
    server = make_server(args.db, args.ledger or applications.ledger_path(), args.port)
    print(f'Review: http://127.0.0.1:{server.server_port}', flush=True)
    threading.Thread(target=keep_warm, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
