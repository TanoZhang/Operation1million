"""Diagnose boundaries in the pending fixes; select working source via PYTHONPATH.

Assertions capture observed defects. All persistent test data is temporary.
"""
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import runpy
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jobdisco import applications, store
from jobdisco.validate_sources import Source


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);"
                         "INSERT INTO companies VALUES ('fixture', 'Fixture');")
    store.migrate(path)


def source(provider):
    return Source(provider + ':fixture', 'company_sources', 'fixture', 'Fixture',
                  provider, 'https://example.test/jobs', {})


def row(provider, identity, raw=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                source_job_id=identity, title='RTL Engineer', location='Austin',
                url='https://example.test/job', posted_at=None,
                raw=raw or {'description': 'Design RTL hardware.'})


def main():
    out = {'source': str(Path(store.__file__).resolve())}
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request',
            side_effect=AssertionError('External HTTP prohibited')):
        root = Path(directory)
        with patch.object(store, 'ROOT', root):
            db_path = root / 'identity.sqlite'
            ledger = root / 'applications.ndjson'
            database(db_path)
            with closing(store.connect(db_path)) as db, db:
                store.record_source(db, source('jsearch'), [row('jsearch', 'A')], 'query_limited', 'full', 1)
            group = applications.queue(db_path, ledger)['pending'][0]
            applications.append_decision(ledger, group, 'applied')
            with closing(store.connect(db_path)) as db, db:
                store.record_source(db, source('ashby'), [row('ashby', 'B')], 'complete', 'full', 1)
            assert len(applications.queue(db_path, ledger)['pending']) == 0
            with closing(store.connect(db_path)) as db, db:
                store.record_source(db, source('ashby'), [row('ashby', 'C')], 'complete', 'full', 1)
                aliases = [tuple(r) for r in db.execute('SELECT provider_key, source_job_id FROM job_identities')]
            state = applications.queue(db_path, ledger)
            assert aliases == [('ashby', 'C')] and len(state['pending']) == 0
            out['B27_old_cross_provider_decision_hides_replacement'] = {
                'current_aliases': aliases, 'pending_groups': len(state['pending']),
                'applied_snapshot_identity': state['applied'][0]['jobs'][0]['source_job_id']}

            # Exercise real collector.main with the same synthetic transport harness
            # used in round 5, including record_seen and paid checkpoint callbacks.
            run = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))['run']
            paid_root = root / 'paid'
            paid_root.mkdir()
            first = {'job_id': 'B', 'job_title': 'RTL Engineer', 'employer_name': 'Fixture',
                     'job_apply_link': 'https://example.test/job', 'job_description': 'Design RTL hardware.'}
            assert run(paid_root, 'first', [], paid=[first])[0] == 0
            assert len(applications.queue(paid_root / 'jobs.sqlite', paid_root / 'ledger.ndjson')['pending']) == 1
            rejected_other = dict(first, job_id='A', job_description='5 years experience required.')
            assert run(paid_root, 'second', [], paid=[rejected_other])[0] == 0
            state = applications.queue(paid_root / 'jobs.sqlite', paid_root / 'ledger.ndjson')
            with closing(store.connect(paid_root / 'jobs.sqlite')) as db:
                held_id = db.execute('SELECT source_job_id FROM jobs').fetchone()[0]
                rejected_id = db.execute("SELECT source_job_id FROM seen_jobs WHERE decision<>''").fetchone()[0]
            assert held_id == 'B' and rejected_id == 'A' and len(state['pending']) == 0
            out['B28_rejection_for_another_id_hides_current_job'] = {
                'held_identity': held_id, 'rejected_identity': rejected_id, 'pending_groups': 0}

            export_db = root / 'export.sqlite'
            database(export_db)
            first_day = datetime.now(timezone.utc) - timedelta(days=2)
            closed_day = first_day + timedelta(days=1)
            with closing(store.connect(export_db)) as db, db:
                store.record_source(db, source('ashby'), [row('ashby', 'old')], 'complete', 'full', 1,
                                    stamp=first_day.isoformat())
                db.execute('UPDATE jobs SET closed_at=?', (closed_day.isoformat(),))
            with patch.object(store, 'LOG', root / 'export-history'), \
                 patch('sys.argv', ['job-store', '--db', str(export_db), '--export']), redirect_stdout(io.StringIO()):
                store.main()
                verification = store.verify()
                restored = root / 'export-restored.sqlite'
                database(restored)
                try:
                    store.rebuild(restored)
                except ValueError as exc:
                    failure = str(exc)
                else:
                    raise AssertionError('Expected missing closure-day manifest')
            assert any(status == 'missing-manifest' for _, status in verification)
            out['B29_export_omits_closure_day_manifest'] = {'verification': verification, 'rebuild_error': failure}

            scored = root / 'scored.sqlite'
            restored = root / 'scored-restored.sqlite'
            database(scored)
            database(restored)
            stamp = store.now()
            with patch.object(store, 'LOG', root / 'score-history'):
                with closing(store.connect(scored)) as db, db:
                    delta = store.record_source(db, source('ashby'),
                        [row('ashby', 'score', {'description': 'Design RTL.', 'relevance': {'confidence': 99}})],
                        'complete', 'full', 1, stamp=stamp)
                    store.append_log(db, delta['new_urls'], [], stamp)
                    store.write_manifest(db, stamp, [])
                with patch.object(store, 'calculate_score', return_value=10):
                    with patch.object(store, 'append_scores', side_effect=OSError('Synthetic score append failure')):
                        try:
                            store.rescore(scored)
                        except OSError:
                            pass
                        else:
                            raise AssertionError('Expected score append failure')
                    with patch.object(store, 'append_scores', wraps=store.append_scores) as append:
                        store.rescore(scored)
                        retried_writes = append.call_count
                store.rebuild(restored)
                verification = store.verify()
            with closing(store.connect(scored)) as db:
                live = db.execute('SELECT relevance FROM jobs').fetchone()[0]
            with closing(store.connect(restored)) as db:
                rebuilt = db.execute('SELECT relevance FROM jobs').fetchone()[0]
            assert live == 10 and rebuilt == 99 and retried_writes == 0
            out['B30_rescore_retry_never_publishes_failed_correction'] = {
                'live_score': live, 'rebuilt_score': rebuilt, 'retry_append_calls': retried_writes,
                'history_verifies': all(status == 'ok' for _, status in verification)}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
