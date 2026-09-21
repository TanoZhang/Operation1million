"""Collector audit with synthetic responses and temporary durable state only."""
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import io
import json
from pathlib import Path
import runpy
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jobdisco import applications, collector, jsearch, store
from jobdisco.jsearch_access import RequestGuard
from jobdisco.validate_sources import Source

HELPER = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))
run = HELPER['run']


def response(payload=None, text='', url='https://example.test/jobs', **kwargs):
    result = HELPER['response'](payload, text, **kwargs)
    result.url, result.content = url, text.encode()
    return result


def source(provider, **fields):
    return Source(provider + ':fixture', 'company_sources', 'fixture', 'Fixture',
                  provider, 'https://example.test/jobs', fields)


def held(folder):
    with closing(store.connect(folder / 'jobs.sqlite')) as db:
        return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY url')]


def main():
    out = {'source': str(Path(collector.__file__).resolve())}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.object(store, 'ROOT', root), patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP forbidden')):
            def folder(name):
                result = root / name
                result.mkdir()
                return result

            # B50: batch preprocessing raises before the per-item boundary in add.
            target = folder('hibob')
            good = {'id': 'A', 'title': 'RTL Engineer', 'site': 'Austin', 'country': 'US'}
            bad = {'title': 'Malformed role'}
            code, reports, calls = run(target, 'pass', [source('hibob', subdomain='fixture')],
                                        [response({'jobAdDetails': [good, bad]})])
            assert code == 2 and reports[0]['direct_status'] == 'failed' and not held(target)
            out['B50_hibob_preprocessing_discards_valid_sibling'] = {'status': reports[0]['direct_status'], 'reason': reports[0]['failure_reason'], 'stored': 0}

            # B51: a sorted page can contain an unseen posting older than collection time.
            target = folder('incremental')
            old = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
            def position(ident, stamp, title='RTL Engineer'):
                return {'id': ident, 'name': title, 'positionUrl': '/job/' + ident, 'postedTs': stamp}
            board = source('eightfold')
            assert run(target, 'first', [board], [response({'data': {'count': 1, 'positions': [position('A', old)]}})])[0] == 0
            data = {'data': {'count': 2, 'positions': [position('B', old + 60), position('A', old, 'Updated RTL Engineer')]}}
            second = run(target, 'second', [board], [response(data)])
            third = run(target, 'third', [board], [response(data)])
            rows = held(target)
            assert second[0] == third[0] == 0 and len(rows) == 1 and rows[0]['title'] == 'RTL Engineer'
            out['B51_unseen_old_posting_skipped_by_since'] = {'statuses': [second[1][0]['direct_status'], third[1][0]['direct_status']], 'stored_ids': [r['source_job_id'] for r in rows], 'unseen_id': 'B', 'stored_title': rows[0]['title']}

            # B52: the first page ETag cannot validate later pages.
            target = folder('page_etag')
            board = replace(source('smartrecruiters', company_slug='fixture'), access_url='https://example.test/jobs?offset=0&limit=100')
            def smart(ident):
                return {'id': ident, 'name': 'RTL Engineer', 'applyUrl': 'https://example.test/job/' + ident}
            assert run(target, 'first', [board], [response({'totalFound': 2, 'content': [smart('A')]}, etag='"page-one"'), response({'totalFound': 2, 'content': [smart('B')]})])[0] == 0
            result = run(target, 'second', [board], [response(status=304), response({'totalFound': 2, 'content': [smart('C')]})])
            ids = [r['source_job_id'] for r in held(target)]
            assert result[0] == 0 and result[2] == 1 and ids == ['A', 'B']
            out['B52_page_etag_certifies_entire_board'] = {'status': result[1][0]['direct_status'], 'requests': result[2], 'stored_ids': ids, 'unread_later_page_id': 'C'}

            # B53: generated URLs make missing requisitions look like valid jobs.
            target = folder('oracle')
            board = source('oracle_cloud', api_domain='example.test', site='CX')
            original = [{'Id': str(i), 'Title': 'RTL Engineer'} for i in range(1, 6)]
            def oracle(items):
                return response({'items': [{'TotalJobsCount': len(items), 'requisitionList': items}]})
            assert run(target, 'first', [board], [oracle(original)])[0] == 0
            result = run(target, 'second', [board], [oracle(original[:4] + [{'Title': 'RTL Engineer'}])])
            rows = held(target)
            bogus = [r for r in rows if r['url'].endswith('/job/None')]
            closed = [r['source_job_id'] for r in rows if r['closed_at']]
            assert result[0] == 0 and bogus and closed == ['5']
            out['B53_missing_id_generates_placeholder_url'] = {'status': result[1][0]['direct_status'], 'placeholder': bogus[0]['url'], 'closed_real_ids': closed}

            # B54: no accepted rows is not evidence that pagination repeated.
            target = folder('malformed_page')
            board = source('workday', tenant='fixture', site='External', workday_host='wd1')
            pages = [response({'total': 2, 'jobPostings': [{'externalPath': '/job/BAD'}]}),
                     response({'total': 2, 'jobPostings': [{'title': 'RTL Engineer', 'externalPath': '/job/GOOD'}]})]
            result = run(target, 'pass', [board], pages)
            assert result[2] == 1 and not held(target) and result[1][0]['direct_status'] == 'partial'
            out['B54_malformed_page_misidentified_as_repeat'] = {'requests': result[2], 'status': result[1][0]['direct_status'], 'reason': result[1][0]['failure_reason'], 'unread_valid_pages': 1}

            # B55: no-store creates the missing job index before checking the flag.
            target = folder('no_store')
            path = target / 'jobs.sqlite'
            guard = RequestGuard(path=target / 'usage.sqlite')
            argv = ['collector', '--db', str(path), '--output', str(target / 'pass'), '--no-store']
            with patch.object(store, 'LOG', target / 'history'), patch.object(collector, 'load_sources', return_value=[]), patch.object(collector, 'load_credentials'), patch.object(collector, 'RequestGuard', return_value=guard), patch('sys.argv', argv), redirect_stdout(io.StringIO()):
                assert collector.main() == 0
            assert path.exists()
            with closing(sqlite3.connect(path)) as db:
                companies = db.execute('SELECT COUNT(*) FROM companies').fetchone()[0]
            out['B55_no_store_creates_database'] = {'index_created': path.exists(), 'catalog_companies': companies}

            # B56: a partial structured list suppresses the full HTML inventory.
            target = folder('mixed_html')
            board = source('achronix_careers')
            def html(ids, structured=False):
                links = ''.join(f'<a href="/job/{i}"><h2>RTL Engineer</h2></a>' for i in ids)
                meta = '<script type="application/ld+json">' + json.dumps([{'@type': 'JobPosting', 'title': 'RTL Engineer', 'url': f'https://example.test/job/{i}'} for i in range(1, 5)]) + '</script>' if structured else ''
                return response(text=meta + links)
            assert run(target, 'first', [board], [html(range(1, 6))])[0] == 0
            result = run(target, 'second', [board], [html(range(1, 6), structured=True)])
            rows = held(target)
            assert result[0] == 0 and int(result[1][0]['jobs']) == 4 and sum(bool(r['closed_at']) for r in rows) == 1
            out['B56_jsonld_suppresses_html_inventory'] = {'advertised': 5, 'extracted': 4, 'status_after_store_fuse': result[1][0]['direct_status'], 'closed': sum(bool(r['closed_at']) for r in rows)}

            # B57: an already downloaded detail page loses all non-title evidence.
            target = folder('sitemap_description')
            board = source('akeana_careers')
            sitemap = '<urlset><url><loc>https://example.test/job/A</loc></url></urlset>'
            detail = '<html><h1>RTL Engineer</h1><section>5 years of experience required.</section></html>'
            result = run(target, 'pass', [board], [response(text=sitemap), response(text=detail, url='https://example.test/job/A')])
            rows = held(target)
            pending = applications.queue(target / 'jobs.sqlite', target / 'applications.ndjson')['pending']
            assert result[0] == 0 and '5 years' not in rows[0]['raw'] and len(pending) == 1
            out['B57_sitemap_fallback_discards_description'] = {'status': result[1][0]['direct_status'], 'retained_raw': json.loads(rows[0]['raw']), 'pending': len(pending)}

            # Existing B45 is only fixed on paid intake; report as a follow-up, not new.
            target = folder('direct_empty_title')
            good = {'id': 'A', 'title': 'RTL Engineer', 'absolute_url': 'https://example.test/A'}
            bad = {'id': 'B', 'title': '   ', 'absolute_url': 'https://example.test/B'}
            try:
                run(target, 'pass', [source('greenhouse')], [response({'jobs': [good, bad]})])
            except sqlite3.IntegrityError as exc:
                assert not held(target)
                out['B45_remaining_direct_path'] = {'exception': str(exc), 'stored': 0}
            else:
                raise AssertionError('Expected unfixed direct normalization boundary')

            # Positive controls cover all nine JSON normalization branches.
            cases = [
                ('workday', {}, {'title': 'RTL Engineer', 'externalPath': '/job/RTL_A'}),
                ('greenhouse', {}, {'title': 'RTL Engineer', 'id': 'A', 'absolute_url': 'https://example.test/A'}),
                ('ashby', {}, {'title': 'RTL Engineer', 'id': 'A', 'jobUrl': 'https://example.test/A'}),
                ('oracle_cloud', {}, {'Title': 'RTL Engineer', 'Id': 'A'}),
                ('smartrecruiters', {'company_slug': 'fixture'}, {'name': 'RTL Engineer', 'id': 'A'}),
                ('phenom', {'career_domain': 'example.test'}, {'title': 'RTL Engineer', 'id': 'A'}),
                ('amazon_jobs', {}, {'title': 'RTL Engineer', 'id_icims': 'A', 'job_path': '/en/jobs/A'}),
                ('eightfold', {}, position('A', old)),
                ('amd_careers', {}, {'title': 'RTL Engineer', 'req_id': 'A'}),
            ]
            for provider, fields, payload in cases:
                row = collector.normalize(source(provider, **fields), payload)
                assert row['title'] == 'RTL Engineer' and row['source_job_id'] == 'A', provider
            links = {
                'achronix_careers': '/job/A', 'apple_jobs': '/en-us/details/123/rtl',
                'jobs2web': '/job/location/rtl/123', 'talentbrew': '/job/location/123/456',
                'avature': '/JobDetail/rtl/123', 'google_jobs': 'jobs/results/123-rtl',
                'jobvite': '/job/A', 'tsmc_careers': '/JobDetail/rtl/123',
                'hibob': '/jobs/A', 'uplers_company_profile': '/talent/all-opportunities/HR123',
            }
            for provider, href in links.items():
                items, _ = collector.html_items(f'<li><a href="{href}"><h2>RTL Engineer</h2></a></li>', 'https://example.test/', provider)
                assert len(items) == 1 and items[0]['title'] == 'RTL Engineer', provider
            out['positive_controls'] = {'json_normalization_branches': len(cases), 'html_link_extractors': len(links)}
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
