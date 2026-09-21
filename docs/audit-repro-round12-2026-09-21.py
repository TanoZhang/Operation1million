"""Offline quota/pacing/recovery audit. All HTTP endpoints are mocked."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jobdisco import collection_policy, collector, jsearch, ledger_guard, workflow_state
from jobdisco.jsearch_access import RequestGuard, QuotaExhausted
from jobdisco.validate_sources import Source


def response(payload=None, status=200, headers=None, text=''):
    result = Mock(status_code=status, text=text)
    result.headers = headers or {'content-type': 'application/json'}
    result.json.return_value = payload
    return result


def main():
    settings, _ = jsearch.load_plan()
    out = {'source': str(Path(collector.__file__).resolve().parent)}
    old = datetime(2026, 10, 15, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    new = old + 2
    with TemporaryDirectory() as directory, patch('requests.sessions.Session.request', side_effect=AssertionError('External HTTP forbidden')), patch('time.sleep'):
        root = Path(directory)
        clock = [old]
        with patch('time.time', side_effect=lambda: clock[0]):
            # B63: a response completing in the new period advances that period's cursor.
            guard = RequestGuard(root / 'rollover.sqlite')
            query = jsearch.Query('RTL', 10, 'A')
            key = query.key + ':' + jsearch.search_space(settings)
            guard.advance(key, 5)
            def receive(*args, **kwargs):
                clock[0] = new
                return response({'status': 'OK', 'data': {'jobs': [{'job_id': 'old-cycle-result', 'job_title': 'RTL Engineer', 'job_apply_link': 'https://example.test/A', 'job_description': 'Design RTL hardware.'}]}})
            session = Mock()
            session.get.side_effect = receive
            client = jsearch.Client({'endpoint_template': 'https://api.openwebninja.com/jsearch/search-v2', 'connection': {'auth_header': 'X-API-Key'}}, settings, guard, session=session)
            with patch.dict(os.environ, {'JSEARCH_API_KEY': 'synthetic-test-key'}):
                jsearch.collect([query], client, settings, {}, lambda *args: None, backfill=True, checkpoint=lambda *args: None)
                cursor = guard.resume_page(key)
                session.get.reset_mock()
                jsearch.collect([query], client, settings, {}, lambda *args: None, backfill=True)
            with closing(sqlite3.connect(guard.path)) as db:
                event_period = db.execute('SELECT period FROM credit_events').fetchone()[0]
            assert cursor == (6, True) and session.get.call_count == 0 and event_period == '2026-09-16'
            out['B63_old_cycle_response_finishes_new_cycle_cursor'] = {'charged_period': event_period, 'current_period': guard.period()[0], 'new_period_cursor': cursor, 'next_pass_requests': 0}

            # B64: old-period charges still belong to the active Pacific budget day.
            clock[0] = old
            daily_limit = settings['daily_budget']
            published = RequestGuard(root / 'published.sqlite', daily_limit=daily_limit)
            for start in range(0, daily_limit, 20):
                published.get(Mock(get=Mock(return_value=response())), 'https://example.test', credits=min(20, daily_limit - start))
            clock[0] = new
            local = RequestGuard(root / 'local.sqlite', daily_limit=daily_limit)
            comparison = ledger_guard.compare(local.path, published.path, settings)
            balances = {'local': local.balance(), 'published': published.balance()}
            local_session = Mock(get=Mock(return_value=response()))
            local.get(local_session, 'https://example.test')
            try:
                published.get(Mock(), 'https://example.test')
            except QuotaExhausted:
                published_refused = True
            else:
                published_refused = False
            assert comparison == (0, 0, True) and local_session.get.call_count == 1 and published_refused
            out['B64_monthly_comparison_misses_active_daily_spend'] = {'comparison': comparison, 'local_daily_used_before': balances['local']['day_used'], 'published_daily_used': balances['published']['day_used'], 'same_budget_day': balances['local']['day'] == balances['published']['day'], 'incorrectly_allowed_dispatch': True}

        # B65: directives for another crawler control this crawler's pacing.
        board = Source('workday:fixture', 'company_sources', 'fixture', 'Fixture', 'workday', 'https://fixture.wd1.myworkdayjobs.com/External', {'tenant': 'fixture', 'site': 'External', 'workday_host': 'wd1'})
        robots = 'User-agent: JobSourceCollector\nCrawl-delay: 2\n\nUser-agent: OtherBot\nCrawl-delay: 600\n'
        with patch.dict(collection_policy._ROBOTS_DELAY, {}, clear=True), patch.object(collection_policy.requests, 'get', return_value=response(status=200, text=robots)):
            interval = collection_policy.request_interval(board, 0)
        assert interval == 600
        out['B65_other_crawler_delay_applies_to_this_crawler'] = {'declared_for_us': 2, 'declared_for_other_bot': 600, 'chosen_seconds': interval}

        # B66: a robots 429 is not turned into a source cooldown.
        args = SimpleNamespace(delay=0, retries=0, timeout=1, max_pages=10, max_jobs=10, source_state=root / 'source-pauses.sqlite')
        c = collector.Collector(board, args)
        timeline = []
        pages = iter([response({'total': 2, 'jobPostings': [{'title': 'RTL Engineer', 'externalPath': '/job/RTL_A'}]}), response({'total': 2, 'jobPostings': [{'title': 'RTL Engineer', 'externalPath': '/job/RTL_B'}]})])
        def board_request(*args, **kwargs):
            timeline.append('board')
            return next(pages)
        c.session.request = Mock(side_effect=board_request)
        throttled = response(status=429, headers={'Retry-After': '3600'}, text='Rate limit')
        def robot_request(*args, **kwargs):
            timeline.append('robots:429')
            return throttled
        with patch.dict(collection_policy._ROBOTS_DELAY, {}, clear=True), patch.object(collection_policy.requests, 'get', side_effect=robot_request) as robots_get:
            status, detail = c.run()
        with closing(sqlite3.connect(args.source_state)) as db:
            pauses = db.execute('SELECT COUNT(*) FROM source_pauses').fetchone()[0]
        assert status == 'complete' and c.session.request.call_count == 2 and robots_get.call_count == 1 and pauses == 0
        assert timeline == ['board', 'robots:429', 'board']
        out['B66_robots_throttle_ignored'] = {'status': status, 'board_requests': 2, 'robots_status': 429, 'persisted_pauses': pauses, 'timeline': timeline}

        # B67: model the VPS publish_state copy/restore steps with actual module calls.
        # The shell itself is not executed; its target paths are checked below.
        baseline = root / 'before.sqlite'
        live = RequestGuard(root / 'vps-local.sqlite')
        live.advance('query', 2)
        shutil.copyfile(live.path, baseline)
        live.get(Mock(get=Mock(return_value=response())), 'https://example.test')
        live.pause(900)
        live.advance('query', 9, exhausted=True)
        published_path = root / 'vps-published.sqlite'
        shutil.copyfile(live.path, published_path)
        workflow_state.restore_cursors(published_path, baseline)
        restored = RequestGuard(published_path)
        comparison = ledger_guard.compare(live.path, published_path, settings)
        assert live.resume_page('query') == (9, True) and restored.resume_page('query') == (2, False) and comparison == (1, 1, True)
        shell = (Path(collector.__file__).resolve().parents[2] / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')
        assert 'python -m jobdisco.workflow_state operational/jsearch_usage.sqlite' in shell
        out['B67_vps_local_cursor_not_rewound'] = {'local_cursor': live.resume_page('query'), 'published_cursor': restored.resume_page('query'), 'next_startup_comparison': comparison, 'charges_preserved': restored.used()}

        # Recovery positive control: restoring the actual runtime ledger keeps charges/pauses.
        workflow_state.restore_cursors(live.path, baseline)
        assert live.resume_page('query') == (2, False) and live.used() == 1
        with closing(sqlite3.connect(live.path)) as db:
            assert db.execute('SELECT COUNT(*) FROM account_pause').fetchone()[0] == 1
        out['control_actual_runtime_ledger_restored'] = True
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
