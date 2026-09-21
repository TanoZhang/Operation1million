"""Offline deployment audit. All Git remotes and shell mutations are temporary.

Run with the project's Python. Requires Git Bash on Windows, or bash on POSIX.
Assertions describe defects, so corrected implementations should fail them.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from jobdisco import applications, collection_policy, jsearch_access

BASH = (Path('C:/Program Files/Git/bin/bash.exe') if os.name == 'nt'
        else Path(shutil.which('bash')))
PYTHON = Path(sys.executable).as_posix()
ENV = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'),
       'JOBDISCO_PYTHON': PYTHON, 'HEALTHCHECK_URL': ''}


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def git(directory, *args, check=True):
    result = subprocess.run(['git', *map(str, args)], cwd=directory,
                            capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result


def shell(directory, text, **env):
    # Each caller owns this temporary directory. Script deletion and moves
    # resolve exclusively beneath it; no production host is reachable.
    put(directory / 'driver.sh', text)
    return subprocess.run([str(BASH), 'driver.sh'], cwd=directory,
                          env={**ENV, **env}, capture_output=True, text=True,
                          timeout=45)


def check(result, code=0):
    assert result.returncode == code, (result.returncode, result.stdout, result.stderr)


def day_file(data, days_ago=1):
    day = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%d')
    body = gzip.compress(b'{"event":"fixture"}\n', mtime=0)
    path = data / 'runs' / (day + '.ndjson.gz')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    put(data / 'manifests' / (day + '.json'), json.dumps({
        'run_date': day, 'file': f'runs/{day}.ndjson.gz',
        'sha256': hashlib.sha256(body).hexdigest()}))


def fixture(directory):
    data = directory / 'fixture/data'
    day_file(data)
    put(data / 'source_state.json', '[]\n')
    operational = data / 'operational'
    put(operational / 'applications.ndjson',
        '{"url":"https://example.test/A","at":"2026-09-21T00:00:00Z","status":"applied"}\n')
    jsearch_access.RequestGuard(path=operational / 'jsearch_usage.sqlite')
    source = SimpleNamespace(company_key='fixture', provider_key='workday',
                             access_url='https://example.test/jobs')
    policy = collection_policy.SourcePolicy(source, 1, path=operational / 'source_access.sqlite')
    policy.check()
    (operational / 'seen_jobs.ndjson.gz').write_bytes(gzip.compress(b'', mtime=0))
    snapshot = directory / 'fixture/sqlite/job_discovery.sqlite'
    snapshot.parent.mkdir(parents=True)
    with closing(sqlite3.connect(snapshot)) as db, db:
        db.execute('CREATE TABLE jobs (closed_at TEXT)')
        db.execute('INSERT INTO jobs VALUES (NULL)')
    return data, source


def backup(directory, extra='', real_remote=False):
    if real_remote:
        ssh = 'ssh() { bash -c "${@: -1}"; }\n'
    else:
        ssh = 'ssh() { tar czf - -C fixture data sqlite; }\n'
    driver = ('python3() { ' + shlex.quote(PYTHON) + ' "$@"; }\n'
              'export -f python3\n' + ssh + extra + '\nsource '
              + shlex.quote((ROOT / 'deploy/local/backup-from-vps.sh').as_posix())
              + ' backup\n')
    return shell(directory, driver,
                 JOBDISCO_VPS_DATA=(directory / 'fixture/data').as_posix(),
                 JOBDISCO_VPS_DB=(directory / 'fixture/sqlite/job_discovery.sqlite').as_posix(),
                 JOBDISCO_VPS='offline-fixture')


def pause(policy):
    try:
        policy.pause('fixture refusal', 3600)
    except collection_policy.SourcePaused:
        pass


def blocked(policy):
    try:
        policy.check()
        return False
    except collection_policy.SourcePaused:
        return True


def b68(directory):
    data, source = fixture(directory)
    live = directory / 'fixture/code/.local'
    live.mkdir(parents=True)
    for name in ('jsearch_usage.sqlite', 'source_access.sqlite'):
        shutil.copyfile(data / 'operational' / name, live / name)
    guard = jsearch_access.RequestGuard(path=live / 'jsearch_usage.sqlite')
    guard.get(SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, headers={})),
              'https://example.test/mock')
    pause(collection_policy.SourcePolicy(source, 1, path=live / 'source_access.sqlite'))
    # Execute the remote command constructed by the real backup script locally.
    result = backup(directory, real_remote=True)
    check(result)
    copied = directory / 'backup/current/operational'
    saved = jsearch_access.RequestGuard(path=copied / 'jsearch_usage.sqlite')
    assert guard.balance()['period_used'] == 1 and saved.balance()['period_used'] == 0
    assert not blocked(collection_policy.SourcePolicy(source, 1, path=copied / 'source_access.sqlite'))
    print('B68: backup exit=0; live credits=1, copied credits=0; live cooldown absent from copy')


def b69(directory):
    results = []
    for name in ('jsearch_usage.sqlite', 'source_access.sqlite',
                 'applications.ndjson', 'seen_jobs.ndjson.gz'):
        case = directory / name
        case.mkdir()
        data, _ = fixture(case)
        check(backup(case))
        path = data / 'operational' / name
        path.write_bytes(b'broken nonempty state')
        for _ in range(2):
            check(backup(case))
        for generation in ('current', 'previous'):
            assert (case / 'backup' / generation / 'operational' / name).read_bytes() == path.read_bytes()
        invalid = False
        try:
            if name.endswith('.sqlite'):
                with closing(sqlite3.connect(path)) as db:
                    db.execute('PRAGMA quick_check').fetchall()
            elif name.endswith('.ndjson'):
                applications.read_events(path)
            else:
                gzip.decompress(path.read_bytes())
        except (sqlite3.DatabaseError, ValueError, gzip.BadGzipFile):
            invalid = True
        assert invalid
        results.append(name)
    print('B69: two successful pulls replace both good generations with invalid files:', ', '.join(results))


def b70(directory):
    fixture(directory)
    check(backup(directory))
    assert (directory / 'backup/current').is_dir()
    # Inject failure precisely at installation of the validated incoming tree.
    fault = '''mv() {
  if [ "${@: -1}" = 'backup/current' ]; then
    echo 'injected destination rename failure' >&2
    return 73
  fi
  command mv "$@"
}
'''
    first = backup(directory, fault)
    check(first, 73)
    assert (directory / 'backup/previous.tmp').is_dir()
    assert not (directory / 'backup/current').exists()
    second = backup(directory, fault)
    check(second, 73)
    assert not any((directory / 'backup' / name).exists()
                   for name in ('current', 'previous', 'previous.tmp'))
    print('B70: repeated injected rename failure deletes the last installed good generation; incoming remains')


def repo_fixture(directory):
    remote, data = directory / 'remote.git', directory / 'data'
    git(directory, 'init', '--quiet', '--bare', remote)
    git(directory, 'clone', '--quiet', remote, data)
    git(data, 'config', 'user.name', 'Offline Audit')
    git(data, 'config', 'user.email', 'audit@example.test')
    day_file(data, 0)
    day_file(data, 30)
    put(data / 'source_state.json', '[]\n')
    put(data / 'operational/applications.ndjson',
        '{"url":"https://example.test/A","at":"2026-09-21T00:00:00Z","status":"applied"}\n')
    git(data, 'add', '-A')
    git(data, 'commit', '--quiet', '-m', 'fixture baseline')
    git(data, 'branch', '-M', 'main')
    git(data, 'push', '--quiet', '-u', 'origin', 'main')
    git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
    return remote, data


def compact(directory):
    driver = '''flock() { return 0; }
job-store() {
  "$JOBDISCO_PYTHON" -c 'from jobdisco import store; assert all(s == "ok" for _, s in store.verify())'
}
python() { "$JOBDISCO_PYTHON" "$@"; }
source ''' + shlex.quote((ROOT / 'deploy/vps/compact-history.sh').as_posix()) + '\n'
    return shell(directory, driver, JOBDISCO_ROOT=directory.as_posix(), JOBDISCO_KEEP_DAYS='1')


def b71(directory):
    remote, data = repo_fixture(directory)
    other = directory / 'other'
    git(directory, 'clone', '--quiet', remote, other)
    git(other, 'config', 'user.name', 'Offline Audit')
    git(other, 'config', 'user.email', 'audit@example.test')
    with (other / 'operational/applications.ndjson').open('a', encoding='utf-8') as out:
        out.write('{"url":"https://example.test/B","at":"2026-09-21T01:00:00Z","status":"applied"}\n')
    git(other, 'add', '-A')
    git(other, 'commit', '--quiet', '-m', 'new remote decision')
    git(other, 'push', '--quiet')
    before = git(remote, 'show', 'main:operational/applications.ndjson').stdout
    check(compact(directory))
    after = git(remote, 'show', 'main:operational/applications.ndjson').stdout
    assert 'example.test/B' in before and 'example.test/B' not in after
    print('B71: stale origin/main passes preflight; real local force-push removes a newer remote decision')


def b72(directory):
    remote, data = repo_fixture(directory)
    git(remote, 'config', 'receive.denyNonFastForwards', 'true')
    first = compact(directory)
    assert first.returncode != 0 and 'non-fast-forward' in first.stderr
    git(remote, 'config', 'receive.denyNonFastForwards', 'false')
    second = compact(directory)
    assert second.returncode == 1 and 'Local and remote differ' in second.stderr
    pull = git(data, 'pull', '--ff-only', check=False)
    assert pull.returncode != 0
    print('B72: failed compaction push strands rewritten/pruned local main; retry=1, normal pull=', pull.returncode)


def b73(directory):
    from jobdisco import ledger_guard
    data, source = fixture(directory)
    local = directory / 'code/.local'
    local.mkdir(parents=True)
    for name in ('jsearch_usage.sqlite', 'source_access.sqlite'):
        shutil.copyfile(data / 'operational' / name, local / name)
    pause(collection_policy.SourcePolicy(source, 1, path=data / 'operational/source_access.sqlite'))
    script = (ROOT / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')
    start = script.index('for name in source_access.sqlite jsearch_usage.sqlite; do',
                         script.index("echo '== Pull the data repository =='"))
    end = script.index('\n# "Present and non-empty"', start)
    seed = script[start:end]
    result = shell(directory, 'set -euo pipefail\nCODE=' + shlex.quote((directory / 'code').as_posix())
                   + '\nDATA=' + shlex.quote(data.as_posix()) + '\n' + seed)
    check(result)
    assert ledger_guard.compare(local / 'jsearch_usage.sqlite',
                                data / 'operational/jsearch_usage.sqlite')[2]
    assert blocked(collection_policy.SourcePolicy(source, 1, path=data / 'operational/source_access.sqlite'))
    assert not blocked(collection_policy.SourcePolicy(source, 1, path=local / 'source_access.sqlite'))
    # Execute the exact publication copy loop; it overwrites the newer pause.
    start = script.index('  for name in source_access.sqlite jsearch_usage.sqlite; do')
    end = script.index('\n  cd "$DATA"', start)
    check(shell(directory, 'set -euo pipefail\nCODE=' + shlex.quote((directory / 'code').as_posix())
                + '\nDATA=' + shlex.quote(data.as_posix()) + '\n' + script[start:end]))
    assert not blocked(collection_policy.SourcePolicy(source, 1, path=data / 'operational/source_access.sqlite'))
    print('B73: published cooldown ignored on startup, credit comparison passes, publication erases pause')


if __name__ == '__main__':
    for case in (b68, b69, b70, b71, b72, b73):
        with tempfile.TemporaryDirectory(prefix='jobdisco-audit13-') as temporary:
            case(Path(temporary))
