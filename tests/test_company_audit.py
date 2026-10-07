import unittest,json,sqlite3,tempfile
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock
from operation1million import applications as a, resume_fit as f, job_details as d
from operation1million.collector import employer_normalize
from operation1million.queue_snapshot import QueueSnapshot

def profile():
 return {'version':1,'families':[
  {'id':'digital','evidence':'Synthetic RTL project','all':[r'\bRTL\b',r'design|verif']}],
  'gaps':[{'id':'network','evidence':'No network practice','scope':'requirements',
           'all':[r'hands.on',r'EtherCAT']}]}


def job(url,company,title,place='',provider='jsearch'):
 return {'url':url,'company':company,'title':title,'location':place,'provider_key':provider}


def group(key,*jobs):
 return key,{'id':key,'company':jobs[0]['company'],'title':jobs[0]['title'],
  'confidence':50,'bucket':0,'flagged':False,'internship_experience':False,'jobs':list(jobs)}


def undecided(_job):
 return None

class CompanyAuditTests(unittest.TestCase):
 def test_company_alias_identity(self):
  names=['Marvell','Marvell Technology, Inc.','31 MSI - (Marvell Semi','31 MSI - (Marvell Semiconductor Inc.) US']
  self.assertEqual(len({a.employer_name(n) for n in names}),1)
  self.assertEqual(len({employer_normalize(n) for n in names}),1)
  self.assertNotEqual(a.employer_name('Marvell Services Staffing'),a.employer_name('Marvell'))

 def assess(self,raw):return f.assess({'title':'Engineer','raw':raw},profile())

 def test_b01_inline_heading_keeps_required_content(self):
  self.assertEqual(self.assess({'description':'Design and verify RTL.\nRequired qualifications: Hands-on EtherCAT.'})['verdict'],'reject')
  self.assertEqual(self.assess({'description':'Responsibilities: Design and verify RTL.'})['verdict'],'keep')

 def test_b02_preferred_inside_qualification_field_is_optional(self):
  self.assertEqual(self.assess({'description':'Design and verify RTL.',
    'qualifications':'Required qualifications\nEngineering degree\nPreferred qualifications\nHands-on EtherCAT.'})['verdict'],'keep')

 def test_b03_explicit_required_gap_survives_missing_duties(self):
  self.assertEqual(self.assess({'requirements':'Hands-on EtherCAT required.'})['verdict'],'reject')

 def test_b04_structured_highlights_are_actual_jd_evidence(self):
  self.assertEqual(self.assess({'job_highlights':{'Responsibilities':['Design and verify RTL.'],
    'Qualifications':['Hands-on EtherCAT required.']}})['verdict'],'reject')
  self.assertEqual(self.assess({'job_highlights':{'Responsibilities':['Design and verify RTL.']}})['verdict'],'keep')

 def cache_run(self,old,new_id='R1'):
  with tempfile.TemporaryDirectory() as folder:
   db=Path(folder)/'jobs.sqlite'
   with closing(sqlite3.connect(db)) as conn, conn:
    conn.execute('CREATE TABLE jobs(url,raw,provider_key)')
    conn.execute('INSERT INTO jobs VALUES (?,?,?)',('https://example.test/job',json.dumps(old),'example'))
   c=SimpleNamespace(jobs=[{'title':'RTL Engineer','url':'https://example.test/job','source_job_id':new_id,'raw':{}}])
   read=Mock(return_value={'description':'Design and verify RTL.'})
   d.enrich_inventory(c,db,reader=read,provider='example',metadata='detail_evidence',fields=('description',),evidence='description',skip_full=True)
   return read,c

 def test_b05_bad_cached_payload_cannot_abort_detail_pass(self):
  for old in ([],{'detail_evidence':['damaged']}):
   with self.subTest(old=old):
    read,_=self.cache_run(old);read.assert_called_once()

 def test_b06_reused_url_does_not_reuse_old_requisition_jd(self):
  old={'description':'Old duties require ten years.','detail_evidence':{'status':'verified',
    'checked_at':datetime.now(timezone.utc).isoformat(),'title':'RTL Engineer','posted_at':None,'source_job_id':'R1'}}
  read,_=self.cache_run(old,'R2');read.assert_called_once()

 def test_b07_same_city_different_states_are_separate(self):
  jobs=[job('https://example.test/1','Example','RTL Intern','Springfield, IL'),job('https://example.test/2','Example','RTL Intern','Springfield, MA')]
  self.assertFalse(a.places_agree([jobs[0]],[jobs[1]]))
  rows=dict([group('a',jobs[0]),group('b',jobs[1])]);a.unify_copies(rows,{},undecided);self.assertEqual(len(rows),2)

 def test_b08_city_substring_cannot_join_different_postings(self):
  rows=dict([group('a',job('https://example.test/1','Example','RTL Engineer','New York, NY','workday')),
    group('b',job('https://example.test/2','Example','RTL Engineer','York, PA'))])
  a.unify_copies(rows,{},undecided);self.assertEqual(len(rows),2)

 def test_b09_multilocation_summary_is_not_a_city(self):
  rows=dict([group('a',job('https://example.test/1','Example','RTL Engineer','3 Locations')),
    group('b',job('https://example.test/2','Example','RTL Engineer','Austin, TX'))])
  a.unify_copies(rows,{},undecided);self.assertEqual(len(rows),1)

 def test_b10_damaged_snapshot_job_cannot_replace_working_queue(self):
  with tempfile.TemporaryDirectory() as folder:
   snapshot=QueueSnapshot(Path(folder)/'ledger',Path(folder)/'db')
   state={key:[] for key in ('pending','backlog','applied','skipped')}
   state['pending']=[{'id':'x','company':'Example','title':'RTL Engineer','confidence':50,'jobs':[{}]}]
   snapshot.save('test',state)
   self.assertIsNone(snapshot.load('test'))



