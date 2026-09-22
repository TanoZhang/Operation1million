"""Offline validator/configuration audit; no provider requests or real secrets."""
from contextlib import ExitStack, closing, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from jobdisco import collection_policy as policy
from jobdisco import collector, jsearch, local_config, query_catalog
from jobdisco import validate_sources as validator


def source(provider='apple_jobs', fields=None):
    return validator.Source('fixture', 'company_direct_sources', 'fixture',
                            'Fixture', provider, 'https://example.test/jobs', fields or {})


class Session:
    def __init__(self, body='<html>Careers</html>'):
        self.headers = {}
        self.calls = 0
        self.body = body

    def get(self, *args, **kwargs):
        self.calls += 1
        return type('Response', (), {'status_code': 200,
                                    'headers': {'content-type': 'text/html'},
                                    'text': self.body})()

    post = get


def isolated(directory, body='<html>Careers</html>'):
    stack = ExitStack()
    session = Session(body)
    original = policy.SourcePolicy
    stack.enter_context(patch.object(validator, 'SourcePolicy',
        lambda item, delay: original(item, delay, path=directory / 'pause.sqlite')))
    stack.enter_context(patch.object(policy, 'request_interval', return_value=1.0))
    stack.enter_context(patch.object(validator.time, 'sleep'))
    stack.enter_context(patch.object(validator.requests, 'Session', return_value=session))
    # A missed mock must fail closed instead of allowing any real HTTP.
    stack.enter_context(patch.object(policy.requests, 'get', side_effect=AssertionError('HTTP forbidden')))
    return stack, session


def b74(directory):
    report = directory / 'report.csv'
    report.write_text('previous report\n', encoding='utf-8')
    good = source()
    bad = source('workday', {'tenant': 'fixture'})
    bad.source_id = 'missing-site'
    stack, session = isolated(directory)
    with stack, patch.object(validator, 'OUT_CSV', report), \
         patch.object(validator, 'load_sources', return_value=[good, bad, good]), \
         redirect_stdout(io.StringIO()):
        try:
            validator.main()
        except KeyError as exc:
            assert exc.args == ('site',)
        else:
            raise AssertionError('Expected request construction to escape validate')
    assert session.calls == 1
    assert report.read_text() == 'previous report\n'
    print('B74: missing Workday site aborts three-source run after one probe; no new report')


def b75(directory):
    report = directory / 'report.csv'
    report.write_text('previous report\n', encoding='utf-8')
    with patch.object(validator, 'OUT_CSV', report), \
         patch.object(validator, 'load_sources', return_value=[]), \
         patch.object(validator.requests, 'Session', return_value=Session()):
        try:
            validator.main()
        except IndexError:
            pass
        else:
            raise AssertionError('Expected empty-source report failure')
    assert report.read_bytes() == b''
    print('B75: zero enabled sources causes IndexError and truncates the previous report to zero bytes')


def b76(directory):
    plain = '<a class="job-title" href="/en-us/details/200123456/rtl-engineer">RTL Engineer</a>'
    nested = plain.replace('>RTL Engineer</a>', '><span>RTL Engineer</span></a>')
    assert len(validator.apple_items(plain)) == 1
    assert validator.apple_items(nested) == []
    assert len(collector.html_items(nested, 'https://jobs.apple.com', 'apple_jobs')[0]) == 1
    stack, session = isolated(directory, nested)
    with stack:
        result = validator.validate(source(), session)
    assert result['verdict'] == 'download_ok_needs_extractor' and result['item_count'] == 0
    print('B76: adding a span to an Apple job title changes validator count 1 -> 0; collector still reads 1')


def b77(directory):
    body = '<html><head><script src="https://cdn.example.test/akamai/metrics.js"></script></head><body>Careers and open positions</body></html>'
    stack, session = isolated(directory, body)
    with stack:
        result = validator.validate(source('google_jobs'), session)
    assert result['verdict'] == 'paused' and 'akamai' in result['evidence']
    with closing(sqlite3.connect(directory / 'pause.sqlite')) as db:
        wait = db.execute('SELECT retry_at FROM source_pauses').fetchone()[0] - policy.time.time()
    assert wait > 86390
    followup = policy.SourcePolicy(source('google_jobs'), 1, path=directory / 'pause.sqlite')
    try:
        followup.check()
    except policy.SourcePaused:
        pass
    else:
        raise AssertionError('Expected the false pause to bind the later collector')
    print('B77: nonvisible CDN path containing akamai creates a durable 24-hour source pause')


