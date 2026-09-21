"""Third offline audit; assertions capture current defects, not desired behavior.

Use PYTHONPATH to select either the audited worktree or the user's source tree.
All data is synthetic and temporary. No external HTTP is allowed.
"""
import argparse
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jobdisco import applications, collection_policy, collector, jsearch, store
from jobdisco.validate_sources import Source


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript('CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);'
                         "INSERT INTO companies VALUES ('fixture', 'Fixture');")
    store.migrate(path)


def source(provider):
    return Source(provider + ':fixture', 'company_sources', 'fixture', 'Fixture',
                  provider, 'https://example.test/sitemap.xml', {})


def row(provider='eightfold', identity='A', title='RTL Engineer', raw=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                title=title, location='Austin', source_job_id=identity,
                url='https://example.test/job', posted_at=None,
                raw=raw if raw is not None else {'description': 'Design RTL and verify hardware.'})


def main():
    results = {'source': str(Path(store.__file__).resolve())}
    with TemporaryDirectory() as directory, \
         patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP prohibited')):
        root = Path(directory)
        with patch.object(store, 'ROOT', root), patch.object(store, 'LOG', root / 'history'):
            live = root / 'failed.sqlite'
            database(live)
            direct = source('eightfold')
            fixture = SimpleNamespace(jobs=[row()], rejected=[], requests=1, listed=None,
                                      etag=None, last_modified=None, session=Mock(),
                                      run=lambda: ('complete', ''))
            with patch.object(collector, 'load_sources', return_value=[direct]), \
                 patch.object(collector, 'load_credentials'), \
                 patch.object(collector, 'Collector', return_value=fixture), \
                 patch.object(collector, 'RequestGuard', return_value=Mock()), \
                 patch.object(store, 'append_log', side_effect=OSError('Synthetic append failure')), \
                 patch('sys.argv', ['collector', '--db', str(live), '--output', str(root / 'run')]), \
                 redirect_stdout(io.StringIO()):
                try:
                    collector.main()
                except OSError as exc:
                    assert 'Synthetic append failure' in str(exc)
                else:
                    raise AssertionError('Expected injected append failure')
            with closing(store.connect(live)) as db:
                live_count = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            restored = root / 'restored.sqlite'
            database(restored)
            store.rebuild(restored)
            with closing(store.connect(restored)) as db:
                restored_count = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            strategy, watermark = store.plan(direct, store.load_state(restored))
            assert live_count == 1 and restored_count == 0
            assert strategy == 'since' and watermark
            assert all(status == 'ok' for _, status in store.verify())
            results['B17_failure_seal_commits_unlogged_rows'] = {
                'live_rows': live_count, 'restored_rows': restored_count,
                'restored_strategy': strategy, 'history_verifies': True}

            rules = jsearch.load_plan()[0]['filter']
            first = row('jsearch', 'A', 'RTL Intern', {'job_description': '5 years experience required.'})
            second = row('jsearch', 'B', 'RTL Engineer', {'job_id': 'B'})
            assert jsearch.rejection_reason(first, rules) == ''
            assert jsearch.rejection_reason(second, rules) == ''
            outcomes = {}
            for batched in (False, True):
                db_path = root / ('batched.sqlite' if batched else 'sequential.sqlite')
                database(db_path)
                with closing(store.connect(db_path)) as db, db:
                    for batch in ([[first, second]] if batched else [[first], [second]]):
                        store.record_source(db, source('jsearch'), batch, 'query_limited', 'full', 1)
                    current = dict(db.execute('SELECT * FROM jobs').fetchone())
                    aliases = [r[0] for r in db.execute('SELECT source_job_id FROM job_identities ORDER BY source_job_id')]
                pending = applications.queue(db_path, root / ('batch.ndjson' if batched else 'sequence.ndjson'))['pending']
                outcomes['batched' if batched else 'sequential'] = {
                    'current_identity': current['source_job_id'], 'aliases': aliases,
                    'inherited_description': json.loads(current['raw']).get('job_description'),
                    'pending_groups': len(pending)}
            assert outcomes['batched']['pending_groups'] == 0
            assert outcomes['sequential']['pending_groups'] == 1
            assert outcomes['batched']['aliases'] == ['A', 'B']
            assert outcomes['sequential']['aliases'] == ['B']
            results['B18_batch_reuse_contaminates_new_requisition'] = outcomes

            sitemap_source = source('renesas_careers')
            args = argparse.Namespace(max_pages=3, max_jobs=10, delay=0, timeout=1,
                                      retries=0, source_state=root / 'pauses.sqlite')
            sitemap_db = root / 'sitemap.sqlite'
            database(sitemap_db)
            identities = []
            urls = ['https://example.test/job/old-title-jid-6866',
                    'https://example.test/job/new-title-jid-6866']
            for url in urls:
                with patch.object(collection_policy, 'robots_delay', return_value=None):
                    worker = collector.Collector(sitemap_source, args)
                xml = f'<urlset><url><loc>{url}</loc></url></urlset>'.encode()
                job = {'@type': 'JobPosting', 'title': 'RTL Engineer', 'url': url,
                       'description': 'Design RTL and verify hardware.'}
                html = '<script type="application/ld+json">' + json.dumps(job) + '</script>'
                worker.fetch = Mock(side_effect=[Mock(content=xml), Mock(text=html)])
                status, _ = worker.run()
                assert status == 'complete'
                identities.append(worker.jobs[0]['source_job_id'])
                with closing(store.connect(sitemap_db)) as db, db:
                    store.record_source(db, sitemap_source, worker.jobs, status, 'full', 2, listed=worker.listed)
            with closing(store.connect(sitemap_db)) as db:
                open_count = db.execute('SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]
            assert identities == [None, None] and open_count == 2
            assert all(collector.html_job_id(url, 'renesas_careers') == '6866' for url in urls)
            results['B19_sitemap_identity_helper_not_wired'] = {
                'collected_ids': identities, 'helper_id': '6866', 'open_rows_after_reslug': open_count}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
