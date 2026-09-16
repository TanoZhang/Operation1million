"""Offline contracts for pagination, attribution, and SQL rebuilds."""
import argparse
import sqlite3
import unittest
from unittest.mock import patch, Mock
from jobdisco.collector import Collector, Source, ROOT, employer_matches, html_items, fallback, config, normalize
from jobdisco.paths import CONFIG
from dataclasses import replace

class Response:
    def __init__(self, data): self.data = data
    def json(self): return self.data

class CollectionTests(unittest.TestCase):
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
        self.assertEqual(len(keys),37)
        self.assertFalse(keys & {
            'ampere_computing', 'bytedance', 'mediatek', 'meta', 'tesla',
            'advantest', 'maxlinear', 'omnivision', 'infineon', 'achronix',
            'nexperia', 'nokia', 'semtech', 'onsemi', 'akeana',
            'microchip_technology', 'psiquantum', 'analog_devices', 'celestica',
            'tsmc',
        })
        self.assertEqual(con.execute('pragma foreign_key_check').fetchall(),[])
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

if __name__=='__main__':unittest.main()
