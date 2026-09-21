"""Offline JSearch function audit. Provider responses are synthetic; no paid calls."""
from contextlib import closing
import copy
import json
from pathlib import Path
import re
import runpy
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from jobdisco import applications, collector, jsearch, store
from jobdisco.jsearch_access import RequestGuard


def item(**changes):
    return dict(dict(job_id='A', job_title='RTL Engineer', employer_name='Fixture',
                     job_apply_link='https://example.test/A',
                     job_description='Design RTL hardware.'), **changes)


def main():
    settings, queries = jsearch.load_plan()
    rules = settings['filter']
    query = jsearch.Query('RTL', 3, 'A')
    out = {'source': str(Path(jsearch.__file__).resolve())}
    run = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))['run']
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP forbidden')):
        root = Path(directory)
        with patch.object(store, 'ROOT', root):
            # B44: actual configured query text changes the same posting's eligibility.
            outcomes = {}
            for text in ('RTL', 'RTL Intern', 'RTL New Grad'):
                row = jsearch.normalize_job(item(job_description='5 years of experience required.'),
                                            jsearch.Query(text, 1, 'A'), {})
                outcomes[text] = jsearch.rejection_reason(row, rules)
            assert outcomes == {'RTL': 'required_experience_over_2_years', 'RTL Intern': '', 'RTL New Grad': ''}
            evidence = {}
            for text in ('RF', 'RF FPGA RTL ASIC'):
                row = jsearch.normalize_job(item(job_title='RF Engineer', job_description='Maintain radio antennas.'),
                                            jsearch.Query(text, 1, 'A'), {})
                evidence[text] = [jsearch.relevance(row, rules)[0], jsearch.rejection_reason(row, rules)]
            assert evidence['RF'][1] == 'no_evidence' and evidence['RF FPGA RTL ASIC'][1] == ''
            out['B44_query_metadata_changes_eligibility'] = {'experience': outcomes, 'evidence': evidence}
            original_main = collector.main
            def intern_main():
                sys.argv[sys.argv.index('--jsearch-query') + 1] = 'RTL Intern'
                return original_main()
            folder = root / 'query_metadata'
            folder.mkdir()
            with patch.object(collector, 'main', side_effect=intern_main):
                assert run(folder, 'pass', [], paid=[item(job_description='5 years of experience required.')])[0] == 0
            pending = applications.queue(folder / 'jobs.sqlite', folder / 'applications.ndjson')['pending']
            assert len(pending) == 1
            out['B44_query_metadata_changes_eligibility']['pending_after_main'] = len(pending)

            # B45: post-normalization contracts are not checked at the item boundary.
            failures = {}
            for name, bad in (('empty_title', item(job_id='B', job_apply_link='https://example.test/B', job_title='   ')),
                              ('object_date', item(job_id='B', job_apply_link='https://example.test/B',
                                                   job_posted_at_datetime_utc={'date': '2026-09-20'}))):
                folder = root / name
                folder.mkdir()
                try:
                    result = run(folder, 'pass', [], paid=[item(), bad])
                    failures[name] = {'returned': result[0]}
                except Exception as exc:
                    failures[name] = {'exception': type(exc).__name__, 'message': str(exc)}
                with closing(sqlite3.connect(folder / 'jobs.sqlite')) as db:
                    failures[name]['stored_jobs'] = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            assert failures['object_date'].get('exception') == 'ProgrammingError'
            assert failures['empty_title'].get('exception') == 'IntegrityError'
            assert all(f['stored_jobs'] == 0 for f in failures.values())
            out['B45_unvalidated_normalized_fields'] = failures

            # B46: each regex is legal under the loader's contract, but joining changes it.
            patterns = [r'(director)', r'(senior)\s+\1']
            title = 'senior senior RTL Engineer'
            separate = any(re.search(p, title, re.I) for p in patterns)
            combined = jsearch.excluded(title, {'exclude_title_patterns': patterns})
            assert separate and not combined
            duplicate_names = [r'(?P<level>senior)', r'(?P<level>principal)']
            for p in duplicate_names:
                re.compile(p, re.I)
            try:
                jsearch.any_of(duplicate_names)
            except re.error as exc:
                error = str(exc)
            else:
                raise AssertionError('Expected invalid combined expression')
            out['B46_regex_alternation_changes_contract'] = {'separate': separate, 'combined': combined, 'named_group_error': error}
            config = copy.deepcopy(settings)
            config['filter']['exclude_title_patterns'] = duplicate_names
            with patch.object(jsearch.tomllib, 'load', return_value=config):
                loaded = jsearch.load_plan()
            folder = root / 'regex'
            folder.mkdir()
            with patch.object(jsearch, 'load_plan', return_value=loaded):
                try:
                    run(folder, 'pass', [], paid=[item()])
                except re.error:
                    pass
                else:
                    raise AssertionError('Expected paid intake to fail compiling the combined pattern')
            with closing(sqlite3.connect(folder / 'usage.sqlite')) as db:
                credits = db.execute('SELECT SUM(credits) FROM credit_events').fetchone()[0]
            assert credits == 1
            out['B46_regex_alternation_changes_contract']['reserved_before_exception'] = credits

            # B47: even an entirely malformed short page permanently settles a sweep.
            guard = RequestGuard(path=root / 'cursor.sqlite')
            client = Mock(guard=guard)
            client.fetch_page.return_value = ([{'job_id': 'lost'}], True)
            persisted = []
            _, stats = jsearch.collect([query], client, settings, {},
                                       lambda q, rows, detail: persisted.extend(rows), backfill=True)
            cursor = guard.resume_page(query.key + ':' + jsearch.search_space(settings))
            client.fetch_page.reset_mock()
            client.fetch_page.return_value = ([item(job_id='lost')], True)
            _, retry = jsearch.collect([query], client, settings, {}, lambda *args: None, backfill=True)
            assert cursor == (2, True) and client.fetch_page.call_count == 0
            assert stats['jsearch_jobs_malformed'] == 1 and not persisted
            out['B47_malformed_page_settles_cursor'] = {'cursor': cursor, 'malformed': 1, 'retry_requests': 0}

            # B48: a usable secondary public URL is ignored behind a bad primary one.
            links = {}
            for primary in ('javascript:void(0)', ' ', 'https://', None):
                payload = item(job_apply_link=primary, job_google_link='https://example.test/public/A')
                try:
                    links[str(primary)] = jsearch.normalize_job(payload, query, {})['url']
                except ValueError as exc:
                    links[str(primary)] = type(exc).__name__
            assert links['None'] == 'https://example.test/public/A'
            assert links['javascript:void(0)'] == links[' '] == 'ValueError'
            assert links['https://'] == 'https://'
            out['B48_valid_secondary_link_discarded'] = links
            link_client = Mock(guard=Mock(credits=0))
            link_client.fetch_page.return_value = ([item(job_apply_link=' ', job_google_link='https://example.test/public/A')], True)
            rows, stats = jsearch.collect([query], link_client, settings, {}, lambda *args: None)
            assert not rows and stats['jsearch_jobs_malformed'] == 1
            out['B48_valid_secondary_link_discarded']['collect_malformed'] = 1

            # B49: JSON object order must not extend a preference into a sibling field.
            base = item(job_description='5 years of experience.')
            variants = [dict(preferred_qualifications='FPGA familiarity', **base),
                        dict(base, preferred_qualifications='FPGA familiarity')]
            decisions = []
            pending_counts = []
            for index, payload in enumerate(variants):
                row = jsearch.normalize_job(payload, query, {})
                decisions.append(jsearch.rejection_reason(row, rules))
                folder = root / f'field_order_{index}'
                folder.mkdir()
                assert run(folder, 'pass', [], paid=[payload])[0] == 0
                pending_counts.append(len(applications.queue(folder / 'jobs.sqlite', folder / 'applications.ndjson')['pending']))
            assert decisions == ['', 'required_experience_over_2_years'] and pending_counts == [1, 0]
            out['B49_sibling_field_order_changes_requirement'] = {'decisions': decisions, 'pending': pending_counts}

            # Controls across identity, configuration, paging, tiering and cursor namespaces.
            assert len({q.key for q in queries}) == len(queries)
            assert jsearch.Query('RTL', 1, 'A').key == query.key
            assert jsearch.Query('RTL', 1, 'A', 'different').key != query.key
            assert jsearch.page_identity([item(), item(job_id='B')]) == {'A', 'B'}
            assert jsearch.page_identity([item(job_id=[])]) is None
            assert jsearch.page_identity([item(), item()]) is None
            assert jsearch.search_space(settings) != jsearch.search_space(dict(settings, date_posted='month'))
            assert jsearch.filter_fingerprint({'a': 1, 'b': 2}) == jsearch.filter_fingerprint({'b': 2, 'a': 1})
            assert sorted(('A', 'company', 'new_grad', 'intern', 'early_career'), key=jsearch.tier_rank) == list(jsearch.TIER_ORDER)
            out['controls'] = 'Nine identity, configuration, ordering and fingerprint assertions passed'
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
