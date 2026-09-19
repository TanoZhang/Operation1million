"""Local application review server. No collection or external writes."""
import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit, parse_qs

from bs4 import BeautifulSoup
from . import applications, ranking
from .paths import DB


# What review_static/app.js actually reads. `queue()` carries more than this
# because writing a decision needs it -- source_job_id is what decision_key is
# computed from -- but the browser reads a fraction, and the difference is 3.6
# of the 12.5 MB this endpoint returned before. Measured on 21,222 groups: the
# five per-job fields nothing renders cost title 1.13, source_job_id 0.91,
# company 0.65, company_key 0.53 and confidence 0.35 MB. posted_at stays: a
# contract test below reads app.js and found the page showing it, which a
# hand-audit of the field list had missed.
#
# Only the response is trimmed. `do_POST` rebuilds the group from its own
# `queue()` call and never from what the client sends back, so a decision is
# still written against the full row. Adding a field to the page means adding
# it here; leaving it out shows as undefined rather than as stale data.
GROUP_FIELDS = ('id', 'company', 'title', 'confidence', 'at', 'reason',
                'bucket', 'flagged')
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


def make_server(db, ledger, port=8765):
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).with_name('review_static')

    class Handler(BaseHTTPRequestHandler):
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
                    return self.send(dict(slim(applications.queue(db, ledger)),
                                          token=token, labels=list(ranking.LABELS)))
                if route.path == '/api/job':
                    url = parse_qs(route.query).get('url', [''])[0]
                    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as con:
                        row = con.execute('SELECT raw FROM jobs WHERE url=?', (url,)).fetchone()
                    raw = json.loads(row[0] or '{}') if row else {}
                    description = (raw.get('job_description') or raw.get('description') or
                                   raw.get('jobDescription') or raw.get('descriptionHtml') or '') if isinstance(raw, dict) else ''
                    return self.send({'description': BeautifulSoup(str(description), 'html.parser').get_text('\n', strip=True)})
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
                state = applications.queue(db, ledger)
                group = next((group for status in ('pending', 'backlog', 'applied', 'skipped')
                              for group in state[status] if group['id'] == data.get('id')), None)
                if group is None:
                    return self.send({'error': 'This item changed. Refresh the queue.'}, 409)
                self.send(applications.append_decision(ledger, group, data.get('status'), data.get('reason', '')))
            except (ValueError, TypeError, AttributeError) as exc:
                self.send({'error': str(exc)}, 400)
            except (OSError, sqlite3.Error) as exc:
                self.send({'error': str(exc)}, 500)

    return HTTPServer(('127.0.0.1', port), Handler)


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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
