"""Temporary-file recovery and loopback Review audit; no provider transport."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import sqlite3
import string
import sys
import tempfile
import threading
from urllib.parse import urlencode
from urllib.request import urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from jobdisco import applications, jsearch, review, store
from jobdisco.validate_sources import Source

SOURCE = Source('ashby:fixture', 'company_sources', 'fixture', 'Fixture', 'ashby', '', {})
TODAY = datetime.now(timezone.utc) - timedelta(seconds=1)


def row(ident, url, provider='ashby', raw=None, posted=None):
    return dict(company_key='fixture', company_name='Fixture', provider_key=provider,
                source_job_id=ident, url=url, title='RTL Design Engineer', location='US',
                posted_at=posted, raw=raw or {})


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix='jobdisco-audit15-') as name:
        root = Path(name)
        path = root / 'index.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
            db.execute("INSERT INTO companies VALUES ('fixture', 'Fixture')")
            db.commit()
        with patch.object(store, 'ROOT', root), patch.object(store, 'LOG', root / 'history'):
            store.migrate(path)
            with closing(store.connect(path)) as db:
                yield root, path, db


def persist(db, rows, stamp, source=SOURCE):
    result = store.record_source(db, source, rows, 'partial', 'full', 1, stamp=stamp)
    store.append_log(db, result['new_urls'] + result['changed_urls'], result['closed_urls'],
                     stamp, seen_urls=result['seen_urls'], source_id=source.source_id,
                     allow_sealed=True)
    db.commit()
    return result


def pending(path, ledger):
    state = applications.queue(path, ledger)
    return len(state['pending']) + len(state['backlog'])


@contextmanager
def server(path, ledger):
    instance = review.make_server(path, ledger, port=0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        def get(route):
            with urlopen(f'http://127.0.0.1:{instance.server_port}' + route, timeout=10) as response:
                return json.load(response)
        yield get
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def b81():
    with fixture() as (root, path, db):
        old = (TODAY - timedelta(days=10)).isoformat()
        stamp = TODAY.isoformat()
        original = row('A', 'https://example.test/shared',
                       raw={'description': 'Requires 5 years of professional experience.'},
                       posted=(TODAY - timedelta(days=15)).isoformat())
        persist(db, [original], old)
        moved = row('A', 'https://example.test/new-address')
        replacement = row('B', original['url'])
        # A move without URL reuse already preserves these fields correctly.
        persist(db, [moved], (TODAY - timedelta(seconds=1)).isoformat())
        control = dict(db.execute('SELECT * FROM jobs WHERE source_job_id="A"').fetchone())
        assert control['first_seen'] == old and control['posted_at'] == original['posted_at']
        assert 'Requires 5 years' in control['raw']
        assert pending(path, root / 'decisions.ndjson') == 0
        delta = persist(db, [moved, replacement], stamp)
        held = dict(db.execute('SELECT * FROM jobs WHERE source_job_id="A"').fetchone())
        assert held['first_seen'] == stamp and held['posted_at'] is None
        assert 'Requires 5 years' not in held['raw']
        assert delta['new'] == 2
        assert pending(path, root / 'decisions.ndjson') == 2
        print('B81: A survives the move but first_seen resets, posted_at and old description disappear; new=2')


def b82():
    with fixture() as (root, path, db):
        ledger = root / 'applications.ndjson'
        initial = (TODAY - timedelta(hours=2)).isoformat()
        latest = (TODAY - timedelta(hours=1)).isoformat()
        job = row('J', 'https://example.test/J', 'jsearch')
        paid = Source('jsearch:fixture', 'discovery', 'fixture', 'Fixture', 'jsearch', '', {})
        persist(db, [job], initial, paid)
        event = dict(provider_key='jsearch', source_job_id='J', url=job['url'],
                     title=job['title'], employer='Fixture', decision='', confidence=70)
        store.record_seen(db, [event], initial)
        db.commit()
        store.export_seen(db)
        store.record_seen(db, [dict(event, decision='required_experience_over_2_years')], latest)
        db.commit()
        assert pending(path, ledger) == 0
        store.rebuild(path)
        assert pending(path, ledger) == 1
        held = db.execute('SELECT last_seen, decision FROM seen_jobs').fetchone()
        assert tuple(held) == (initial, '')
        print('B82: in-place rebuild imports stale seen snapshot over newer rejection; review count 0 -> 1')


def b83():
    with fixture() as (root, path, db):
        rng = random.Random(15)
        jobs = [row(str(i), 'https://example.test/' + ''.join(rng.choices(string.ascii_letters, k=120)))
                for i in range(20)]
        stamp = TODAY.isoformat()
        persist(db, jobs, stamp)
        before = list(map(tuple, db.execute('SELECT url, relevance FROM jobs ORDER BY url')))
        calls = 0
        real_sync = store.os.fsync
        def fail_second(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected second-member fsync failure')
            return real_sync(fd)
        with patch.object(store, 'MAX_DAILY_LOG_BYTES', 300), \
             patch.object(store, 'calculate_score', return_value=99), \
             patch.object(store, 'now', return_value=stamp), \
             patch.object(store.os, 'fsync', side_effect=fail_second):
            try:
                store.rescore(path)
            except OSError:
                pass
            else:
                raise AssertionError('Expected injected write failure')
        assert list(map(tuple, db.execute('SELECT url, relevance FROM jobs ORDER BY url'))) == before
        invalid = [pair for pair in store.verify() if pair[1] != 'ok']
        assert invalid, store.verify()
        with patch.object(store, 'calculate_score', return_value=99), \
             patch.object(store, 'now', return_value=(TODAY + timedelta(days=1)).isoformat()):
            assert store.rescore(path) == 20
        assert [pair for pair in store.verify() if pair[1] != 'ok'] == invalid
        try:
            store.rebuild(path)
        except ValueError as exc:
            assert 'integrity' in str(exc)
        else:
            raise AssertionError('Expected unrepaired prior-day log to block replay')
        print('B83: second sharded member fails; index rolls back but log is invalid; next-day successful rescore cannot repair:', invalid)


def b84():
    with fixture() as (root, path, db):
        persist(db, [row('A', 'https://example.test/A')], TODAY.isoformat())
        plan = root / 'plan.toml'
        plan.write_text('[filter]\nexclude_title_patterns = []\n', encoding='utf-8')
        real_load = jsearch.load_plan
        ledger = root / 'applications.ndjson'
        with patch.object(jsearch, 'load_plan', side_effect=lambda: real_load(plan)), server(path, ledger) as get:
            assert len(get('/api/queue')['pending']) == 1
            # Absorb the harmless first readonly WAL lifecycle change before
            # changing only the rule file, with the writer held open throughout.
            get('/api/queue')
            plan.write_text('[filter]\nexclude_title_patterns = ["RTL"]\n', encoding='utf-8')
            assert pending(path, ledger) == 0
            assert len(get('/api/queue')['pending']) == 1
        print('B84: changed filter removes job from fresh queue, but HTTP refresh keeps cached job')


def existing_followups():
    with fixture() as (root, path, db):
        job = row('A', 'https://example.test/A', raw={'content': 'Current provider description.'})
        persist(db, [job], TODAY.isoformat())
        with server(path, root / 'applications.ndjson') as get:
            assert get('/api/job?' + urlencode({'url': job['url']}))['description'] == ''
        print('R02 variant: top-level content is stored, but Review description is empty')
    with fixture() as (root, path, db):
        ledger = root / 'applications.ndjson'
        old = row('OLD', 'https://example.test/reused', 'jsearch',
                  raw={'job_description': 'Original requisition description.'})
        paid = Source('jsearch:fixture', 'discovery', 'fixture', 'Fixture', 'jsearch', '', {})
        persist(db, [old], TODAY.isoformat(), paid)
        group = applications.queue(path, ledger)['pending'][0]
        applications.append_decision(ledger, group, 'applied')
        direct = row('DIRECT-OLD', old['url'], raw={'description': 'Direct original description.'})
        persist(db, [direct], TODAY.isoformat())
        job = row('NEW', old['url'], raw={'description': 'New requisition description.'})
        persist(db, [job], TODAY.isoformat())
        state = applications.queue(path, ledger)
        assert len(state['applied']) == 1 and len(state['pending']) == 1
        params = dict(url=job['url'], id=applications.decision_key(old),
                      provider='jsearch', title=old['title'])
        with server(path, ledger) as get:
            result = get('/api/job?' + urlencode(params))
            assert result == {'description': 'New requisition description.'}
        assert not db.execute('SELECT 1 FROM job_identities WHERE source_job_id="OLD"').fetchone()
        print('B23/B27 follow-up: historical cross-provider id receives replacement JD despite no matching identity alias')


def o10():
    with fixture() as (root, path, db):
        facts = store._file_facts
        scanned = []
        def count(file):
            result = facts(file)
            scanned.append(result[1])
            return result
        with patch.object(store, '_file_facts', side_effect=count):
            for i in range(20):
                persist(db, [row(str(i), f'https://example.test/{i}')], TODAY.isoformat())
        assert scanned == list(range(2, 41, 2)), scanned
        print('O10: 20 small checkpoints leave 40 log records but manifest refresh decompresses', sum(scanned), 'records total')


if __name__ == '__main__':
    for case in (b81, b82, b83, b84, existing_followups, o10):
        case()
