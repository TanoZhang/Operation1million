"""Offline store audit: temporary state, synthetic rows, no external HTTP."""
from contextlib import closing
import copy
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import random
import runpy
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jobdisco import applications, collector, jsearch, store
from jobdisco.validate_sources import Source

HELPER = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))


def source(provider='greenhouse'):
    return Source(provider + ':fixture', 'company_sources', 'fixture', 'Fixture', provider, 'https://example.test/jobs', {})


def row(ident='A', url='https://example.test/A', provider='greenhouse', raw=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                title='RTL Engineer', location='Austin', source_job_id=ident, url=url,
                posted_at=None, raw=raw if raw is not None else {'description': 'Design RTL hardware.'})


def main():
    out = {'source': str(Path(store.__file__).resolve())}
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP forbidden')):
        root = Path(directory)
        with patch.object(store, 'ROOT', root):
            def database(name):
                path = root / (name + '.sqlite')
                HELPER['database'](path)
                return path

            # B58: a "duplicate" description is removed even when there is no full one.
            path = database('slim')
            original = row(raw={'description_short': '5 years of experience required.'})
            before = jsearch.rejection_reason(copy.deepcopy(original), jsearch.load_plan()[0]['filter'])
            with closing(store.connect(path)) as db, db:
                store.record_source(db, source(), [original], 'complete', 'full', 1)
                retained = json.loads(db.execute('SELECT raw FROM jobs').fetchone()[0])
            pending = applications.queue(path, root / 'slim-applications.ndjson')['pending']
            assert before == 'required_experience_over_2_years' and len(pending) == 1
            out['B58_slim_drops_only_description'] = {'before': before, 'retained_raw': retained, 'pending': len(pending)}

            # B59: moving A and reusing its old address for B must keep both IDs.
            outcomes = {}
            for label, reverse in [('move_first', False), ('replacement_first', True)]:
                path = database(label)
                with patch.object(store, 'LOG', root / (label + '-log')), closing(store.connect(path)) as db, db:
                    initial = store.record_source(db, source(), [row(url='https://example.test/shared')], 'complete', 'full', 1)
                    store.append_log(db, initial['new_urls'], [], initial['stamp'], source_id=source().source_id)
                    batch = [row(url='https://example.test/new-A'), row('B', 'https://example.test/shared')]
                    delta = store.record_source(db, source(), list(reversed(batch)) if reverse else batch, 'complete', 'full', 1)
                    store.append_log(db, delta['new_urls'] + delta['changed_urls'], delta['closed_urls'], delta['stamp'], seen_urls=delta['seen_urls'], source_id=source().source_id)
                    store.write_manifest(db, delta['stamp'], [])
                    outcomes[label] = {'ids': [r[0] for r in db.execute('SELECT source_job_id FROM jobs ORDER BY source_job_id')], 'status': delta['status']}
                with patch.object(store, 'LOG', root / (label + '-log')):
                    restored = database(label + '-restored')
                    store.rebuild(restored)
                    with closing(store.connect(restored)) as db:
                        outcomes[label]['rebuilt_ids'] = [r[0] for r in db.execute('SELECT source_job_id FROM jobs ORDER BY source_job_id')]
                    assert outcomes[label]['rebuilt_ids'] == outcomes[label]['ids']
            assert outcomes['move_first']['ids'] == ['B'] and outcomes['replacement_first']['ids'] == ['A', 'B']
            out['B59_batch_order_loses_moved_requisition'] = outcomes

            # B60: the shard threshold only rolls existing data; it cannot split a member.
            path = database('shards')
            stamp = store.now()
            rng = random.Random(42)
            batch = [row(str(i), f'https://example.test/{i}', raw={'description': ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(500))}) for i in range(12)]
            with patch.object(store, 'LOG', root / 'shard-log'), patch.object(store, 'MAX_DAILY_LOG_BYTES', 1024), closing(store.connect(path)) as db, db:
                delta = store.record_source(db, source(), batch, 'complete', 'full', 1)
                store.append_log(db, delta['new_urls'], [], stamp)
                store.write_manifest(db, stamp, [])
                size = store.daily_log(stamp).stat().st_size
                largest_record = max(len(gzip.compress(line.encode(), mtime=0)) for line in store.log_lines(store.daily_log(stamp)))
                assert largest_record < 1024 < size and all(state == 'ok' for _, state in store.verify())
                out['B60_single_append_exceeds_shard_limit'] = {'configured_bytes': 1024, 'written_bytes': size, 'largest_individual_record': largest_record, 'records': len(batch), 'verify': 'ok'}

            # B61: an authoritative direct description is mixed with a stale paid body.
            path = database('enrichment')
            paid = row('paid-A', provider='jsearch', raw={'job_description': '5 years of experience required.'})
            paid['title'] = 'RTL Intern'
            direct = row('direct-A', raw={'content': '2 years of experience required.'})
            assert jsearch.rejection_reason(copy.deepcopy(direct), jsearch.load_plan()[0]['filter']) == ''
            with closing(store.connect(path)) as db, db:
                store.record_source(db, source('jsearch'), [paid], 'query_limited', 'full', 1)
                store.record_source(db, source(), [direct], 'complete', 'full', 1)
                current = dict(db.execute('SELECT * FROM jobs').fetchone())
            current['raw'] = json.loads(current['raw'])
            retained = copy.deepcopy(current['raw'])
            reason = jsearch.rejection_reason(current, jsearch.load_plan()[0]['filter'])
            pending = applications.queue(path, root / 'enrichment-applications.ndjson')['pending']
            assert reason == 'required_experience_over_2_years' and len(pending) == 0
            out['B61_old_paid_description_overrules_current_direct'] = {'retained_raw': retained, 'reason': reason, 'pending': 0}

            # Candidate already fixed in concurrent work: retain as an observation only.
            path = database('validator')
            with closing(store.connect(path)) as db, db:
                store.record_source(db, source(), [row()], 'complete', 'full', 1, etag='"version-one"')
                changed = row(raw={'description': 'Changed current description.'})
                store.record_source(db, source(), [changed], 'complete', 'conditional', 2)
            state = store.load_state(path)
            strategy, validator = store.plan(source(), state)
            out['concurrent_validator_fix_control'] = {'next_strategy': strategy, 'next_if_none_match': validator, 'latest_response_etag': None}

            # B62: the clock can seal a day after append but before its manifest exists.
            target = root / 'midnight'
            target.mkdir()
            start = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
            current_clock = [start.isoformat()]
            original_append = store.append_log
            def append_then_midnight(*args, **kwargs):
                result = original_append(*args, **kwargs)
                current_clock[0] = (start + timedelta(seconds=2)).isoformat()
                return result
            payload = {'jobs': [{'id': 'A', 'title': 'RTL Engineer', 'absolute_url': 'https://example.test/A'}]}
            with patch.object(store, 'now', side_effect=lambda: current_clock[0]), patch.object(store, 'append_log', side_effect=append_then_midnight):
                try:
                    HELPER['run'](target, 'pass', [source()], [HELPER['response'](payload)])
                except FileExistsError as exc:
                    failure = str(exc)
                else:
                    raise AssertionError('Expected manifest to be sealed before completion')
            with patch.object(store, 'LOG', target / 'history'):
                verification = store.verify()
                assert any(state == 'missing-manifest' for _, state in verification)
                restored = database('midnight-restored')
                try:
                    store.rebuild(restored)
                except ValueError as exc:
                    rebuild_error = str(exc)
                else:
                    raise AssertionError('Expected integrity check to refuse replay')
            out['B62_midnight_leaves_unreplayable_day'] = {'error': failure, 'verify': verification, 'rebuild_error': rebuild_error}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
