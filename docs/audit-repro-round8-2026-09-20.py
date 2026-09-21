"""Systematic text-to-Review audit. Synthetic state only; no external HTTP."""
from contextlib import closing
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
import json
import io
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import threading
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from jobdisco import applications, experience, job_text, ranking, review, store, jsearch
from jobdisco.validate_sources import Source


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("CREATE TABLE companies(company_key TEXT PRIMARY KEY, name TEXT);"
                         "INSERT INTO companies VALUES ('fixture','Fixture');")
    store.migrate(path)


def row(identity='A', provider='ashby', **extra):
    result = dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                  source_job_id=identity, title='RTL Engineer', location='Austin, Texas, US',
                  url='https://example.test/' + identity, posted_at=None,
                  raw={'description': 'Design RTL hardware.'})
    result.update(extra)
    return result


def insert(path, rows):
    source = Source('fixture', 'company_sources', 'fixture', 'Fixture', rows[0]['provider_key'], '', {})
    with closing(store.connect(path)) as db, db:
        store.record_source(db, source, rows, 'partial', 'full', 1)


def experience_checks(root):
    controls = [
        ('RTL Intern', '5 years required', None, True, False),
        ('RTL Engineer', '2 years required', 2, False, False),
        ('RTL Engineer', '5 years required', 5, False, True),
        ('RTL Engineer', '5 years preferred', None, False, False),
        ('RTL Engineer', 'BS+4 / MS+2', 2, False, False),
        ('RTL Engineer', 'BS+5 / MS+3', 3, False, True),
        ('RTL Engineer', 'BS+5 or MS+2. 4 years experience required.', 4, False, True),
        ('RTL Engineer', 'No more than 5 years of experience.', None, False, False),
        ('RTL Engineer', 'No less than 5 years of experience.', 5, False, True),
        ('RTL Engineer', 'This is not an internship. 5 years experience required.', 5, False, True),
        ('RTL Engineer', 'You will mentor our interns. 5 years experience required.', 5, False, True),
        ('RTL Engineer', 'Preferred qualifications:\n5 years experience', None, False, False),
        ('RTL Engineer', 'Preferred qualifications:\n5 years experience\nRequirements:\n3 years experience', 3, False, True),
        ('RTL Engineer', 'A 5-year roadmap and a 2-year degree.', None, False, False),
    ]
    for title, text, years, entry, refused in controls:
        facts = experience.evaluate(title, text)
        assert facts['entry_override'] == entry
        if not entry:
            assert facts['effective_experience_years'] == years, (text, facts)
        assert bool(facts['hard_pass_reason']) == refused
    cases = {
        'B34_postfix_negation_rejects_eligible_job': ('2 years experience required. 5 years experience is not required.', 0),
        'B35_prior_internship_is_not_an_intern_role': ('Candidates must have prior internship experience. 5 years experience required.', 1),
        'B36_skill_slash_creates_degree_alternative': ('BS with 5 years experience and MS with 2 years experience in RTL/FPGA design required.', 1),
    }
    # The slash in a skill name alone changes the degree-alternative verdict.
    with_slash = experience.evaluate('RTL Engineer', cases['B36_skill_slash_creates_degree_alternative'][0])
    without_slash = experience.evaluate('RTL Engineer', cases['B36_skill_slash_creates_degree_alternative'][0].replace('RTL/FPGA', 'RTL and FPGA'))
    assert with_slash['effective_experience_years'] == 2
    assert without_slash['effective_experience_years'] == 5
    assert experience.evaluate('RTL Engineer', '5 years experience required, including internship experience.')['entry_override']
    assert experience.evaluate('RTL Engineer', '3 years experience not necessary.')['hard_pass_reason']
    run = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))['run']
    results = {}
    for name, (text, pending_count) in cases.items():
        folder = root / name
        folder.mkdir()
        job = {'job_id': name, 'job_title': 'RTL Engineer', 'employer_name': 'Fixture',
               'job_apply_link': 'https://example.test/' + name, 'job_description': text}
        assert run(folder, 'collection', [], paid=[job])[0] == 0
        pending = applications.queue(folder / 'jobs.sqlite', folder / 'applications.ndjson')['pending']
        assert len(pending) == pending_count
        results[name] = dict(text=text, pending=len(pending), facts=experience.evaluate('RTL Engineer', text))
    return {'controls': len(controls), 'findings': results}


