"""Exercise compaction against disposable local Git remotes, never GitHub."""
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = str(Path('C:/Program Files/Git/bin/bash.exe')) if os.name == 'nt' else shutil.which('bash')


@unittest.skipUnless(BASH and Path(BASH).is_file(), 'Bash required')
class CompactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='jobdisco-compact-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote, self.data = self.root / 'remote.git', self.root / 'data'
        self.git(self.root, 'init', '--quiet', '--bare', self.remote)
        self.git(self.root, 'clone', '--quiet', self.remote, self.data)
        self.git(self.data, 'config', 'user.name', 'Offline Test')
        self.git(self.data, 'config', 'user.email', 'test@example.test')
        for folder in ('runs', 'manifests', 'operational'):
            (self.data / folder).mkdir()
        for age in (0, 30):
            day = (datetime.now(timezone.utc) - timedelta(days=age)).strftime('%Y-%m-%d')
            body = gzip.compress(b'{}\n')
            (self.data / 'runs' / (day + '.ndjson.gz')).write_bytes(body)
            (self.data / 'manifests' / (day + '.json')).write_text(json.dumps({
                'run_date': day, 'file': f'runs/{day}.ndjson.gz', 'sha256': hashlib.sha256(body).hexdigest()}))
        (self.data / 'operational/applications.ndjson').write_text('{}\n')
        self.git(self.data, 'add', '-A')
        self.git(self.data, 'commit', '--quiet', '-m', 'baseline')
        self.git(self.data, 'branch', '-M', 'main')
        self.git(self.data, 'push', '--quiet', '-u', 'origin', 'main')
        self.git(self.remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        self.before = self.git(self.data, 'rev-parse', 'HEAD').stdout.strip()

    def git(self, cwd, *args, check=True):
        return subprocess.run(['git', *map(str, args)], cwd=cwd, capture_output=True,
                              text=True, check=check)

    def compact(self, extra=''):
        driver = self.root / 'driver.sh'
        driver.write_text('''flock() { return 0; }
python() { "$JOBDISCO_PYTHON" "$@"; }
job-store() { "$JOBDISCO_PYTHON" -c 'from jobdisco import store; assert all(s == "ok" for _, s in store.verify())'; }
''' + extra + '\nsource ' + shlex.quote((ROOT / 'deploy/vps/compact-history.sh').as_posix()),
                          encoding='utf-8', newline='\n')
        return subprocess.run([BASH, 'driver.sh'], cwd=self.root, capture_output=True, text=True,
                              env={**os.environ, 'PYTHONPATH': str(ROOT / 'src'),
                                   'JOBDISCO_ROOT': self.root.as_posix(), 'JOBDISCO_KEEP_DAYS': '1',
                                   'JOBDISCO_PYTHON': Path(sys.executable).as_posix()}, timeout=30)

    def other_commit(self):
        other = self.root / 'other'
        self.git(self.root, 'clone', '--quiet', self.remote, other)
        self.git(other, 'config', 'user.name', 'Offline Test')
        self.git(other, 'config', 'user.email', 'test@example.test')
        (other / 'operational/applications.ndjson').write_text('{"new":"decision"}\n')
        self.git(other, 'add', '-A')
        self.git(other, 'commit', '--quiet', '-m', 'remote decision')
        return other

    def test_unfetched_remote_update_is_not_overwritten(self):
        other = self.other_commit()
        self.git(other, 'push', '--quiet')
        result = self.compact()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Local and remote differ', result.stderr)
        self.assertEqual(self.git(self.data, 'rev-parse', 'HEAD').stdout.strip(), self.before)
        self.assertIn('new', self.git(self.remote, 'show', 'main:operational/applications.ndjson').stdout)

    def test_remote_update_after_fetch_is_protected_by_explicit_lease(self):
        other = self.other_commit()
        result = self.compact('''git() {
  if [ "$1" = push ]; then command git -C ''' + shlex.quote(other.as_posix()) + ''' push --quiet; fi
  command git "$@"
}
''')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(self.data, 'rev-parse', 'HEAD').stdout.strip(), self.before)
        self.assertIn('new', self.git(self.remote, 'show', 'main:operational/applications.ndjson').stdout)

    def test_rejected_push_leaves_original_tree_and_retry_succeeds(self):
        self.git(self.remote, 'config', 'receive.denyNonFastForwards', 'true')
        failed = self.compact()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.git(self.data, 'rev-parse', 'HEAD').stdout.strip(), self.before)
        self.assertEqual(len(list((self.data / 'runs').glob('*.gz'))), 2)
        self.git(self.data, 'pull', '--ff-only')
        self.git(self.remote, 'config', 'receive.denyNonFastForwards', 'false')
        retried = self.compact()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(len(list((self.data / 'runs').glob('*.gz'))), 1)
        self.git(self.data, 'pull', '--ff-only')
        self.assertEqual(self.git(self.data, 'rev-parse', 'HEAD').stdout,
                         self.git(self.remote, 'rev-parse', 'main').stdout)
