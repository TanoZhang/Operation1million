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
from . import applications
from .paths import DB


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
                    return self.send(dict(applications.queue(db, ledger), token=token))
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
