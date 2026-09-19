"""Regressions for the five pre-launch fixes.

Each of these was measured on the live queue before it was changed, so the
numbers in the docstrings are observations rather than illustrations.
"""
from pathlib import Path
import os
import re
import subprocess
import shutil
import tempfile
import unittest

from jobdisco import jsearch

ROOT = Path(__file__).resolve().parents[1]


class HardRejectTests(unittest.TestCase):
    """A2: functions that are not the trade, promoted out of the soft list.

    A soft reject is consulted only when confidence falls below
    min_confidence, and a sales or technician posting at a semiconductor
    company is written in the trade's vocabulary, so it cleared the threshold
    and the soft reject never fired. 423 sales, 151 marketing and 633
    technician postings were in the live queue because of it.
    """

    def setUp(self):
        self.rules = jsearch.load_plan()[0]['filter']

    def test_sales_marketing_and_technician_are_hard_rejects(self):
        for title in ('Technical Sales Engineer', 'Sales Engineer, EDA Tools',
                      'Product Marketing Manager, Silicon',
                      'Data Center Technician', 'Engineering Operation Technician'):
            with self.subTest(title=title):
                self.assertTrue(jsearch.excluded(title, self.rules))

    def test_a_hard_reject_outranks_a_keep_pattern(self):
        """The point of promoting them: no score and no keyword can save them."""
        self.assertTrue(jsearch.excluded('RTL Verification Technician', self.rules))
        self.assertTrue(jsearch.excluded('FPGA Sales Engineer', self.rules))

    def test_analog_and_software_were_deliberately_left_alone(self):
        for title in ('Analog IC Design Engineer', 'Analog Mixed-Signal Design Engineer',
                      'Software Engineer, Post Silicon Validation',
                      'Software Development Engineer, Silicon'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))

    def test_the_promoted_terms_are_no_longer_duplicated_in_the_soft_list(self):
        soft = ' '.join(self.rules['reject_title_patterns'])
        for term in ('sales', 'marketing', 'technician'):
            self.assertNotIn(term, soft)

    def test_the_target_roles_still_pass(self):
        for title in ('RTL Design Engineer', 'Design Verification Engineer',
                      'DFT Engineer', 'Physical Design Engineer', 'FPGA Engineer'):
            with self.subTest(title=title):
                self.assertFalse(jsearch.excluded(title, self.rules))


@unittest.skipUnless(shutil.which('bash') and shutil.which('git') and shutil.which('flock'),
                     'bash, git and flock are required; Windows has no flock')
