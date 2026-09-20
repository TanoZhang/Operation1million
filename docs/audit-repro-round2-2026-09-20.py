"""Second audit: offline boundary reproducers, asserting the observed defects.

Run with PYTHONPATH=src. Uses temporary state and loopback HTTP only.
"""
import argparse
from contextlib import closing, redirect_stdout
import csv
from dataclasses import replace
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from jobdisco import applications, collection_policy, collector as collector_module, jsearch, review, store
from jobdisco.collector import Collector
from jobdisco.collector import clean
from jobdisco.jsearch_access import RequestGuard
from jobdisco.validate_sources import Source


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript('CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);'
                         "INSERT INTO companies VALUES ('fixture', 'Fixture');")
    store.migrate(path)


def row(provider='ashby', identity='direct-1', raw=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                title='RTL Engineer', location='Austin', source_job_id=identity,
                url='https://example.test/job/1', posted_at=None,
                raw=raw or {'description': 'RTL SystemVerilog UVM'})


def source(provider='ashby'):
    return Source(provider + ':fixture', 'company_sources', 'fixture', 'Fixture',
                  provider, 'https://example.test/jobs', {})


def main():
    results = {}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.object(store, 'ROOT', root), patch.object(store, 'LOG', root / 'history'):
            db_path = root / 'identity.sqlite'
            database(db_path)
            ledger = root / 'applications.ndjson'
            with closing(store.connect(db_path)) as db, db:
                store.record_source(db, source('jsearch'), [row('jsearch', 'search-1')],
                                    'query_limited', 'full', 1)
            group = applications.queue(db_path, ledger)['pending'][0]
            applications.append_decision(ledger, group, 'applied')
            assert not applications.queue(db_path, ledger)['pending']
            with closing(store.connect(db_path)) as db, db:
                store.record_source(db, source(), [row()], 'complete', 'full', 1)
                aliases = [tuple(r) for r in db.execute(
                    'SELECT provider_key, source_job_id FROM job_identities ORDER BY provider_key')]
            state = applications.queue(db_path, ledger)
            assert len(state['pending']) == len(state['applied']) == 1
            assert len(aliases) == 2
            results['B10_provider_upgrade_loses_decision'] = {
                'pending': len(state['pending']), 'applied': len(state['applied']), 'aliases': aliases}

            scored = root / 'scored.sqlite'
            database(scored)
            stale = row(raw={'description': 'General ledger and tax reporting.',
                             'relevance': {'confidence': 99}})
            stale['title'] = 'Accountant'
            stamp = store.now()
            with closing(store.connect(scored)) as db, db:
                delta = store.record_source(db, source(), [stale], 'complete', 'full', 1, stamp=stamp)
                store.append_log(db, delta['new_urls'], [], stamp)
                store.write_manifest(db, stamp, [])
            store.rescore(scored)
            with closing(store.connect(scored)) as db:
                corrected = db.execute('SELECT relevance FROM jobs').fetchone()[0]
            restored = root / 'restored.sqlite'
            database(restored)
            store.rebuild(restored)
            with closing(store.connect(restored)) as db:
                replayed = db.execute('SELECT relevance FROM jobs').fetchone()[0]
            assert corrected == 0 and replayed == 99
            results['B11_rescore_not_durable'] = {'after_rescore': corrected, 'after_rebuild': replayed}

            settings, _ = jsearch.load_plan()
            guard = RequestGuard(path=root / 'usage.sqlite', daily_limit=10)
            session = Mock()
            valid = {'job_id': 'good', 'job_title': 'RTL Engineer',
                     'employer_name': 'Fixture', 'job_apply_link': 'https://example.test/good'}
            session.get.return_value = Mock(status_code=200, headers={},
                json=lambda: {'status': 'OK', 'data': {'jobs': [dict(valid, job_id=['invalid']), valid]}})
            client = jsearch.Client({'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
                                     'connection': {'auth_header': 'X-API-Key'}}, settings, guard, session=session)
            checkpoint, seen = Mock(), Mock()
            with patch.dict(os.environ, {'JSEARCH_API_KEY': 'offline-placeholder'}):
                try:
                    jsearch.collect([jsearch.Query('RTL Engineer', 1, 'A')], client, settings, {}, Mock(),
                                    checkpoint=checkpoint, record_seen=seen)
                except TypeError as exc:
                    assert 'unhashable' in str(exc)
                else:
                    raise AssertionError('Expected malformed ID to abort paging')
            assert guard.credits == 1 and checkpoint.call_count == seen.call_count == 0
            results['B12_paid_malformed_id_loses_page'] = {
                'credits': guard.credits, 'checkpoint_calls': checkpoint.call_count, 'seen_calls': seen.call_count}

            stats_guard = RequestGuard(path=root / 'statistics-usage.sqlite', daily_limit=10)
            stats_session = Mock()
            pages = [[dict(valid, job_id=str(i), job_apply_link=f'https://example.test/{i}') for i in range(10)],
                     [dict(valid, job_id='last', job_apply_link='https://example.test/last')]]
            stats_session.get.side_effect = [Mock(status_code=200, headers={},
                json=lambda page=page: {'status': 'OK', 'data': {'jobs': page}}) for page in pages]
            stats_client = jsearch.Client({'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
                'connection': {'auth_header': 'X-API-Key'}}, settings, stats_guard, session=stats_session)
            output = root / 'statistics-run'
            with patch.object(collector_module, 'load_sources', return_value=[]), \
                 patch.object(collector_module, 'load_credentials'), \
                 patch.object(collector_module, 'RequestGuard', return_value=stats_guard), \
                 patch.object(jsearch, 'Client', return_value=stats_client), \
                 patch.dict(os.environ, {'JSEARCH_API_KEY': 'offline-placeholder'}), \
                 patch('sys.argv', ['collector', '--db', str(db_path), '--output', str(output),
                    '--jsearch-only', '--jsearch-query', 'RTL Engineer', '--jsearch-pages', '2', '--no-store']), \
                 redirect_stdout(io.StringIO()):
                assert collector_module.main() == 0
            with (output / 'company_results.csv').open(newline='', encoding='utf-8') as handle:
                report = next(csv.DictReader(handle))
            assert stats_guard.attempts == 2 and report['requests'] == '1'
            results['B16_query_request_count_underreported'] = {
                'HTTP_dispatches': stats_guard.attempts, 'reported_requests': int(report['requests'])}

            workday = replace(source('workday'), fields={'tenant': 'fixture', 'site': 'External', 'workday_host': 'wd1'})
            args = argparse.Namespace(max_pages=2, max_jobs=100, delay=0, timeout=1, retries=0,
                                      source_state=root / 'pause.sqlite')
            with patch.object(collection_policy, 'robots_delay', return_value=None):
                collector = Collector(workday, args)
            collector.strategy, collector.watermark = 'conditional', '"fixture-etag"'
            collector.session.request = Mock(return_value=Mock(status_code=405, headers={}))
            status, reason = collector.run()
            method = collector.session.request.call_args.args[0]
            assert status == 'paused' and method == 'GET'
            results['B13_post_validator_uses_get'] = {'method': method, 'status': status, 'reason': reason}

            # Capture acceptance deterministically, then leave one connection
            # idle before sending a second complete request.
            server = review.make_server(db_path, ledger, port=0)
            accepted = threading.Event()
            original_accept = server.get_request
            def get_request():
                value = original_accept()
                accepted.set()
                return value
            server.get_request = get_request
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            nested = {'jsearch': {'job_description': 'Design RTL and verify hardware.'}}
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute('UPDATE jobs SET raw=?', (json.dumps(nested),))
            with urlopen(f'http://127.0.0.1:{server.server_port}/api/job?url=https://example.test/job/1', timeout=2) as response:
                detail = json.load(response)['description']
            assert detail == '' and jsearch.description_text({'raw': nested})
            results['R02_confirmed_nested_description'] = {'stored_prose': True, 'HTTP_description': detail}
            accepted.clear()
            idle = socket.create_connection(server.server_address, timeout=2)
            assert accepted.wait(2)
            waiting = socket.create_connection(server.server_address, timeout=2)
            waiting.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
            waiting.settimeout(0.4)
            try:
                waiting.recv(1024)
                raise AssertionError('Expected single HTTP server to block behind idle socket')
            except socket.timeout:
                pass
            idle.close()
            waiting.settimeout(2)
            response = waiting.recv(1024)
            assert b'200 OK' in response
            waiting.close()
            server.shutdown()
            server.server_close()
            thread.join(2)
            results['B14_idle_socket_blocks_review'] = {'second_request_blocked': True,
                                                       'recovers_after_idle_close': True}

            bash = Path('C:/Program Files/Git/bin/bash.exe') if os.name == 'nt' else Path(shutil.which('bash') or '/missing')
            if bash.is_file():
                fixture_root = root / 'backup-fixture'
                data = fixture_root / 'fixture/data'
                for folder in ('runs', 'manifests', 'operational'):
                    (data / folder).mkdir(parents=True)
                log_name = store.now()[:10]
                log = data / f'runs/{log_name}.ndjson.gz'
                original = gzip.compress(b'{}\n', mtime=0)
                log.write_bytes(gzip.compress(b'{"changed":true}\n', mtime=0))
                (data / f'manifests/{log_name}.json').write_text(json.dumps({
                    'run_date': log_name, 'file': f'runs/{log_name}.ndjson.gz',
                    'sha256': hashlib.sha256(original).hexdigest()}), encoding='utf-8')
                (data / 'operational/applications.ndjson').write_text(
                    '{"url":"https://example.test/1","at":"fixture","status":"applied"}\n', encoding='utf-8')
                for name in ('jsearch_usage.sqlite', 'source_access.sqlite'):
                    with closing(sqlite3.connect(data / 'operational' / name)) as db:
                        db.execute('CREATE TABLE fixture(value TEXT)')
                (data / 'operational/seen_jobs.ndjson.gz').write_bytes(gzip.compress(b'', mtime=0))
                snapshot = fixture_root / 'fixture/sqlite/job_discovery.sqlite'
                snapshot.parent.mkdir()
                with closing(sqlite3.connect(snapshot)) as db:
                    db.execute('CREATE TABLE jobs(closed_at TEXT)')
                backup = fixture_root / 'backup'
                # The production script rotates recursively; every target is
                # explicitly inside this freshly created temporary fixture.
                assert backup.resolve().is_relative_to(root.resolve())
                for generation in ('current', 'previous'):
                    old_copy = backup / generation
                    shutil.copytree(data, old_copy)
                    (old_copy / f'runs/{log_name}.ndjson.gz').write_bytes(original)
                    (old_copy / 'sqlite').mkdir()
                    shutil.copy2(snapshot, old_copy / 'sqlite/job_discovery.sqlite')
                    (old_copy / 'good-generation').write_text('Keep', encoding='utf-8')
                    with patch.object(store, 'LOG', old_copy):
                        assert store.verify() == [(log_name, 'ok')]
                driver = fixture_root / 'driver.sh'
                target = Path(__file__).resolve().parents[1] / 'deploy/local/backup-from-vps.sh'
                driver.write_text('ssh() { tar czf - -C fixture data sqlite; }\nsource '
                                  + shlex.quote(target.as_posix()) + ' backup\n', encoding='utf-8', newline='\n')
                statuses = []
                for _ in range(2):
                    result = subprocess.run([str(bash), 'driver.sh'], cwd=fixture_root,
                        env=dict(os.environ, JOBDISCO_VPS_DATA='/unused/data', JOBDISCO_PYTHON=Path(sys.executable).as_posix()),
                        capture_output=True, text=True)
                    assert result.returncode == 0, result.stdout + result.stderr
                    statuses.append(result.returncode)
                with patch.object(store, 'LOG', backup / 'current'):
                    verification = store.verify()
                assert verification == [(log_name, 'MISMATCH')]
                assert not list(backup.glob('*/good-generation'))
                results['B15_backup_accepts_checksum_mismatch'] = {
                    'backup_exit_codes': statuses, 'verification': verification, 'both_good_generations_replaced': True}

            # Read-only query benchmark; index experiment stays in a temporary DB.
            with closing(sqlite3.connect(':memory:')) as db:
                db.executescript('CREATE TABLE jobs(url TEXT PRIMARY KEY, provider_key TEXT, company_key TEXT, '
                                 'source_job_id TEXT, closed_at TEXT);'
                                 'CREATE INDEX jobs_open ON jobs(company_key, closed_at);')
                db.executemany('INSERT INTO jobs VALUES (?, ?, ?, ?, NULL)',
                    [(f'https://example.test/{i}', 'jsearch', 'fixture', str(i)) for i in range(5000)])
                sql = ('SELECT url FROM jobs WHERE provider_key=? AND source_job_id=? '
                       'AND url<>? AND closed_at IS NULL')
                params = [('jsearch', str(i), f'https://example.test/{i}') for i in range(500)]
                before_plan = [r[3] for r in db.execute('EXPLAIN QUERY PLAN ' + sql, params[0])]
                started = time.perf_counter()
                before = [db.execute(sql, p).fetchall() for p in params]
                before_time = time.perf_counter() - started
                db.execute('CREATE INDEX audit_identity_lookup ON jobs(provider_key, source_job_id, company_key, url) '
                           'WHERE closed_at IS NULL')
                after_plan = [r[3] for r in db.execute('EXPLAIN QUERY PLAN ' + sql, params[0])]
                started = time.perf_counter()
                after = [db.execute(sql, p).fetchall() for p in params]
                after_time = time.perf_counter() - started
                assert before == after
                results['O08_identity_lookup_index'] = {'rows': 5000, 'lookups': 500,
                    'before_plan': before_plan, 'after_plan': after_plan,
                    'before_seconds': round(before_time, 6), 'after_seconds': round(after_time, 6)}
            titles = ['RTL Engineer', ' Engineer ', 'ASIC &amp; FPGA', '<b>Intern</b>', '', None] * 1000
            def fast_clean(value):
                text = str(value or '')
                return clean(value) if '<' in text or '&' in text else text.strip()
            started = time.perf_counter()
            before = [clean(v) for v in titles]
            before_time = time.perf_counter() - started
            started = time.perf_counter()
            after = [fast_clean(v) for v in titles]
            after_time = time.perf_counter() - started
            assert before == after
            results['O09_plain_title_fast_path'] = {'inputs': len(titles),
                'before_seconds': round(before_time, 6), 'after_seconds': round(after_time, 6)}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