def b78(directory):
    body = '<html><h1>Human verification</h1><a class="link-inline" href="/en-us/details/200123456/rtl-engineer">RTL Engineer</a></html>'
    assert validator.html_signal(body)[0] is False
    stack, session = isolated(directory, body)
    with stack:
        result = validator.validate(source(), session)
    assert result['verdict'] == 'usable'
    with closing(sqlite3.connect(directory / 'pause.sqlite')) as db:
        assert db.execute('SELECT COUNT(*) FROM source_pauses').fetchone()[0] == 0
    print('B78: recognized Human verification text is bypassed by one parsed anchor; usable, no pause')


def b79(directory):
    config = directory / 'plan.toml'
    prefix = '[[query]]\nquery = "RTL Engineer"\npages = 1\n[filter]\n'
    config.write_text(prefix + 'exclude_title_patterns = ["senior"]\n', encoding='utf-8')
    settings, _ = jsearch.load_plan(config)
    assert not jsearch.excluded('RTL Engineer', settings['filter'])
    config.write_text(prefix + 'exclude_title_patterns = "senior"\n', encoding='utf-8')
    settings, _ = jsearch.load_plan(config)
    assert jsearch.excluded('RTL Engineer', settings['filter'])
    assert jsearch.excluded('FPGA Intern', settings['filter'])
    print('B79: scalar regex accepted by load_plan; senior becomes individual letters, rejecting RTL Engineer and FPGA Intern')


def b80(directory):
    first, second = directory / 'first.sqlite', directory / 'second.sqlite'
    for path in (first, second):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE companies (company_key TEXT, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('fixture', 'Fixture')")
    with patch.object(query_catalog, 'ROOT', directory):
        query_catalog.migrate(first)
        assert len(query_catalog.load_queries(first)) == 18
        try:
            query_catalog.migrate(second)
        except FileExistsError:
            pass
        else:
            raise AssertionError('Expected cross-database backup path collision')
    with closing(sqlite3.connect(second)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='search_queries'").fetchone()
    print('B80: migrating first.sqlite prevents migration of unrelated second.sqlite via shared backup filename')


def controls(directory):
    # Exercise every request adapter with complete fields, without transport.
    for provider, fields, method in (
        ('workday', {'tenant': 'x', 'site': 'External', 'workday_host': 'wd1'}, 'POST'),
        ('workday', {'tenant': 'x', 'site': 'External', 'workday_host': 'wd1', 'path_style': 'recruiting'}, 'POST'),
        ('oracle_cloud', {'api_domain': 'example.test', 'site': 'CX'}, 'GET'),
        ('phenom', {'career_domain': 'example.test'}, 'POST'),
        ('ashby', {}, 'GET'),
    ):
        assert validator.request_for(source(provider, fields))[1] == method
    samples = {
        'greenhouse': {'jobs': [{'title': 'RTL'}]}, 'ashby': {'jobs': [{'title': 'RTL'}]},
        'smartrecruiters': {'content': [{'title': 'RTL'}]}, 'workday': {'jobPostings': [{'title': 'RTL'}]},
        'oracle_cloud': {'items': [{'requisitionList': [{'title': 'RTL'}]}]},
        'amd_careers': {'jobs': [{'data': {'title': 'RTL'}}]},
        'eightfold': {'data': {'positions': [{'title': 'RTL'}]}},
        'phenom': {'refineSearch': {'data': {'jobs': [{'title': 'RTL'}]}}},
    }
    for provider, data in samples.items():
        assert len(validator.json_items(provider, data)) == 1
    assert len(validator.xml_items('renesas_careers', '<url><loc>https://example.test/job/rtl</loc></url>')) == 1
    assert len(validator.achronix_items('<td class="views-field-title"><a href="/job/rtl">RTL</a></td>')) == 1
    # Credentials here are synthetic. No real environment file is read.
    with patch.object(local_config, 'ROOT', directory), patch.dict(os.environ, {}, clear=True):
        local_config.load_credentials()
        (directory / '.env.local').write_text('\ufeffJSEARCH_API_KEY="fixture-only"\nUNSUPPORTED=ignored\n', encoding='utf-8')
        local_config.load_credentials()
        assert os.environ['JSEARCH_API_KEY'] == 'fixture-only' and 'UNSUPPORTED' not in os.environ
        os.environ['JSEARCH_API_KEY'] = 'environment-wins'
        local_config.load_credentials()
        assert os.environ['JSEARCH_API_KEY'] == 'environment-wins'
    print('Controls: request builders, supported JSON adapters, XML/HTML extraction, credential loading pass')


if __name__ == '__main__':
    for case in (b74, b75, b76, b77, b78, b79, b80, controls):
        with tempfile.TemporaryDirectory(prefix='jobdisco-audit14-') as temporary:
            case(Path(temporary))