class ApplicationsBackupTests(unittest.TestCase):
    """A3: the ledger reaches GitHub every fifteen minutes, not once a day."""

    SCRIPT = ROOT / 'deploy/vps/backup-applications.sh'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root / 'remote.git'
        self.data = self.root / 'data'
        self.run_git(['init', '--quiet', '--bare', str(self.remote)], cwd=self.root)
        self.run_git(['clone', '--quiet', str(self.remote), str(self.data)], cwd=self.root)
        for name, value in (('user.name', 'test'), ('user.email', 'test@example.test')):
            self.run_git(['config', name, value], cwd=self.data)
        (self.data / 'operational').mkdir()
        (self.data / 'README').write_text('x', encoding='utf-8')
        self.run_git(['add', '-A'], cwd=self.data)
        self.run_git(['commit', '--quiet', '-m', 'init'], cwd=self.data)
        self.run_git(['push', '--quiet', 'origin', 'HEAD:refs/heads/main'], cwd=self.data)
        self.run_git(['branch', '-M', 'main'], cwd=self.data)
        self.run_git(['branch', '--set-upstream-to=origin/main', 'main'], cwd=self.data)

    def run_git(self, args, cwd):
        return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True,
                              text=True, check=True)

    def backup(self):
        return subprocess.run(['bash', str(self.SCRIPT)], capture_output=True, text=True,
                              env={**os.environ, 'JOBDISCO_ROOT': str(self.root)})

    def ledger(self):
        return self.data / 'operational/applications.ndjson'

    def commits(self):
        out = subprocess.run(['git', 'log', '--oneline', 'main'], cwd=str(self.remote),
                             capture_output=True, text=True).stdout
        return [line for line in out.splitlines() if line.strip()]

    def test_a_decision_reaches_the_remote_without_waiting_for_a_pass(self):
        self.ledger().write_text('{"url":"u","at":"t","status":"skipped"}\n', encoding='utf-8')
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commits()), 2)
        stored = subprocess.run(
            ['git', 'show', 'main:operational/applications.ndjson'],
            cwd=str(self.remote), capture_output=True, text=True)
        self.assertIn('skipped', stored.stdout)

    def test_an_unchanged_ledger_produces_no_commit(self):
        self.ledger().write_text('{"url":"u","at":"t","status":"skipped"}\n', encoding='utf-8')
        self.backup()
        before = len(self.commits())
        self.assertEqual(self.backup().returncode, 0)
        self.assertEqual(len(self.commits()), before, 'an empty commit was made')

    def test_a_missing_ledger_is_not_an_error(self):
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.commits()), 1)

    def test_it_stands_aside_while_a_pass_holds_the_lock(self):
        self.ledger().write_text('{"url":"u","at":"t","status":"skipped"}\n', encoding='utf-8')
        holder = subprocess.Popen(
            ['bash', '-c', f'exec 9>"{self.root}/collection.lock"; flock 9; sleep 20'])
        try:
            deadline = __import__('time').monotonic() + 10
            while __import__('time').monotonic() < deadline:
                if (self.root / 'collection.lock').exists():
                    break
                __import__('time').sleep(0.1)
            __import__('time').sleep(0.5)
            result = self.backup()
            self.assertEqual(result.returncode, 0, 'a held lock must not be an error')
            self.assertEqual(len(self.commits()), 1, 'it committed while the lock was held')
        finally:
            holder.kill()
            holder.wait(timeout=10)

    def test_it_never_writes_to_the_ledger_itself(self):
        """A backup that could corrupt what it protects is worse than none."""
        body = '{"url":"u","at":"t","status":"applied"}\n'
        self.ledger().write_text(body, encoding='utf-8')
        self.backup()
        self.assertEqual(self.ledger().read_text(encoding='utf-8'), body)

    def test_a_push_that_fails_says_so_and_leaves_the_commit(self):
        self.ledger().write_text('{"url":"u","at":"t","status":"skipped"}\n', encoding='utf-8')
        self.run_git(['remote', 'set-url', 'origin', str(self.root / 'gone.git')], cwd=self.data)
        result = self.backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('could not be pushed', result.stderr)
        local = subprocess.run(['git', 'log', '--oneline'], cwd=str(self.data),
                               capture_output=True, text=True).stdout
        self.assertIn('Back up application decisions', local)


class BackupWiringTests(unittest.TestCase):
    """The units have to be installed, or they are a file nobody runs."""

    def test_the_timer_runs_every_fifteen_minutes(self):
        unit = (ROOT / 'deploy/vps/jobdisco-backup.timer').read_text(encoding='utf-8')
        self.assertIn('OnUnitActiveSec=15min', unit)

    def test_the_installer_installs_and_enables_it(self):
        installer = (ROOT / 'deploy/vps/install.sh').read_text(encoding='utf-8')
        self.assertIn('jobdisco-backup.service', installer)
        self.assertIn('jobdisco-backup.timer', installer)
        self.assertRegex(installer, r'systemctl enable --now jobdisco-backup\.timer')

    def test_every_git_writer_shares_one_lock(self):
        for name in ('daily-pass.sh', 'compact-history.sh', 'install.sh',
                     'backup-applications.sh'):
            body = (ROOT / 'deploy/vps' / name).read_text(encoding='utf-8')
            with self.subTest(script=name):
                self.assertIn('collection.lock', body)
                self.assertIn('flock -n 9', body)


class PassStatisticsTests(unittest.TestCase):
    """A6: the six numbers that have to add up."""

    def test_the_collector_reports_the_seen_split(self):
        source = (ROOT / 'src/jobdisco/collector.py').read_text(encoding='utf-8')
        for field in ('seen_fetched', 'seen_new', 'seen_existing',
                      'seen_accepted', 'seen_rejected', 'seen_malformed'):
            self.assertIn(field, source)

    def test_fetched_splits_into_new_and_existing(self):
        """Counted from the table, because an upsert cannot report the split."""
        source = (ROOT / 'src/jobdisco/collector.py').read_text(encoding='utf-8')
        self.assertIn("seen_totals['fetched'] += len(rows)", source)
        self.assertIn("seen_totals['new_seen'] += added", source)
        self.assertIn("seen_totals['existing_seen'] += len(rows) - added", source)


if __name__ == '__main__':
    unittest.main()