def title_checks(root):
    controls = [
        ('RTL Engineer Posted today', '', 'RTL Engineer'),
        ('RTL Engineer Austin, Texas, United States Posted today', 'Austin, Texas, US', 'RTL Engineer'),
        ('New York Hardware Engineer', '', 'New York Hardware Engineer'),
        ('  RTL\u00a0Engineer  ', '', 'RTL Engineer'),
        ('RTL Engineer', '', 'RTL Engineer'),
    ]
    for title, location, expected in controls:
        assert job_text.clean_title(title, location) == expected
    noisy = 'RTL Engineer Posted today - Austin, Texas, US'
    cleaned = job_text.clean_title(noisy, 'Austin, Texas, US')
    assert cleaned == 'RTL Engineer Posted today'
    assert job_text.clean_title(cleaned, 'Austin, Texas, US') == 'RTL Engineer'
    path = root / 'title.sqlite'
    database(path)
    insert(path, [row(title=noisy)])
    actual = applications.queue(path, root / 'title.ndjson')['pending'][0]['title']
    assert actual == cleaned
    return {'controls': len(controls), 'B37_suffix_order_non_idempotent': {'input': noisy, 'review_title': actual}}


def ranking_checks():
    examples = [('RTL Intern', 0), ('Hardware Intern', 1), ('RTL Engineer', 2),
                ('Hardware Engineer', 3), ('Marketing Intern', 4), ('SOC Analyst', 4)]
    for title, bucket in examples:
        assert ranking.bucket(title) == bucket
    dates = ['2026-09-20', '2026-09-20T12:00:00Z', 'September 20, 2026', '09/20/2026']
    for value in dates:
        assert ranking.posted_day(value).isoformat() == '2026-09-20'
    for value in (None, '', '2026-99-99', 'recently'):
        assert ranking.posted_day(value) is None
    assert ranking._seconds('2026-09-20T12:00:01Z') > ranking._seconds('2026-09-20T12:00:00Z')
    groups = [dict(id=str(i), title=title, confidence=50,
                   jobs=[{'posted_at':'2026-09-20','first_seen':'2026-09-20T12:00:00Z'}])
              for i, (title, _) in enumerate(examples[:5])]
    assert [g['id'] for g in ranking.order(list(reversed(groups)))] == [str(i) for i in range(5)]
    assert sum(ranking.summarize(groups).values()) == len(groups)
    assert ranking.rank({}) and ranking.order([]) == []
    return {'functions_checked': ['bucket', 'summarize', 'posted_day', '_seconds', 'rank', 'order'],
            'new_confirmed_findings': 0, 'controls': 'bands, date formats, invalid dates, UTC ties, empty inputs, stable ordering'}


