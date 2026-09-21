"""Offline audit through collector.main, including a correction of B20."""
from contextlib import closing, redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from jobdisco import applications, collection_policy, collector, jsearch, store
from jobdisco.jsearch_access import RequestGuard
from jobdisco.validate_sources import Source


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);"
                         "INSERT INTO companies VALUES ('fixture', 'Fixture');")
    store.migrate(path)


def response(payload=None, text='', etag=None, status=200):
    result = Mock(status_code=status, text=text)
    result.headers = {'content-type': 'application/json' if payload is not None else 'text/html'}
    if etag:
        result.headers['ETag'] = etag
    result.json.return_value = payload
    return result


def run(root, name, sources, direct=(), paid=None):
    path = root / 'jobs.sqlite'
    if not path.exists():
        database(path)
    settings, _ = jsearch.load_plan()
    guard = RequestGuard(path=root / 'usage.sqlite')
    session = Mock()
    session.get.return_value = response({'status': 'OK', 'data': {'jobs': paid or []}})
    client = jsearch.Client({'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2',
                            'connection': {'auth_header': 'X-API-Key'}}, settings, guard, session=session)
    argv = ['collector', '--db', str(path), '--output', str(root / name)]
    if paid is not None:
        argv += ['--jsearch-only', '--jsearch-query', 'RTL', '--jsearch-pages', '1']
    with patch.object(store, 'LOG', root / 'history'), \
         patch.object(collector, 'SOURCE_STATE', root / 'pauses.sqlite'), \
         patch.object(collector, 'load_sources', return_value=sources), \
         patch.object(collector, 'load_credentials'), \
         patch.object(collector, 'RequestGuard', return_value=guard), \
         patch.object(jsearch, 'Client', return_value=client), \
         patch.object(collection_policy, 'robots_delay', return_value=None), \
         patch('requests.sessions.Session.request', side_effect=list(direct)) as dispatch, \
         patch('time.sleep'), patch.dict(os.environ, {'JSEARCH_API_KEY': 'synthetic-test-key'}), \
         patch('sys.argv', argv), redirect_stdout(io.StringIO()):
        code = collector.main()
    with (root / name / 'company_results.csv').open(encoding='utf-8', newline='') as handle:
        reports = list(csv.DictReader(handle))
    return code, reports, dispatch.call_count


def main():
    out = {'source': str(Path(collector.__file__).resolve())}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.object(store, 'ROOT', root):
            paid_root = root / 'paid'
            paid_root.mkdir()
            original = {'job_id': 'A', 'job_title': 'RTL Engineer', 'employer_name': 'Fixture',
                        'job_apply_link': 'https://example.test/job/A',
                        'job_description': 'Design RTL hardware.'}
            assert run(paid_root, 'first', [], paid=[original])[0] == 0
            revised = dict(original, job_description='5 years experience required.')
            assert run(paid_root, 'second', [], paid=[revised])[0] == 0
            with closing(store.connect(paid_root / 'jobs.sqlite')) as db:
                decision = db.execute('SELECT decision FROM seen_jobs').fetchone()[0]
                raw = json.loads(db.execute('SELECT raw FROM jobs').fetchone()[0])
            pending = applications.queue(paid_root / 'jobs.sqlite', paid_root / 'applications.ndjson')['pending']
            assert decision == 'required_experience_over_2_years' and len(pending) == 1
            assert raw['job_description'] == original['job_description']
            out['B24_rejected_update_leaves_old_accepted_job'] = {
                'latest_seen_decision': decision, 'pending_groups': len(pending),
                'stored_description': raw['job_description']}

            ti = Source('ti_careers:fixture', 'company_sources', 'fixture', 'Fixture',
                        'ti_careers', 'https://example.test/en/sites/CX/jobs', {})
            shell = '<base data-apibaseurl="https://api.example.test/" data-sitenumber="CX">'
            items = [{'Id': str(i), 'Title': 'RTL Engineer'} for i in range(5)]
            payload = lambda rows: {'items': [{'TotalJobsCount': len(rows), 'requisitionList': rows}]}
            ti_root = root / 'ti'
            ti_root.mkdir()
            assert run(ti_root, 'first', [ti], [response(text=shell), response(payload(items))])[0] == 0
            code, reports, _ = run(ti_root, 'second', [ti], [response(text=shell), response(payload(items[:4]))])
            with closing(store.connect(ti_root / 'jobs.sqlite')) as db:
                held = db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]
                provider = db.execute('SELECT provider_key FROM jobs LIMIT 1').fetchone()[0]
                state_provider = db.execute('SELECT provider_key FROM source_state').fetchone()[0]
            assert code == 0 and held == 5 and provider == 'oracle_cloud' and state_provider == 'ti_careers'
            out['B25_ti_provider_mismatch_prevents_closure'] = {
                'returned_jobs': 4, 'open_jobs': held, 'job_provider': provider,
                'state_provider': state_provider, 'status': reports[0]['direct_status']}

            etag_root = root / 'etag'
            etag_root.mkdir()
            assert run(etag_root, 'first', [ti], [response(text=shell, etag='"shell-v1"'), response(payload(items[:1]))])[0] == 0
            code, reports, calls = run(etag_root, 'second', [ti],
                                      [response(status=304), response(payload(items[:2]))])
            with closing(store.connect(etag_root / 'jobs.sqlite')) as db:
                held = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            assert code == 0 and calls == 1 and held == 1 and reports[0]['direct_status'] == 'unchanged'
            out['B26_shell_etag_suppresses_jobs_api'] = {
                'requests_second_pass': calls, 'status': reports[0]['direct_status'],
                'jobs_api_read': False, 'held_jobs': held}

            correction_root = root / 'correction'
            correction_root.mkdir()
            green = Source('greenhouse:fixture', 'company_sources', 'fixture', 'Fixture',
                           'greenhouse', 'https://example.test/jobs', {})
            items = [{'id': str(i), 'title': 'RTL Engineer', 'absolute_url': f'https://example.test/job/{i}'} for i in range(5)]
            assert run(correction_root, 'first', [green], [response({'jobs': items})])[0] == 0
            items[-1].pop('title')
            code, reports, _ = run(correction_root, 'second', [green], [response({'jobs': items})])
            with closing(store.connect(correction_root / 'jobs.sqlite')) as db:
                closed = db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NOT NULL').fetchone()[0]
            assert code == 2 and reports[0]['direct_status'] == 'partial' and closed == 0
            out['B20_retracted_main_prevents_closure'] = {
                'exit_code': code, 'status': reports[0]['direct_status'], 'closed': closed}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
