"""Offline contracts for pagination, attribution, and SQL rebuilds."""
import argparse
import io
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch, Mock
from jobdisco import collector
from jobdisco.collector import (Collector, Source, ROOT, employer_matches,
                                html_items, fallback, config, normalize,
                                reported_total, source_lock)
from jobdisco.paths import CONFIG
from jobdisco import store
from dataclasses import replace

class Response:
    def __init__(self, data): self.data = data
    def json(self): return self.data

class LedgerBeforeIndexTests(unittest.TestCase):
    """A source that could not be logged must not be left in the index.

    The log is the record and SQLite is derived from it. A pass that wrote rows
    to the index and then failed to append them left postings a rebuild cannot
    restore, with that source's watermark advanced past them so the next pass
    would not look again -- and with a manifest rewritten on the way out, so
    the integrity check still called the day sound.
    """

    class FakeCollector:
        rows = [dict(company_key='sample', company_name='Sample Inc.', provider_key='workday',
                     title='RTL Engineer', location='Austin', url='https://sample.test/job/1',
                     source_job_id='R-1', posted_at=None, raw={'description': 'Design hardware.'})]

        def __init__(self, source, args):
            self.source, self.args = source, args
            self.session = SimpleNamespace(close=lambda: None, headers={})
            self.jobs = [dict(row) for row in self.rows]
            self.rejected, self.requests = [], 1
            self.strategy, self.watermark = 'full', None
            self.known, self.listed = set(), None
            self.etag = self.last_modified = None

        def run(self):
            return 'complete', ''

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        log = patch.object(store, 'LOG', self.root / 'store')
        log.start()
        self.addCleanup(log.stop)
        self.db_path = self.root / 'jobs.sqlite'
        with sqlite3.connect(self.db_path) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('sample', 'Sample Inc.')")
        store.migrate(self.db_path)
        self.source = Source('test', 'company_sources', 'sample', 'Sample Inc.', 'workday',
                             'https://sample.test/External', {})

    def run_pass(self):
        arguments = ['collector', '--db', str(self.db_path),
                     '--output', str(self.root / 'run'), '--workers', '1']
        with patch.object(collector, 'load_sources', return_value=[self.source]), \
             patch.object(collector, 'Collector', self.FakeCollector), \
             patch.object(collector, 'RequestGuard', return_value=Mock(attempts=0)), \
             patch('sys.argv', arguments), patch('sys.stdout', new_callable=io.StringIO):
            return collector.main()

    def held(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            jobs = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            state = db.execute('SELECT COUNT(*) FROM source_state '
                               'WHERE last_success_at IS NOT NULL').fetchone()[0]
        return jobs, state

    def test_a_pass_that_could_not_log_a_source_does_not_keep_it(self):
        with patch.object(store, 'append_log', side_effect=OSError('no space left on device')):
            with self.assertRaises(OSError):
                self.run_pass()
        self.assertEqual(self.held(), (0, 0))
        # And the same pass, with the log writable, does store it.
        self.assertEqual(self.run_pass(), 0)
        self.assertEqual(self.held(), (1, 1))
        self.assertEqual([state for _, state in store.verify()], ['ok'])


class EffectiveProviderTests(unittest.TestCase):
    """What a pass stores under is what it must close under.

    A TI board is a shell that names the Oracle endpoint its postings actually
    live on, and the collector rewrites itself to that provider, so its rows are
    stored as `oracle_cloud`. The pass was still reported and persisted under
    the provider the catalog names, and closing is scoped by company and
    provider -- so it compared the board against an inventory holding nothing,
    and a board that went from five postings to four kept all five open.
    """

    class ShellRewritingCollector:
        """Stands in for the real one: same rewrite, no HTTP."""

        listings = []

        def __init__(self, source, args):
            self.source = replace(source, provider_key='oracle_cloud')
            self.args = args
            self.session = SimpleNamespace(close=lambda: None, headers={})
            self.rejected, self.requests = [], 1
            self.strategy, self.watermark = 'full', None
            self.known, self.listed = set(), None
            self.etag = self.last_modified = None
            self.jobs = [dict(
                company_key=self.source.company_key, company_name=self.source.company_name,
                provider_key=self.source.provider_key, title='RTL Engineer',
                location='Dallas', url=url, source_job_id=url.rsplit('/', 1)[-1],
                posted_at=None, raw={'description': 'Design hardware.'})
                for url in self.listings]

        def run(self):
            return 'complete', ''

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        log = patch.object(store, 'LOG', self.root / 'store')
        log.start()
        self.addCleanup(log.stop)
        self.db_path = self.root / 'jobs.sqlite'
        with sqlite3.connect(self.db_path) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('ti', 'Texas Instruments')")
        store.migrate(self.db_path)
        self.source = Source('ti:1', 'company_sources', 'ti', 'Texas Instruments', 'ti_careers',
                             'https://careers.ti.com/', {})

    def pass_listing(self, urls, run):
        self.ShellRewritingCollector.listings = urls
        arguments = ['collector', '--db', str(self.db_path),
                     '--output', str(self.root / run), '--workers', '1']
        with patch.object(collector, 'load_sources', return_value=[self.source]), \
             patch.object(collector, 'Collector', self.ShellRewritingCollector), \
             patch.object(collector, 'RequestGuard', return_value=Mock(attempts=0)), \
             patch('sys.argv', arguments), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(collector.main(), 0)
        with closing(sqlite3.connect(self.db_path)) as db:
            return db.execute(
                'SELECT COUNT(*) FROM jobs WHERE closed_at IS NULL').fetchone()[0]

    def test_a_board_that_lost_a_posting_closes_it(self):
        listed = [f'https://careers.ti.com/job/{n}' for n in range(5)]
        self.assertEqual(self.pass_listing(listed, 'first'), 5)
        self.assertEqual(self.pass_listing(listed[:4], 'second'), 4)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        robots = patch('jobdisco.collection_policy.robots_delay', return_value=None)
        robots.start()
        self.addCleanup(robots.stop)

    def source(self):
        return Source('test', 'company_sources', 'sample', 'Sample Inc.', 'workday', 'https://sample.wd1.myworkdayjobs.com/External', {'tenant':'sample','site':'External','workday_host':'wd1'})
    def args(self):
        return argparse.Namespace(max_jobs=100,max_pages=10,delay=0,timeout=1,jsearch_timeout=1,fallback_queries=1)
    def test_pagination_and_relative_dates(self):
        c = Collector(self.source(),self.args()); offsets=[]
        def fetch(url,method,payload):
            n=payload['offset'];offsets.append(n)
            return Response({'total':2,'jobPostings':[{'title':'Engineer','externalPath':f'/job/Engineer_R{n}','bulletFields':['Posted Today',f'R{n}']}]})
        c.fetch=fetch
        self.assertEqual(c.run(),('complete',''));self.assertEqual(offsets,[0,1])
        self.assertEqual([r['source_job_id'] for r in c.jobs],['R0','R1'])
        self.assertIsNone(c.jobs[0]['posted_at']);self.assertIn('/External/job/',c.jobs[0]['url'])
    def test_repeated_page(self):
        c=Collector(self.source(),self.args())
        c.fetch=lambda *a:Response({'total':10,'jobPostings':[{'title':'Engineer','externalPath':'/job/Engineer_R1'}]})
        self.assertEqual(c.run()[0],'partial');self.assertEqual(len(c.jobs),1)
    def test_malformed_record_does_not_drop_later_jobs(self):
        c=Collector(self.source(),self.args())
        c.add([{'externalPath':'/job/broken'},{'title':'Good','externalPath':'/job/Good_R2'}])
        self.assertEqual(len(c.jobs),1);self.assertEqual(len(c.rejected),1)
    def test_a_null_field_rejects_one_record_not_the_board(self):
        """Not every malformed record is malformed in the same way.

        A provider that sends null where it has always sent a string raises
        AttributeError here, not ValueError, and that used to end the source
        along with every later page of good postings.
        """
        c=Collector(self.source(),self.args())
        c.add([{'title':'Broken','externalPath':None},{'title':'Good','externalPath':'/job/Good_R2'}])
        self.assertEqual([r['title'] for r in c.jobs],['Good'])
        self.assertEqual(len(c.rejected),1)
        self.assertIn('AttributeError',c.rejected[0]['reason'])

    def test_the_job_cap_is_never_a_complete_board(self):
        """A pass that ran out of room did not watch the board end.

        The store retires whatever a complete pass did not list, so a capped
        pass reporting 'complete' withdraws the postings it had no room for.
        """
        args=self.args();args.max_jobs=2
        c=Collector(self.source(),args)
        c.fetch=lambda *a:Response({'total':3,'jobPostings':[
            {'title':'Engineer','externalPath':f'/job/Engineer_R{n}'} for n in range(3)]})
        status,reason=c.run()
        self.assertEqual(status,'partial');self.assertIn('cap',reason)
        self.assertEqual(len(c.jobs),2);self.assertTrue(c.capped)

    def test_an_empty_page_does_not_outrank_the_stated_total(self):
        c=Collector(self.source(),self.args())
        pages=[Response({'total':500,'jobPostings':[{'title':'Engineer','externalPath':'/job/Engineer_R1'}]}),
               Response({'total':500,'jobPostings':[]})]
        c.fetch=lambda *a:pages.pop(0)
        status,reason=c.run()
        self.assertEqual(status,'partial');self.assertIn('500',reason)
        self.assertEqual(len(c.jobs),1)

    def test_an_empty_page_still_ends_a_board_that_states_no_total(self):
        c=Collector(self.source(),self.args())
        pages=[Response({'jobPostings':[{'title':'Engineer','externalPath':'/job/Engineer_R1'}]}),
               Response({'jobPostings':[]})]
        c.fetch=lambda *a:pages.pop(0)
        self.assertEqual(c.run(),('complete',''));self.assertEqual(len(c.jobs),1)

    def test_a_stated_zero_is_a_count_not_a_silence(self):
        """An empty board that says so is closable; one that says nothing is not."""
        self.assertEqual(reported_total('workday',{'total':0}),0)
        self.assertEqual(reported_total('amd_careers',{'totalCount':0}),0)
        self.assertIsNone(reported_total('workday',{}))
        c=Collector(self.source(),self.args())
        c.fetch=lambda *a:Response({'total':0,'jobPostings':[]})
        self.assertEqual(c.run(),('complete',''))
        silent=Collector(self.source(),self.args())
        silent.fetch=lambda *a:Response({'jobPostings':[]})
        self.assertEqual(silent.run()[0],'partial')

    def test_a_position_without_a_link_is_malformed_not_a_duplicate(self):
        """Two requisitions became one URL: the board's own address.

        `urljoin(access_url, '')` is the board, so every position missing its
        positionUrl resolved to the same page, all but the first were dropped as
        duplicates, and the pass called itself complete.
        """
        source=replace(self.source(),provider_key='eightfold',
                       access_url='https://careers.test/api/pcsx/search?domain=x.com')
        with self.assertRaises(ValueError):
            normalize(source,{'id':'1','name':'RTL Engineer'})
        c=Collector(source,self.args())
        c.fetch=lambda *a:Response({'data':{'count':2,'positions':[
            {'id':'1','name':'RTL Engineer'},{'id':'2','name':'DV Engineer'}]}})
        c.run()
        # Two rejected records, not one kept and one silently deduplicated
        # against it. `main` is what turns a pass holding rejects into a
        # partial one; what matters here is that neither posting was merged
        # into the other.
        self.assertEqual(c.jobs,[]);self.assertEqual(len(c.rejected),2)

    def test_the_ti_shell_does_not_supply_the_boards_validator(self):
        """The shell is not the board, and its ETag does not describe the jobs.

        Stored as this source's validator, a 304 from the wrapper ended the
        pass before the jobs API was asked at all, hiding every arrival and
        change behind it. The shell's ETag is discarded and this source keeps
        no validator, so it is read in full each time.
        """
        source=Source('ti:1','company_sources','ti','Texas Instruments','ti_careers',
                      'https://careers.ti.com/',{})
        c=Collector(source,argparse.Namespace(max_jobs=100,max_pages=2,delay=0,timeout=1,
                                              retries=0,jsearch_timeout=1,fallback_queries=1))
        shell=Mock(status_code=200,headers={'content-type':'text/html','ETag':'W/"shell"'},
                   text='<base data-apibaseurl="https://ti.example/api" data-sitenumber="CX_1">')
        page=Mock(status_code=200,headers={'content-type':'application/json','ETag':'W/"api"'},text='')
        page.json.return_value={'items':[{'TotalJobsCount':1,'requisitionList':[
            {'Id':'1','Title':'RTL Engineer'}]}]}
        c.session.request=Mock(side_effect=[shell,page])
        self.addCleanup(c.session.close)
        with patch('jobdisco.collector.time.sleep'):
            self.assertEqual(c.run(),('complete',''))
        self.assertEqual(len(c.jobs),1)
        self.assertIsNone(c.etag);self.assertIsNone(c.last_modified)

    def test_employer_filter(self):
        self.assertTrue(employer_matches('Advanced Micro Devices, Inc.',['Advanced Micro Devices']))
        self.assertTrue(employer_matches('AMD',['AMD']))
        for name in ['AMD Staffing','Not AMD','AMDocs','','Microsoft Partner']:
            self.assertFalse(employer_matches(name,['AMD','Microsoft']))
    def test_apple_auxiliary_links(self):
        html='<a href="/en-us/details/123/engineer">Engineer</a><a href="/en-us/details/123/engineer">See full role description</a><a href="/en-us/details/123/engineer/locationPicker">Locations</a>'
        items,_=html_items(html,'https://jobs.apple.com','apple_jobs')
        self.assertEqual(len(items),1);self.assertEqual(items[0]['title'],'Engineer')
    def test_schema_rebuild(self):
        con=sqlite3.connect(':memory:');sql=(CONFIG/'schema.sql').read_text(encoding='utf-8')
        con.executescript(sql);con.executescript(sql)
        keys={r[0] for r in con.execute('select company_key from companies')}
        self.assertEqual(len(keys),35)
        self.assertFalse(keys & {
            'ampere_computing', 'bytedance', 'mediatek', 'meta', 'tesla',
            'advantest', 'maxlinear', 'omnivision', 'infineon', 'achronix',
            'nexperia', 'nokia', 'semtech', 'onsemi', 'akeana',
            'microchip_technology', 'psiquantum', 'analog_devices', 'celestica',
            'tsmc', 'rambus', 'ventana_micro',
        })
        self.assertEqual(con.execute('pragma foreign_key_check').fetchall(),[])
        self.assertEqual(con.execute("select provider_key from company_sources where company_key='amd'").fetchone()[0], 'amd_careers')
    def test_oracle_jobs_subdomain_is_preserved(self):
        source=replace(self.source(),provider_key='oracle_cloud',access_url='https://jobs.nokia.com/en/sites/CX_1/jobs?mode=location')
        row=normalize(source,{'Id':123,'Title':'Engineer'})
        self.assertEqual(row['url'],'https://jobs.nokia.com/en/sites/CX_1/job/123')
    def test_amazon_url_uses_job_path(self):
        row=normalize(replace(self.source(),provider_key='amazon_jobs'),{'id':'uuid','id_icims':'123','title':'Engineer','job_path':'/en/jobs/123/engineer'})
        self.assertEqual(row['url'],'https://www.amazon.jobs/en/jobs/123/engineer')
        self.assertEqual(row['source_job_id'],'123')
    def test_empty_terminal_page(self):
        c=Collector(replace(self.source(),provider_key='apple_jobs'),self.args())
        c.jobs=[{'title':'Existing job'}]
        c.fetch=lambda *a:type('HTMLResponse',(),{'text':'<p>There are no results that match your search.</p>','url':'https://jobs.apple.com/en-us/search?page=226'})()
        self.assertEqual(c.run(),('complete',''))
    def test_missing_key_no_network(self):
        with patch.dict('os.environ',{},clear=True),patch('requests.Session.get') as get:
            rows,status,_=fallback(self.source(),['Sample'],self.args(),[30],config('sources_search.toml')['search']['jsearch'])
            self.assertEqual((rows,status),([],'missing_credentials'));get.assert_not_called()

    def test_jsearch_v2_nested_jobs_and_employer_filter(self):
        args = self.args()
        args.jsearch_guard = Mock()
        response = Mock(status_code=200)
        job = {'job_id': '123', 'job_title': 'Hardware Engineer', 'employer_name': 'Sample', 'job_apply_link': 'https://example.com/job/123'}
        response.json.return_value = {'status': 'OK', 'data': {'jobs': [job, dict(job, job_id='456', employer_name='Sample Staffing')], 'cursor': 'next-page'}}
        args.jsearch_guard.get.return_value = response
        with patch.dict('os.environ', {'JSEARCH_API_KEY': 'test-placeholder'}):
            rows, status, reason = fallback(self.source(), ['Sample'], args, [1], config('sources_search.toml')['search']['jsearch'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source_job_id'], '123')
        self.assertEqual(status, 'query_limited')
        self.assertIn('1 employer mismatches', reason)
        call = args.jsearch_guard.get.call_args
        self.assertIn('num_pages=1', call.args[1])
        self.assertIn('query=Sample&', call.args[1])  # employer name, not a role keyword
        self.assertEqual(call.kwargs['headers'], {'X-API-Key': 'test-placeholder'})

    def test_microsoft_lock_does_not_block_other_sources(self):
        microsoft = replace(self.source(), company_key='microsoft')
        another_microsoft = replace(self.source(), source_id='microsoft:second',
                                    company_key='microsoft')
        other = replace(self.source(), source_id='other', company_key='other')
        first_entered = threading.Event()
        second_entered = threading.Event()
        other_finished = threading.Event()
        release = threading.Event()

        def first():
            with source_lock(microsoft):
                first_entered.set()
                release.wait(2)

        def second():
            first_entered.wait(2)
            with source_lock(another_microsoft):
                second_entered.set()

        def independent():
            first_entered.wait(2)
            with source_lock(other):
                other_finished.set()

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(first), pool.submit(second), pool.submit(independent)]
            self.assertTrue(first_entered.wait(1))
            self.assertTrue(other_finished.wait(1))
            self.assertFalse(second_entered.is_set())
            release.set()
            for future in futures:
                future.result(timeout=2)
        self.assertTrue(second_entered.is_set())

if __name__=='__main__':unittest.main()