def application_checks(root):
    path = root / 'application-controls.sqlite'
    ledger = root / 'application-controls.ndjson'
    database(path)
    assert applications.read_events(ledger) == []
    a, other = row(), row(company_key='other')
    assert applications.decision_key(a) != applications.decision_key(other)
    assert applications.decision_key(row(provider='jsearch')) == applications.decision_key(row(provider='jsearch', company_key='other'))
    with patch.dict(os.environ, {'JOBDISCO_STORE': str(root / 'custom')}):
        assert applications.ledger_path() == root / 'custom' / 'operational/applications.ndjson'
    insert(path, [a])
    group = applications.queue(path, ledger)['pending'][0]
    applications.append_decision(ledger, group, 'applied', 'Done')
    assert len(applications.queue(path, ledger)['applied']) == 1
    applications.append_decision(ledger, group, 'pending')
    assert len(applications.queue(path, ledger)['pending']) == 1
    with applications.locked(ledger):
        assert len(applications.read_events(ledger)) == 2
    broken = root / 'broken.ndjson'
    broken.write_text('{"url":"https://example.test","at":"now","status":"applied"}', encoding='utf-8')
    try:
        applications.read_events(broken)
    except ValueError as exc:
        assert 'line 1' in str(exc)
    else:
        raise AssertionError('Incomplete ledger line accepted')
    assert broken.read_text(encoding='utf-8').endswith('}')
    # Recheck B27 against the added company/title restriction without renumbering.
    identity_path = root / 'same-title-replacement.sqlite'
    identity_ledger = root / 'same-title-replacement.ndjson'
    database(identity_path)
    insert(identity_path, [row(provider='jsearch')])
    original = applications.queue(identity_path, identity_ledger)['pending'][0]
    applications.append_decision(identity_ledger, original, 'applied')
    insert(identity_path, [row('B', url='https://example.test/A')])
    insert(identity_path, [row('C', url='https://example.test/A')])
    assert not applications.queue(identity_path, identity_ledger)['pending']
    # A query-scoped mismatch should not erase a separate global rejection.
    run = runpy.run_path(str(Path(__file__).with_name('audit-repro-round5-2026-09-20.py')))['run']
    folder = root / 'query-rejection'
    folder.mkdir()
    job = {'job_id':'A', 'job_title':'RTL Engineer', 'employer_name':'Fixture',
           'job_apply_link':'https://example.test/A', 'job_description':'Design RTL.'}
    assert run(folder, 'first', [], paid=[job])[0] == 0
    revised = dict(job, job_description='5 years experience required.')
    assert run(folder, 'second', [], paid=[revised])[0] == 0
    assert not applications.queue(folder / 'jobs.sqlite', folder / 'ledger.ndjson')['pending']
    query_type = jsearch.Query
    def mismatched_query(*args, **kwargs):
        kwargs['aliases'] = ('Unrelated Employer',)
        return query_type(*args, **kwargs)
    with patch.object(jsearch, 'Query', side_effect=mismatched_query):
        assert run(folder, 'third', [], paid=[revised])[0] == 0
    pending = applications.queue(folder / 'jobs.sqlite', folder / 'ledger.ndjson')['pending']
    with closing(store.connect(folder / 'jobs.sqlite')) as db:
        reason = db.execute('SELECT decision FROM seen_jobs').fetchone()[0]
    assert reason == 'employer_mismatch' and len(pending) == 1
    return {'controls': 'scoped keys, ledger path, lock/read/append/reopen, incomplete-line rejection',
            'existing_B27_still_reproduces': 'same-title replacement C remains hidden',
            'B38_query_mismatch_erases_global_rejection': {'latest_reason': reason, 'pending_after_third_pass': len(pending)}}


