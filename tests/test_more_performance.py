import copy
from contextlib import closing
from datetime import datetime, timezone
import sqlite3
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen, Request

from operation1million import applications, review, jsearch, job_text


def state():
    result = {key: [] for key in review.STATUSES}
    result['pending'] = [{'id': 'g', 'company': 'Example', 'title': 'RTL Engineer',
                         'confidence': 90, 'jobs': [{'url': 'https://example.test/job'}]}]
    return result


class MorePerformanceTests(unittest.TestCase):
    def test_title_location_work_is_shared_across_different_titles(self):
        if hasattr(job_text, '_location_patterns'):
            job_text._location_patterns.cache_clear()
        with patch.object(job_text, '_location_candidates', wraps=job_text._location_candidates) as candidates:
            for title in ('RTL Engineer', 'Verification Engineer', 'Physical Design Engineer'):
                self.assertEqual(job_text.clean_title(title + ' - Austin, TX', 'Austin, TX, US'), title)
            self.assertEqual(candidates.call_count, 1)

    def test_plan_cache_isolated_from_callers_and_reloads_atomic_replacements(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'plan.toml'
            original = b'[filter]\nmin_confidence = 25\n'
            path.write_bytes(original)
            with patch.object(jsearch.tomllib, 'load', wraps=jsearch.tomllib.load) as parse:
                config, queries = jsearch.load_plan(path)
                expected = copy.deepcopy(config)
                queries.append(jsearch.Query('caller-only', 1, 'A'))
                config['filter']['min_confidence'] = 99
                self.assertEqual(jsearch.load_plan(path)[0], expected)
                self.assertEqual(jsearch.load_plan(path)[1], [])
                self.assertEqual(parse.call_count, 1)
                stamp = path.stat()
                replacement = Path(folder)/'new.toml'
                changed = original.replace(b'min_confidence = 25', b'min_confidence = 26')
                self.assertNotEqual(changed, original)
                replacement.write_bytes(changed)
                os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                replacement.replace(path)
                self.assertEqual(jsearch.load_plan(path)[0]['filter']['min_confidence'], 26)
                path.write_text('not valid TOML [[[', encoding='utf-8')
                with self.assertRaises(ValueError):
                    jsearch.load_plan(path)

    def test_warm_http_reuses_projection_and_attachments_then_invalidates_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger = root/'applications.ndjson'
            with patch.object(applications, 'queue', side_effect=lambda *a: state()), \
                 patch.object(applications, 'attach_links', wraps=applications.attach_links) as links, \
                 patch.object(applications, 'attach_outcomes', wraps=applications.attach_outcomes) as outcomes, \
                 patch.object(review, 'slim', wraps=review.slim) as project:
                server = review.make_server(root/'db', ledger, 0)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = f'http://127.0.0.1:{server.server_port}/api/queue'
                    replies = []
                    for _ in range(5):
                        with urlopen(url) as response:
                            replies.append(response.read())
                    self.assertEqual(len(set(replies)), 1)
                    self.assertEqual((links.call_count, outcomes.call_count, project.call_count), (1, 1, 1))
                    applications.append_link(applications.links_path(ledger), 'https://example.test/job', 'https://example.test/official')
                    with urlopen(url) as response:
                        changed = json.load(response)
                    self.assertEqual(changed['pending'][0]['jobs'][0]['official_link'], 'https://example.test/official')
                    self.assertEqual(project.call_count, 2)
                finally:
                    server.shutdown()
                    thread.join(2)
                    server.server_close()

    def test_cached_response_tracks_decisions_outcomes_reopen_and_manual_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ledger, database = root/'applications.ndjson', root/'jobs.sqlite'
            with closing(sqlite3.connect(database)) as db, db:
                db.executescript("CREATE TABLE companies(company_key TEXT PRIMARY KEY,name TEXT); "
                    "CREATE TABLE jobs(url TEXT PRIMARY KEY,company_key TEXT,title TEXT,location TEXT,"
                    "source_job_id TEXT,first_seen TEXT,posted_at TEXT,provider_key TEXT,relevance REAL,"
                    "closed_at TEXT,raw TEXT,last_seen TEXT);")
                stamp = datetime.now(timezone.utc).isoformat()
                db.execute('INSERT INTO companies VALUES (?,?)', ('example', 'Example'))
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('https://example.test/job', 'example', 'RTL Engineer', 'Austin, TX',
                     'req-1', stamp, None, 'example', 90, None, json.dumps({'description': 'Design and verify RTL.'}), stamp))
            server = review.make_server(database, ledger, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def get():
                with urlopen(base + '/api/queue', timeout=5) as response:
                    return json.load(response)
            try:
                initial = get()
                token = initial['token']
                ident = initial['pending'][0]['id']
                def post(route, value):
                    request = Request(base + route, json.dumps(value).encode(),
                                      headers={'X-Review-Token': token})
                    with urlopen(request, timeout=5) as response:
                        return json.load(response)
                post('/api/decision', {'id': ident, 'status': 'applied'})
                self.assertEqual(get()['applied'][0]['id'], ident)
                post('/api/outcome', {'id': ident, 'outcome': 'passed'})
                self.assertEqual(get()['applied'][0]['outcome'], 'passed')
                post('/api/decision', {'id': ident, 'status': 'pending'})
                reopened = get()
                self.assertFalse(reopened['applied'])
                self.assertNotIn('outcome', reopened['pending'][0])
                post('/api/decision', {'id': ident, 'status': 'skipped'})
                self.assertEqual(get()['skipped'][0]['id'], ident)
                post('/api/decision', {'id': ident, 'status': 'pending'})
                save = review.manual_intake.save_manual
                def save_and_change_profile(*args, **kwargs):
                    result = save(*args, **kwargs)
                    review.resume_fit.profile_path(ledger).write_text(json.dumps({
                        'version': 1, 'families': [{'id': 'different', 'evidence': 'Synthetic project',
                                                  'all': ['unrelated work']}]}), encoding='utf-8')
                    return result
                with patch.object(review.manual_intake, 'catalog_source', return_value=None), \
                     patch.object(review.manual_intake, 'save_manual', side_effect=save_and_change_profile):
                    post('/api/manual', {'url': 'https://example.test/other', 'company': 'Other Example',
                                        'title': 'Verification Engineer'})
                self.assertEqual([group['company'] for group in get()['pending']], ['Other Example'])
                self.assertEqual(get(), get())
            finally:
                server.shutdown()
                thread.join(2)
                server.server_close()

    def test_plan_changed_while_parsing_is_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'plan.toml'
            path.write_text('[filter]\nmin_confidence = 25\n', encoding='utf-8')
            parser = jsearch.tomllib.load
            calls = []
            def parse_then_change(handle):
                value = parser(handle)
                calls.append(1)
                if len(calls) == 1:
                    path.write_text('[filter]\nmin_confidence = 26\n', encoding='utf-8')
                return value
            with patch.object(jsearch.tomllib, 'load', side_effect=parse_then_change):
                self.assertEqual(jsearch.load_plan(path)[0]['filter']['min_confidence'], 25)
                self.assertEqual(jsearch.load_plan(path)[0]['filter']['min_confidence'], 26)
                self.assertEqual(jsearch.load_plan(path)[0]['filter']['min_confidence'], 26)
                self.assertEqual(len(calls), 2)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                jsearch.load_plan(path)

    def test_a_rewrite_with_an_identical_stat_is_not_served_from_cache(self):
        # ext4 on the VPS gave a same-size rewrite inside one clock tick the
        # identical mtime and ctime (162 of 200 tries, 2026-10-09), and the
        # cache went on serving the old plan.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'plan.toml'
            path.write_text('[filter]\nmin_confidence = 25\n', encoding='utf-8')
            self.assertEqual(jsearch.load_plan(path)[0]['filter']['min_confidence'], 25)
            frozen = path.stat()
            path.write_text('[filter]\nmin_confidence = 26\n', encoding='utf-8')
            with patch.object(Path, 'stat', lambda self, **kwargs: frozen):
                self.assertEqual(jsearch.load_plan(path)[0]['filter']['min_confidence'], 26)
