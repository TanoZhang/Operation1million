"""Run the workstation backup against a synthetic SSH tar stream."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
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
        for failure in ('missing-ledger', 'bad-snapshot', 'mismatched-manifest',
                        'corrupt-run-file'):
            with self.subTest(failure=failure):
                result, backup = self.run_backup(failure)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in ('current', 'previous'):
                    self.assertEqual((backup / name / 'keep.txt').read_text(), name)
                self.assertEqual((backup / 'last-pull').read_text(), 'last good pull')

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