def review_checks(root):
    path = root / 'review.sqlite'
    ledger = root / 'review.ndjson'
    database(path)
    insert(path, [row(provider='jsearch')])
    original = applications.queue(path, ledger)['pending'][0]
    applications.append_decision(ledger, original, 'applied')
    insert(path, [row('B', url='https://example.test/A')])
    with closing(store.connect(path)) as db:
        aliases = db.execute('SELECT COUNT(*) FROM job_identities').fetchone()[0]
    assert aliases == 2
    server = review.make_server(path, ledger, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def get(route):
        with urlopen(base + route, timeout=5) as response:
            return json.load(response)
    try:
        state = get('/api/queue')
        assert len(state['applied']) == 1 and state['token']
        detail = get('/api/job?' + urlencode({'url':'https://example.test/A','id':original['id']}))
        assert detail.get('replaced') is True and detail['description'] == ''
        # Use a separate current identity to exercise unambiguous prose handling.
        insert(path, [row('C', raw={'descriptionPlain':'Implement FIFO<T> and std::vector<int> for RTL tooling.'})])
        detail_text = get('/api/job?' + urlencode({'url':'https://example.test/C', 'id':applications.decision_key(row('C'))}))
        assert '<T>' not in detail_text['description'] and '<int>' not in detail_text['description']
        # Real status-code controls, with no state change from denied writes.
        from urllib.error import HTTPError
        for request, expected in [(Request(base+'/api/queue', headers={'Host':'example.test'}),403),
                                  (Request(base+'/api/decision', data=b'{}'),403),
                                  (Request(base+'/api/decision', data=b'[]', headers={'X-Review-Token':state['token']}),400),
                                  (Request(base+'/api/decision', data=b'{"id":"unknown","status":"applied"}', headers={'X-Review-Token':state['token']}),409),
                                  (Request(base+'/missing'),404)]:
            try:
                urlopen(request, timeout=5)
            except HTTPError as exc:
                assert exc.code == expected
            else:
                raise AssertionError('Expected HTTP rejection')
        with urlopen(base+'/app.js', timeout=5) as response:
            assert 'javascript' in response.headers['Content-Type']
            assert response.headers['Cache-Control'] == 'no-store'
        body = json.dumps({'id':applications.decision_key(row('C')),'status':'applied'}).encode()
        with urlopen(Request(base+'/api/decision', data=body, headers={'X-Review-Token':state['token']}), timeout=5) as response:
            assert json.load(response)['status'] == 'applied'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    with patch('sys.argv',['review','--db',str(root / 'missing.sqlite')]), redirect_stderr(io.StringIO()):
        try:
            review.main()
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError('Missing index accepted')
    fake = Mock(server_port=1234)
    fake.serve_forever.side_effect = KeyboardInterrupt
    with patch('sys.argv',['review','--db',str(path)]), patch.object(review,'make_server',return_value=fake), redirect_stdout(io.StringIO()):
        review.main()
    fake.server_close.assert_called_once()
    return {'controls':'queue projection, host restriction, write token, missing route',
            'B39_alias_upgrade_mislabeled_replacement': {'known_aliases':aliases,'response':detail},
            'B40_plain_description_loses_template_arguments': detail_text}


def frontend_checks():
    """Run unchanged app.js in Node with a minimal DOM and deferred fetches."""
    code = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
process.env.TZ='America/Los_Angeles';
const source=fs.readFileSync(process.argv[1],'utf8');
class Clock extends Date { constructor(...args){super(...(args.length?args:['2026-09-20T19:00:00Z']));} }
class Element {
  constructor(){this.value=''; this.textContent=''; this.innerHTML=''; this.open=false; this.hidden=false;this.children=[];}
  setAttribute(){} append(...children){this.children.push(...children);} replaceChildren(){this.children=[];} focus(){}
  querySelector(){return new Element();}
  showModal(){this.open=true;} close(){this.open=false;}
}
function harness(){
 const elements=new Map(), calls=[];
 const tabs=['pending','backlog','applied','skipped'].map(tab=>Object.assign(new Element(),{dataset:{tab}}));
 const document={querySelector(selector){if(!elements.has(selector))elements.set(selector,new Element()); return elements.get(selector);},querySelectorAll(selector){return selector==='[data-tab]'?tabs:[];},createElement(){return new Element();}};
 const ctx=vm.createContext({document,URL,Date:Clock,fetch(path,options){return new Promise((resolve,reject)=>calls.push({path,options,resolve,reject}));}});
 vm.runInContext(source,ctx); // The real startup refresh remains deferred.
 return {ctx,calls,elements,tabs};
}
const group=id=>({id,company:'Fixture',title:'RTL Engineer '+id,confidence:50,bucket:2,jobs:[{url:'https://example.test/'+id,provider_key:'ashby',first_seen:'2026-09-20T12:00:00Z',posted_at:null}]});
const state=(revision,pending,applied=[])=>({revision,pending,applied,backlog:[],skipped:[],labels:[],token:'synthetic'});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function answer(call,body){call.resolve({ok:true,json:async()=>body});await flush();}
(async()=>{
 let h=harness();
 const dates=vm.runInContext("({bare:date('2026-09-20'),localNoon:date('2026-09-20T12:00:00'),today:postedToday({posted_at:'2026-09-20'}),timestampToday:postedToday({posted_at:'2026-09-20T19:00:00Z'})})",h.ctx);
 assert.notEqual(dates.bare,dates.localNoon); assert.equal(dates.today,false);assert.equal(dates.timestampToday,true);
 assert.equal(vm.runInContext("safeLink('javascript:alert(1)')",h.ctx),'#');
 assert.equal(vm.runInContext("escapeText('<script>')",h.ctx),'&lt;script&gt;');
 h=harness();
 vm.runInContext('refresh()',h.ctx);
 await answer(h.calls[1],state('new',[group('B')]));
 const intermediate=vm.runInContext('state.revision',h.ctx);
 await answer(h.calls[0],state('old',[group('A')]));
 const reverted=vm.runInContext('state.revision',h.ctx);
 assert.equal(intermediate,'new'); assert.equal(reverted,'old');
 h=harness();
 await answer(h.calls[0],state('initial',[group('A'),group('B')]));
 const selectedAtOpen=vm.runInContext('selected',h.ctx);
 vm.runInContext("document.querySelector('#skip').onclick()",h.ctx);
 assert.equal(h.elements.get('#skip-dialog').open,true);
 vm.runInContext('refresh()',h.ctx);
 const pendingRefresh=h.calls.filter(c=>c.path==='/api/queue').at(-1);
 await answer(pendingRefresh,state('changed',[group('B')],[group('A')]));
 assert.equal(h.elements.get('#skip-dialog').open,true);
 vm.runInContext("document.querySelector('#skip-form').onsubmit({preventDefault(){}})",h.ctx);
 const decision=JSON.parse(h.calls.find(c=>c.path==='/api/decision').options.body);
 assert.equal(selectedAtOpen,'A');assert.equal(decision.id,'B');assert.equal(decision.status,'skipped');
 // Description responses have a generation check; verify that protection works.
 h=harness();
 await answer(h.calls[0],state('one',[group('A')]));
 const firstDetail=h.calls.find(c=>c.path.startsWith('/api/job'));
 vm.runInContext('refresh()',h.ctx);
 await answer(h.calls.filter(c=>c.path==='/api/queue').at(-1),state('two',[group('B')]));
 const secondDetail=h.calls.filter(c=>c.path.startsWith('/api/job')).at(-1);
 await answer(secondDetail,{description:'B description'});
 await answer(firstDetail,{description:'A description'});
 assert.equal(h.elements.get('#description').textContent,'B description');
 h=harness();
 await answer(h.calls[0],Object.assign(state('many',Array.from({length:76},(_,i)=>group('J'+i))),{backlog:[group('D')]}));
 assert.equal(h.elements.get('#list').children.at(-1).textContent,'Show more');
 h.elements.get('#list').children.at(-1).onclick();
 assert.equal(vm.runInContext('visibleLimit',h.ctx),150);
 h.elements.get('#search').value='does not exist';h.elements.get('#search').oninput();
 assert.equal(vm.runInContext('selected',h.ctx),null);
 h.elements.get('#search').value='';h.elements.get('#search').oninput();
 h.tabs[1].onclick();assert.equal(vm.runInContext('selected',h.ctx),'D');
 vm.runInContext("document.querySelector('#skip').onclick()",h.ctx);
 h.elements.get('#cancel-skip').onclick();assert.equal(h.elements.get('#skip-dialog').open,false);
 vm.runInContext('busy=true',h.ctx);h.tabs[0].onclick();assert.equal(vm.runInContext('tab',h.ctx),'backlog');
 h=harness();
 h.calls[0].resolve({ok:false,json:async()=>({error:'Synthetic failure'})});await flush();
 assert.equal(h.elements.get('#error').textContent,'Synthetic failure');
 process.stdout.write(JSON.stringify({B41_date_only_shifts_day:dates,B42_old_refresh_overwrites_new:{intermediate,final:reverted},B43_skip_dialog_changes_target:{openedFor:selectedAtOpen,submittedFor:decision.id},controls:'safe links, text escaping, latest-description guard, show more, search/no match, tabs, cancel, busy-tab guard, API errors'},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    path = Path(applications.__file__).with_name('review_static') / 'app.js'
    return json.loads(subprocess.check_output(['node', '-e', code, str(path)], text=True, timeout=30))


def main():
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request',
            side_effect=AssertionError('External HTTP prohibited')):
        root = Path(directory)
        with patch.object(store, 'ROOT', root), patch.object(store, 'LOG', root / 'history'):
            results = {'source': str(Path(applications.__file__).resolve()),
                       'experience': experience_checks(root), 'job_text': title_checks(root),
                       'ranking': ranking_checks(), 'applications': application_checks(root),
                       'review': review_checks(root), 'frontend': frontend_checks()}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
