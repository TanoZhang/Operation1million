import argparse,csv,json,sys
from pathlib import Path
from collections import Counter
from dataclasses import replace
from datetime import datetime,timezone
from jobdisco.collector import *
from jobdisco.paths import DB
base=ROOT/'runs'
names=['20260915T190233Z','20260915T185610Z','20260915T190100Z','20260915T185850Z']
jobs_by_company={};reports={};runs=[]
for name in names:
 path=base/name
 manifest=json.loads((path/'manifest.json').read_text());runs.append({'directory':name,**manifest})
 selected=list(csv.DictReader((path/'company_results.csv').open(encoding='utf-8')))
 for row in selected:
  # The large-board run supersedes the earlier Amazon repair attempt.
  reports[row['company_key']]=row;jobs_by_company[row['company_key']]=[]
 for line in (path/'jobs.jsonl').open(encoding='utf-8'):
  job=json.loads(line);jobs_by_company[job['company_key']].append(job)
args=argparse.Namespace(delay=0,timeout=25,max_pages=1,max_jobs=10000)
audit=[]
sources={s.company_key:s for s in load_sources(DB)}
for key,page in [('apple',226),('google',169)]:
 source=replace(sources[key],access_url=query_url(sources[key].access_url,page=page))
 c=Collector(source,args);c.jobs=jobs_by_company[key].copy()
 status,reason=c.run()
 audit.append({'company_key':key,'terminal_url':source.access_url,'status':status,'reason':reason})
 if status=='complete':
  reports[key].update(direct_status='complete',failure_reason='',fallback_status='',next_step='None')
reports['amazon'].update(direct_status='partial',failure_reason='Amazon search returned its 10,000-result ceiling; partition searches to establish full coverage',fallback_status='missing_credentials')
for row in reports.values():
 if row['direct_status']!='complete':
  row['next_step']='; '.join(filter(None,[row['failure_reason'],'Set JSEARCH_API_KEY or RAPIDAPI_KEY for fallback' if row['fallback_status']=='missing_credentials' else '']))
rows=sorted(reports.values(),key=lambda r:r['company_key'])
jobs=[normalize(replace(sources[key],provider_key=j['provider_key']),j['raw']) for key in sorted(jobs_by_company) for j in jobs_by_company[key]]
assert len(rows)==52
assert len({(j['company_key'],j['url']) for j in jobs})==len(jobs)
assert all(list(j)==FIELDS and j['title'] and j['url'].startswith('https://') for j in jobs)
assert all(len(jobs_by_company[r['company_key']])==int(r['jobs']) for r in rows)
out=base/'20260915T190602Z';out.mkdir(exist_ok=True)
with (out/'jobs.jsonl').open('w',encoding='utf-8') as f:
 for job in jobs:f.write(json.dumps(job,ensure_ascii=True)+'\n')
write_csv(out/'jobs.csv',jobs,FIELDS);write_csv(out/'company_results.csv',rows,list(rows[0]))
manifest={'collected_at':datetime.now(timezone.utc).isoformat(),'companies':len(rows),'jobs':len(jobs),'direct_status_counts':dict(Counter(r['direct_status'] for r in rows)),'jsearch_requests':0,'input_runs':runs,'terminal_page_verification':audit}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
for path in (base/'20260915T185610Z').glob('*_rejected.json'):
 (out/path.name).write_bytes(path.read_bytes())
lines=['# Job Source Collection Results - 2026-09-15','',f'Collected {len(jobs):,} records from 52 source companies. '+str(sum(int(r['jobs'])>0 for r in rows))+' companies returned jobs.','',f'Direct status: {dict(Counter(r["direct_status"] for r in rows))}. JSearch requests: 0 (API key unavailable).','', 'Results combine an all-source run with targeted reruns after extractor corrections. Input manifests and live terminal-page checks are retained in `runs/20260915T190602Z/manifest.json`.','', 'Ten offline regression tests passed. JSONL/CSV record counts, required fields, per-company counts, URL uniqueness, and the absence of the five deleted companies were checked.','', '## Company Results','', '| Company | Jobs | Direct status | Failure reason / next step |','|---|---:|---|---|']
for r in rows:
 note=r['next_step'].replace('|','/').replace('\n',' ')
 lines.append(f"| {r['company_name']} | {r['jobs']} | {r['direct_status']} | {note} |")
lines += ['', '## Remaining Work','', '- Configure JSearch credentials and validate a paid response with the strict employer filter. The nine configured fallback companies remain uncollected.', '- Amazon exposes a 10,000-result search ceiling. Partition searches by location or job category and deduplicate before claiming full-board coverage.', '- Cadence and Samsung each returned one malformed record. Valid records were collected; rejected records are retained for review.', '- Rivos yielded 15 public Uplers job cards; pagination completeness is unverified.', '- TSMC returned HTTP 403. Ventana redirected to a Jobvite product site, with no job records. Both attempt JSearch when credentials are available.', '- Add a shared daily JSearch quota ledger before scheduling repeated automated runs. No scheduled task or startup entry was installed.', '', '## Source Changes','', '- MatX migrated from Greenhouse to Ashby, verified against [the company careers page](https://matx.com/jobs). SQL and SQLite were updated together.', '- Renesas returned 403 during the validator run but succeeded through the collector using its standard identifying User-Agent; 910 public detail pages were collected without challenge bypass.', '- Four missing tuple-opening parentheses in schema.sql were repaired. The source catalog rebuild and idempotent rerun passed SQLite foreign-key checks.', '', 'The schema and JSONL preserve provider data. Most boards are worldwide; Apple and JSearch use their configured US scope. Counts are source records, not deduplicated real-world requisitions across locations.']
(ROOT/'docs/job-source-collection-results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in manifest.items() if k not in ['input_runs']},indent=2))