class CompanyQueueTests(unittest.TestCase):
 def test_live_queue_export_and_legacy_decision_share_one_company(self):
  from contextlib import closing
  from operation1million import export, jsearch, employers
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);db=root/'jobs.sqlite';ledger=root/'applications.ndjson'
   now=datetime.now(timezone.utc).isoformat()
   names=['Marvell','Marvell Technology, Inc.','31 MSI - (Marvell Semiconductor Inc.) US']
   with closing(sqlite3.connect(db)) as conn,conn:
    conn.executescript('CREATE TABLE companies(company_key TEXT PRIMARY KEY,name TEXT); CREATE TABLE jobs(url TEXT PRIMARY KEY,company_key TEXT,title TEXT,location TEXT,source_job_id TEXT,first_seen TEXT,posted_at TEXT,provider_key TEXT,relevance REAL,closed_at TEXT,raw TEXT,last_seen TEXT);')
    for i,name in enumerate(names):
     conn.execute('INSERT INTO companies VALUES (?,?)',(str(i),name))
     conn.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
       ('https://example.test/'+str(i),str(i),'RTL Intern','Austin, TX',str(i),now,None,
        'workday' if i==0 else 'jsearch',90,None,json.dumps({'description':'Design and verify RTL.'}),now))
   state=a.queue(db,ledger);self.assertEqual(len(state['pending']),1)
   combined=state['pending'][0];self.assertEqual(combined['company'],'Marvell')
   self.assertEqual({j['company'] for j in combined['jobs']},{'Marvell'})
   self.assertEqual({r[1] for r in export.rows([('pending',combined)])},{'Marvell'})
   # A pre-normalization snapshot is replayed without rewriting the ledger.
   old=dict(combined,company=names[2]);a.append_decision(ledger,old,'applied')
   saved=ledger.read_bytes();after=a.queue(db,ledger)
   self.assertFalse(after['pending']);self.assertEqual(after['applied'][0]['company'],'Marvell')
   self.assertEqual(ledger.read_bytes(),saved)
   self.assertEqual(employers.display('A & B Semiconductor'),'A & B Semiconductor')
   item={'employer_name':names[2],'job_title':'RTL Intern','job_id':'sample',
         'job_apply_link':'https://example.test/job'}
   row=jsearch.normalize_job(item,jsearch.Query('RTL', 1, 'general'),{'marvell':'marvell'})
   self.assertEqual(row['company_key'],'marvell');self.assertEqual(row['raw']['employer_name'],names[2])
   keys=[]
   for name in ('Example Instruments','Example Instruments, Inc.'):
    keys.append(jsearch.normalize_job(dict(item,employer_name=name),jsearch.Query('RTL', 1, 'general'),{})['company_key'])
   self.assertEqual(keys[0],keys[1])



class CacheBoundaryTests(unittest.TestCase):
 def test_corrupt_snapshot_rebuilds_at_review_restart(self):
  from unittest.mock import patch
  from operation1million import review
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);ledger=root/'applications.ndjson';db=root/'jobs.sqlite'
   state={key:[] for key in ('pending','backlog','applied','skipped')}
   with patch.object(review.applications,'queue',return_value=state) as build:
    server=review.make_server(db,ledger,port=0)
    try:server.current_queue()
    finally:server.server_close()
    cache=ledger.with_name('review_queue.cache.json');saved=json.loads(cache.read_text())
    saved['state']['pending']=[{'id':'bad','company':'Example','title':'RTL','confidence':80,'jobs':[{}]}]
    cache.write_text(json.dumps(saved))
    server=review.make_server(db,ledger,port=0)
    try:self.assertEqual(server.current_queue(),state)
    finally:server.server_close()
    self.assertEqual(build.call_count,2)

 def test_preferred_qualification_list_retains_its_section(self):
  row={'title':'Engineer','raw':{'description':'Design and verify RTL.',
       'qualifications':['Required qualifications','Engineering degree',
                         'Preferred qualifications','Hands-on EtherCAT.']}}
  self.assertEqual(f.assess(row,profile())['verdict'],'keep')
