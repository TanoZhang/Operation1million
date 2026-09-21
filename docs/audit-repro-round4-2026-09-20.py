"""Offline diagnostics: assertions describe four defects, not desired behavior."""
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import urlopen
from urllib.parse import urlencode

from jobdisco import applications, collection_policy, collector, review, store
from jobdisco.validate_sources import Source


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);"
                         "INSERT INTO companies VALUES ('fixture', 'Fixture');")
    store.migrate(path)


def source(provider):
    return Source(provider + ':fixture', 'company_sources', 'fixture', 'Fixture',
                  provider, 'https://example.test/board', {})


def row(identity, raw=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key='greenhouse',
                title='RTL Engineer', location='Austin', source_job_id=identity,
                url='https://example.test/job/' + identity, posted_at=None,
                raw=raw or {'description': 'Design RTL hardware.'})


def main():
    out = {'source': str(Path(store.__file__).resolve())}
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request',
            side_effect=AssertionError('External HTTP prohibited')):
        root = Path(directory)
        args = SimpleNamespace(max_pages=3, max_jobs=100, delay=0, retries=0,
                               timeout=1, source_state=root / 'pauses.sqlite')
        with patch.object(store, 'ROOT', root), patch.object(store, 'LOG', root / 'history'):
            path = root / 'rejected.sqlite'
            database(path)
            board = source('greenhouse')
            initial = [row(str(i)) for i in range(5)]
            with closing(store.connect(path)) as db, db:
                store.record_source(db, board, initial, 'complete', 'full', 1)
            items = [dict(id=str(i), title='RTL Engineer', absolute_url=r['url'])
                     for i, r in enumerate(initial)]
            items[-1].pop('title')
            with patch.object(collection_policy, 'robots_delay', return_value=None):
                worker = collector.Collector(board, args)
            worker.fetch = Mock(return_value=Mock(json=lambda: {'jobs': items}))
            status, _ = worker.run()
            with closing(store.connect(path)) as db, db:
                delta = store.record_source(db, board, worker.jobs, status, 'full', 1)
                closed = db.execute('SELECT url FROM jobs WHERE closed_at IS NOT NULL').fetchall()
            assert status == 'complete' and len(worker.rejected) == 1 and len(closed) == 1
            out['B20_rejected_record_closes_advertised_job'] = {
                'status': status, 'rejected': len(worker.rejected), 'closed': delta['closed']}

            export_db = root / 'export.sqlite'
            database(export_db)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            with closing(store.connect(export_db)) as db, db:
                store.record_source(db, board, [row('old')], 'complete', 'full', 1, stamp=yesterday)
            with patch('sys.argv', ['job-store', '--db', str(export_db), '--export']), redirect_stdout(io.StringIO()):
                try:
                    store.main()
                except FileExistsError as exc:
                    out['B21_export_rejects_historical_jobs'] = str(exc)
                else:
                    raise AssertionError('Historical export unexpectedly succeeded')

            with patch.object(collection_policy, 'robots_delay', return_value=None):
                worker = collector.Collector(source('eightfold'), args)
            payload = {'data': {'count': 2, 'positions': [
                {'id': 'A', 'title': 'RTL Engineer', 'url': 'https://example.test/job/A'},
                {'id': 'B', 'title': 'FPGA Engineer', 'url': 'https://example.test/job/B'}]}}
            worker.fetch = Mock(return_value=Mock(json=lambda: payload))
            status, _ = worker.run()
            assert status == 'complete' and len(worker.jobs) == 1
            assert worker.jobs[0]['url'] == worker.source.access_url
            out['B22_missing_provider_path_collapses_jobs'] = {
                'status': status, 'input_jobs': 2, 'stored_jobs': len(worker.jobs),
                'url': worker.jobs[0]['url'], 'rejected': len(worker.rejected)}

            history_db = root / 'review.sqlite'
            ledger = root / 'applications.ndjson'
            database(history_db)
            old = row('A', {'description': 'Old requisition A: design RTL.'})
            with closing(store.connect(history_db)) as db, db:
                store.record_source(db, board, [old], 'complete', 'full', 1)
            group = applications.queue(history_db, ledger)['pending'][0]
            applications.append_decision(ledger, group, 'applied')
            new = dict(row('B', {'description': 'New requisition B: verify FPGA.'}), url=old['url'])
            with closing(store.connect(history_db)) as db, db:
                store.record_source(db, board, [new], 'complete', 'full', 1)
            state = applications.queue(history_db, ledger)
            assert state['applied'][0]['jobs'][0]['source_job_id'] == 'A'
            server = review.make_server(history_db, ledger, port=0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/api/job?' + urlencode({'url': old['url']})
                with urlopen(url, timeout=3) as response:
                    detail = json.load(response)['description']
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
            assert detail == new['raw']['description']
            out['B23_history_detail_reads_replacement'] = {
                'applied_identity': 'A', 'description_returned': detail,
                'pending_identity': state['pending'][0]['jobs'][0]['source_job_id']}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
