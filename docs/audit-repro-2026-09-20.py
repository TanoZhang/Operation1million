"""Offline audit reproducers. Assertions describe defects present at the audited SHA.

Run from the repository with PYTHONPATH=src. No provider requests are made.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from unittest.mock import Mock, patch

from jobdisco import collection_policy, experience, store, validate_sources
from jobdisco.collector import Collector, normalize, reported_total
from jobdisco.validate_sources import Source


def main():
    results = {}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = Source('fixture', 'company_sources', 'fixture', 'Fixture',
                        'workday', 'https://example.test/jobs',
                        {'tenant': 'fixture', 'site': 'External', 'workday_host': 'wd1'})
        args = argparse.Namespace(max_pages=3, max_jobs=3, delay=0, timeout=1,
                                  retries=0, source_state=root / 'pause.sqlite')
        items = [{'title': 'RTL Engineer', 'externalPath': f'/role_{i}'} for i in range(4)]
        with patch.object(collection_policy, 'robots_delay', return_value=None):
            collector = Collector(source, args)
        collector.fetch = Mock(return_value=Mock(json=lambda: {'jobPostings': items, 'total': 4}))
        status, reason = collector.run()
        assert status == 'complete' and len(collector.jobs) == 3
        results['B01_cap_false_complete'] = {'status': status, 'stored': len(collector.jobs), 'listed': 4}

        db_path = root / 'jobs.sqlite'
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('CREATE TABLE companies (company_key TEXT PRIMARY KEY, name TEXT)')
        with patch.object(store, 'ROOT', root):
            store.migrate(db_path)
        with closing(store.connect(db_path)) as db:
            store.record_source(db, source, [normalize(source, item) for item in items],
                                'complete', 'full', 1)
            delta = store.record_source(db, source, collector.jobs, status, 'full', 1)
            assert delta['closed'] == 1 and not delta['closure_fused']
            results['B01_cap_false_complete']['valid_jobs_closed'] = delta['closed']

        args.max_jobs = 100
        with patch.object(collection_policy, 'robots_delay', return_value=None):
            collector = Collector(source, args)
        pages = iter([{'jobPostings': items[:3], 'total': 4}, {'jobPostings': [], 'total': 4}])
        collector.fetch = Mock(side_effect=lambda *a: Mock(json=lambda: next(pages)))
        status, _ = collector.run()
        assert status == 'complete' and len(collector.jobs) == 3
        results['B02_early_empty_page'] = {'status': status, 'collected': 3, 'reported_total': 4}

        with patch.object(collection_policy, 'robots_delay', return_value=None):
            collector = Collector(source, args)
        collector.fetch = Mock(return_value=Mock(json=lambda: {'jobPostings': [None, items[0]], 'total': 2}))
        status, reason = collector.run()
        assert status == 'failed' and not collector.jobs
        results['B03_malformed_item_aborts_page'] = {'status': status, 'reason': reason}

        for key, prose in (
            ('B04_lower_bound', 'No less than 5 years of professional experience required.'),
            ('B05_incidental_intern', 'This is not an internship. 5 years of professional experience required.'),
        ):
            verdict = experience.evaluate('RTL Engineer', prose)
            assert verdict['hard_pass_reason'] == ''
            results[key] = verdict

        with patch.object(collection_policy, 'robots_delay', return_value=None):
            policy = collection_policy.SourcePolicy(source, 1, root / 'paused.sqlite')
            try:
                policy.pause('HTTP 403', 86400)
            except collection_policy.SourcePaused:
                pass
        collection_policy._ROBOTS_DELAY.clear()
        with patch('requests.get', return_value=Mock(status_code=200, text='')) as request:
            policy = collection_policy.SourcePolicy(source, 1, root / 'paused.sqlite')
            try:
                policy.check()
            except collection_policy.SourcePaused:
                pass
            assert request.call_count == 1
            results['B06_robots_before_cooldown_check'] = {'requests_before_pause': request.call_count}

        # Empty boards with an explicit zero are misreported by `or` chains.
        results['B07_zero_total'] = {
            provider: reported_total(provider, payload) for provider, payload in (
                ('workday', {'total': 0}), ('amd_careers', {'totalCount': 0}),
                ('smartrecruiters', {'totalFound': 0}))}
        assert all(value is None for value in results['B07_zero_total'].values())

        with patch.object(validate_sources, 'load_sources', return_value=[source]), \
             patch.object(validate_sources, 'validate', return_value={'verdict': 'usable'}), \
             patch.object(validate_sources, 'OUT_CSV', root / 'absent' / 'results.csv'):
            try:
                validate_sources.main()
            except FileNotFoundError:
                results['B09_validator_missing_directory'] = 'FileNotFoundError after validation'
            else:
                raise AssertionError('Expected output-directory failure')

        bash = Path('C:/Program Files/Git/bin/bash.exe') if os.name == 'nt' else Path(shutil.which('bash') or '/missing')
        if bash.is_file():
            backup_root = root / 'backup-fixture'
            backup_root.mkdir()
            data = backup_root / 'data'
            remote = backup_root / 'remote.git'
            def git(*args, cwd=backup_root):
                return subprocess.run(['git', *args], cwd=cwd, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '--bare', str(remote))
            git('init', '-b', 'main', str(data))
            git('config', 'user.name', 'Offline audit', cwd=data)
            git('config', 'user.email', 'audit@example.test', cwd=data)
            (data / 'README').write_text('Synthetic local repository.\n', encoding='utf-8')
            git('add', '.', cwd=data)
            git('commit', '-m', 'Initial fixture', cwd=data)
            git('remote', 'add', 'origin', str(remote), cwd=data)
            git('push', '-u', 'origin', 'main', cwd=data)
            (data / 'operational').mkdir()
            (data / 'operational/applications.ndjson').write_text(
                '{"url":"https://example.test/1","at":"fixture","status":"applied"}\n', encoding='utf-8')
            git('remote', 'set-url', 'origin', str(backup_root / 'missing.git'), cwd=data)
            script = Path(__file__).resolve().parents[1] / 'deploy/vps/backup-applications.sh'
            # Windows has no flock. This fixture has only one writer; stub only
            # the lock, retaining real Git commits and pushes to a local bare repo.
            command = 'flock() { return 0; }; export -f flock; source "$AUDIT_SCRIPT"'
            env = dict(os.environ, JOBDISCO_ROOT=backup_root.as_posix(), AUDIT_SCRIPT=script.as_posix())
            first = subprocess.run([str(bash), '-c', command], env=env, capture_output=True, text=True)
            assert first.returncode == 1, first.stderr
            git('remote', 'set-url', 'origin', str(remote), cwd=data)
            second = subprocess.run([str(bash), '-c', command], env=env, capture_output=True, text=True)
            assert second.returncode == 0, second.stderr
            local = git('rev-parse', 'main', cwd=data)
            published = git('rev-parse', 'main', cwd=remote)
            assert local != published
            results['B08_backup_retry'] = {'first_exit': first.returncode, 'retry_exit': second.returncode,
                                          'remote_still_behind': True, 'lock_stubbed': True}
        else:
            results['B08_backup_retry'] = 'Skipped: Bash unavailable'
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
