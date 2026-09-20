"""Run the workstation backup against a synthetic SSH tar stream."""
from pathlib import Path
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

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
        for name in ('applications.ndjson', 'jsearch_usage.sqlite',
                     'source_access.sqlite', 'seen_jobs.ndjson.gz'):
            (data / 'operational' / name).write_bytes(b'synthetic state')
        (data / 'runs/2026-09-20.ndjson.gz').write_bytes(b'fixture')
        manifest = '2026-09-19' if failure == 'mismatched-manifest' else '2026-09-20'
        (data / 'manifests' / (manifest + '.json')).write_text('{}', encoding='utf-8')
        snapshot = root / 'fixture/sqlite/job_discovery.sqlite'
        snapshot.parent.mkdir()
        with sqlite3.connect(snapshot) as db:
            db.execute('CREATE TABLE jobs (closed_at TEXT)')
        if failure == 'missing-ledger':
            (data / 'operational/jsearch_usage.sqlite').unlink()
        if failure == 'bad-snapshot':
            snapshot.write_bytes(b'not a SQLite snapshot')
        backup = root / 'backup'
        for name in ('current', 'previous'):
            (backup / name).mkdir(parents=True)
            (backup / name / 'keep.txt').write_text(name, encoding='utf-8')
        (backup / 'last-pull').write_text('last good pull', encoding='utf-8')
        driver = root / 'driver.sh'
        driver.write_text(
            "ssh() { tar czf - -C fixture data sqlite; }\n"
            + 'source ' + shlex.quote((ROOT / 'deploy/local/backup-from-vps.sh').as_posix())
            + ' backup\n', encoding='utf-8', newline='\n')
        result = subprocess.run([BASH, 'driver.sh'], cwd=root, capture_output=True, text=True,
                                env={**os.environ, 'JOBDISCO_VPS_DATA': '/unused/data',
                                     'JOBDISCO_PYTHON': Path(sys.executable).as_posix()})
        return result, backup

    def test_invalid_copies_preserve_both_recovery_generations(self):
        for failure in ('missing-ledger', 'bad-snapshot', 'mismatched-manifest'):
            with self.subTest(failure=failure):
                result, backup = self.run_backup(failure)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in ('current', 'previous'):
                    self.assertEqual((backup / name / 'keep.txt').read_text(), name)
                self.assertEqual((backup / 'last-pull').read_text(), 'last good pull')

    def test_valid_copy_rotates_only_after_validation(self):
        result, backup = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((backup / 'previous/keep.txt').read_text(), 'current')
        self.assertTrue((backup / 'current/sqlite/job_discovery.sqlite').is_file())
