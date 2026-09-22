"""Run the workstation backup against a synthetic SSH tar stream."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import gzip
import importlib.util
import io
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tarfile
import unittest
from types import SimpleNamespace

from jobdisco.jsearch_access import RequestGuard
from jobdisco.collection_policy import SourcePolicy

ROOT = Path(__file__).resolve().parents[1]
BASH = (str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe')
        if os.name == 'nt' else shutil.which('bash'))


@unittest.skipUnless(BASH and Path(BASH).is_file(), 'Bash required for backup regression')
class BackupTests(unittest.TestCase):
    def run_backup(self, failure=None):
        temporary = tempfile.TemporaryDirectory(prefix='jobdisco-backup-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        data = root / 'fixture/data'
        for folder in ('runs', 'manifests', 'operational'):
            (data / folder).mkdir(parents=True)
        (data / 'operational/applications.ndjson').write_text(
            '{"url":"https://example.test/A","at":"2026-01-01T00:00:00Z","status":"applied"}\n', encoding='utf-8')
        RequestGuard(path=data / 'operational/jsearch_usage.sqlite')
        SourcePolicy(SimpleNamespace(company_key='fixture'), 1,
                     path=data / 'operational/source_access.sqlite').check()
        (data / 'operational/seen_jobs.ndjson.gz').write_bytes(gzip.compress(b''))
        # Days are computed, never written down. The digest check exempts the
        # day still being written, so a literal date here would exercise one
        # branch today and the other one tomorrow.
        def stamp(days_ago):
            return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%d')

        def day_file(day, content, digest_of=None):
            (data / 'runs' / (day + '.ndjson.gz')).write_bytes(content)
            (data / 'manifests' / (day + '.json')).write_text(json.dumps({
                'run_date': day, 'file': f'runs/{day}.ndjson.gz',
                'sha256': hashlib.sha256(digest_of if digest_of is not None
                                         else content).hexdigest()}), encoding='utf-8')

        sealed = stamp(1)
        if failure == 'mismatched-manifest':
            # A manifest for a day whose run file is not in the copy.
            (data / 'runs' / (sealed + '.ndjson.gz')).write_bytes(b'fixture')
            day_file(stamp(2), b'', digest_of=b'')
            (data / 'runs' / (stamp(2) + '.ndjson.gz')).unlink()
        elif failure == 'corrupt-run-file':
            # What the manifest describes and what the copy holds differ, which
            # is what a truncated or damaged transfer looks like.
            day_file(sealed, b'truncated on the way', digest_of=b'fixture')
        else:
            day_file(sealed, b'fixture')
        if failure == 'today-still-writing':
            # A pass may be appending to today's file while tar reads it.
            day_file(stamp(0), b'a pass is still appending to this',
                     digest_of=b'what the manifest said an hour ago')
        snapshot = root / 'fixture/sqlite/job_discovery.sqlite'
        snapshot.parent.mkdir()
        # `with sqlite3.connect(...)` commits the transaction; it does not
        # close the connection. The open handle left the fixture's temporary
        # directory undeletable on Windows, where the whole suite then errored
        # in cleanup while passing on Linux.
        with closing(sqlite3.connect(snapshot)) as db, db:
            db.execute('CREATE TABLE jobs (closed_at TEXT)')
        if failure == 'missing-ledger':
            (data / 'operational/jsearch_usage.sqlite').unlink()
        if failure == 'bad-snapshot':
            snapshot.write_bytes(b'not a SQLite snapshot')
        if failure and failure.startswith('corrupt-') and failure != 'corrupt-run-file':
            (data / 'operational' / failure.removeprefix('corrupt-')).write_bytes(b'broken nonempty state')
        if failure == 'empty-decisions':
            (data / 'operational/applications.ndjson').write_bytes(b'')
        backup = root / 'backup'
        for name in ('current', 'previous'):
            (backup / name).mkdir(parents=True)
            (backup / name / 'keep.txt').write_text(name, encoding='utf-8')
        (backup / 'last-pull').write_text('last good pull', encoding='utf-8')
        driver = root / 'driver.sh'
        driver.write_text(
            "ssh() { tar czf - -C fixture data sqlite; }\n"
            + ('''mv() {
  if [ "$1" = 'backup/.incoming/data' ]; then return 73; fi
  command mv "$@"
}
''' if failure == 'rotation' else '')
            + 'source ' + shlex.quote((ROOT / 'deploy/local/backup-from-vps.sh').as_posix())
            + ' backup\n', encoding='utf-8', newline='\n')
        result = subprocess.run([BASH, 'driver.sh'], cwd=root, capture_output=True, text=True,
                                env={**os.environ, 'JOBDISCO_VPS_DATA': '/unused/data',
                                     'JOBDISCO_PYTHON': Path(sys.executable).as_posix()})
        return result, backup

    def test_invalid_copies_preserve_both_recovery_generations(self):
        for failure in ('missing-ledger', 'bad-snapshot', 'mismatched-manifest',
                        'corrupt-run-file', 'corrupt-applications.ndjson',
                        'corrupt-jsearch_usage.sqlite', 'corrupt-source_access.sqlite',
                        'corrupt-seen_jobs.ndjson.gz'):
            with self.subTest(failure=failure):
                result, backup = self.run_backup(failure)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in ('current', 'previous'):
                    self.assertEqual((backup / name / 'keep.txt').read_text(), name)
                self.assertEqual((backup / 'last-pull').read_text(), 'last good pull')

    def test_rotation_failure_and_retry_preserve_installed_generations(self):
        result, backup = self.run_backup('rotation')
        self.assertNotEqual(result.returncode, 0)
        # Retry the exact failed transfer, not a fresh fixture.
        retried = subprocess.run([BASH, 'driver.sh'], cwd=backup.parent, capture_output=True,
                                 env={**os.environ, 'JOBDISCO_VPS_DATA': '/unused/data',
                                      'JOBDISCO_PYTHON': Path(sys.executable).as_posix()})
        self.assertNotEqual(retried.returncode, 0)
        for name in ('current', 'previous'):
            self.assertEqual((backup / name / 'keep.txt').read_text(), name)
        self.assertEqual((backup / 'last-pull').read_text(), 'last good pull')

    def test_no_decisions_yet_is_a_valid_ledger(self):
        result, _ = self.run_backup('empty-decisions')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_interrupted_rotation_is_recovered_before_another_bad_transfer(self):
        result, backup = self.run_backup('bad-snapshot')
        self.assertNotEqual(result.returncode, 0)
        (backup / 'current').rename(backup / 'previous.tmp')
        retried = subprocess.run([BASH, 'driver.sh'], cwd=backup.parent, capture_output=True,
                                 env={**os.environ, 'JOBDISCO_VPS_DATA': '/unused/data',
                                      'JOBDISCO_PYTHON': Path(sys.executable).as_posix()})
        self.assertNotEqual(retried.returncode, 0)
        for name in ('current', 'previous'):
            self.assertEqual((backup / name / 'keep.txt').read_text(), name)
        self.assertEqual((backup / 'last-pull').read_text(), 'last good pull')

    def test_archive_reads_runtime_quota_including_its_wal(self):
        spec = importlib.util.spec_from_file_location('backup_snapshot', ROOT / 'deploy/vps/backup-snapshot.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, runtime = root / 'data', root / 'code/.local'
            (data / 'operational').mkdir(parents=True)
            runtime.mkdir(parents=True)
            (data / 'operational/applications.ndjson').write_bytes(b'')
            index = root / 'jobs.sqlite'
            with closing(sqlite3.connect(index)) as db, db:
                db.execute('CREATE TABLE jobs (url TEXT)')
            published = RequestGuard(path=data / 'operational/jsearch_usage.sqlite')
            live = RequestGuard(path=runtime / 'jsearch_usage.sqlite')
            policy = SourcePolicy(SimpleNamespace(company_key='fixture'), 1,
                                  path=runtime / 'source_access.sqlite')
            policy.check()
            with closing(sqlite3.connect(live.path)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('BEGIN')
                writer.execute('SELECT * FROM credit_usage').fetchall()
                live.get(SimpleNamespace(get=lambda *a, **kw: SimpleNamespace(status_code=200, headers={})),
                         'https://example.test/mock')
                self.assertTrue(Path(str(live.path) + '-wal').exists())
                output = io.BytesIO()
                module.archive(data, index, runtime, output)
            self.assertEqual(published.balance()['period_used'], 0)
            with tarfile.open(fileobj=io.BytesIO(output.getvalue()), mode='r:gz') as archive:
                copied = root / 'copied.sqlite'
                copied.write_bytes(archive.extractfile('data/operational/jsearch_usage.sqlite').read())
            self.assertEqual(RequestGuard(path=copied).balance()['period_used'], 1)

    @unittest.skipIf(os.name == 'nt' or os.geteuid() == 0, 'needs a POSIX user a mode bit can refuse')
    def test_a_lock_file_the_backup_user_cannot_write_is_still_honoured(self):
        """Measured on the VPS before deploying: the SSH user cannot write the
        service account's `applications.lock`, and opening it for append
        failed every archive with Permission denied."""
        import fcntl
        spec = importlib.util.spec_from_file_location('backup_snapshot', ROOT / 'deploy/vps/backup-snapshot.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / 'applications.ndjson'
            lock = ledger.with_suffix('.lock')
            lock.write_bytes(b'')
            lock.chmod(0o444)
            with open(lock, 'rb') as other:
                fcntl.flock(other.fileno(), fcntl.LOCK_EX)
                held = True
                try:
                    with open(lock, 'rb') as probe:
                        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = False
                except BlockingIOError:
                    pass
                self.assertTrue(held, 'the fixture lock does not exclude')
            with module.decision_lock(ledger):
                with open(lock, 'rb') as probe, self.assertRaises(BlockingIOError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_the_day_still_being_written_may_differ_from_its_manifest(self):
        """A pass appending while tar reads is a race, not a damaged copy.

        The manifest is rewritten when the pass finishes, so today's digest is
        not final. Failing on it would make every pull that overlaps a pass
        look like corruption.
        """
        result, backup = self.run_backup('today-still-writing')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('still being written', result.stdout)

    def test_valid_copy_rotates_only_after_validation(self):
        result, backup = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((backup / 'previous/keep.txt').read_text(), 'current')
        self.assertTrue((backup / 'current/sqlite/job_discovery.sqlite').is_file())
        # Structure is not enough: an unverified copy that rotates twice
        # replaces both intact generations.
        self.assertIn('1 run files verified against their manifests', result.stdout)
