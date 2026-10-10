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

from operation1million import collector, jsearch

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


class UnpublishedProgressTests(unittest.TestCase):
    """B67: a failed publication rewinds the ledger the next pass will read.

    The branch runs only when the collected history fails verification, and no
    test here drives the pass script that far; so the wiring is checked as
    source, and the rewind itself against real ledgers.
    """

    def test_the_recovery_branch_rewinds_the_runtime_ledger_as_well(self):
        script = (ROOT / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')
        branch = script.split("publishing charges without unpublished cursors.")[1]
        branch = branch.split('\n  fi\n')[0]
        self.assertIn('workflow_state "$CODE/.local/jsearch_usage.sqlite"', branch)
        self.assertIn('workflow_state operational/jsearch_usage.sqlite', branch)

    def test_the_offline_tests_run_without_the_production_environment(self):
        # With OPERATION1MILLION_STORE exported they read the production resume
        # profile: 61 failures and 5 errors on the VPS, 2026-10-09.
        script = (ROOT / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')
        step = script.split("echo '== Offline regression tests =='")[1].split("echo '== Database =='")[0]
        command = step[step.index('env -i'):step.index('unittest discover')]
        self.assertNotIn('OPERATION1MILLION', command)
        self.assertNotIn('JSEARCH', command)

    def test_a_rewind_keeps_the_credits_and_restores_the_cursor(self):
        from operation1million.jsearch_access import RequestGuard
        from operation1million.workflow_state import restore_cursors
        with tempfile.TemporaryDirectory() as folder:
            before, runtime = Path(folder) / 'before.sqlite', Path(folder) / 'runtime.sqlite'
            RequestGuard(path=before).advance('q', 2, period='2026-09-16')
            guard = RequestGuard(path=runtime)
            guard.advance('q', 9, exhausted=True, period='2026-09-16')
            guard.baseline(1)
            restore_cursors(runtime, before)
            self.assertEqual(guard.resume_page('q', period='2026-09-16'), (2, False))
            self.assertEqual(guard.balance()['period_used'], 1)


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
                              env={**os.environ, 'OPERATION1MILLION_ROOT': str(self.root)})

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

    def test_the_company_links_go_out_with_the_ledger(self):
        """The review page keeps them beside the ledger (2026-10-02)."""
        links = self.data / 'operational/listing_links.ndjson'
        links.write_text('{"url":"u","link":"https://example.test/j","at":"t"}\n', encoding='utf-8')
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = subprocess.run(
            ['git', 'show', 'main:operational/listing_links.ndjson'],
            cwd=str(self.remote), capture_output=True, text=True)
        self.assertIn('example.test/j', stored.stdout)

    def test_manual_jobs_are_backed_up_without_waiting_for_collection(self):
        manual = self.data / 'operational/manual_jobs.ndjson'
        manual.write_text('{"group":{"id":"manual-fixture"}}\n', encoding='utf-8')
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = self.run_git(['show', 'main:operational/manual_jobs.ndjson'], cwd=self.remote)
        self.assertIn('manual-fixture', stored.stdout)

    def test_an_unchanged_ledger_produces_no_commit(self):
        self.ledger().write_text('{"url":"u","at":"t","status":"skipped"}\n', encoding='utf-8')
        self.backup()
        before = len(self.commits())
        self.assertEqual(self.backup().returncode, 0)
        self.assertEqual(len(self.commits()), before, 'an empty commit was made')

    def test_a_failed_push_is_retried_on_the_next_tick(self):
        """The failure this exists for must not wait for the next decision.

        A push that cannot reach GitHub leaves the ledger on one disk, and the
        push used to run only when a new decision had just been committed. No
        decision may be made for days, and the disk is what is being insured
        against.
        """
        self.ledger().write_text('{"url":"u","at":"t","status":"skipped"}\n', encoding='utf-8')
        self.run_git(['remote', 'set-url', 'origin', str(self.root / 'absent.git')], cwd=self.data)
        failed = self.backup()
        self.assertEqual(failed.returncode, 1, 'an unreachable remote must be loud')
        self.assertEqual(len(self.commits()), 1, 'nothing can have reached the remote')
        self.run_git(['remote', 'set-url', 'origin', str(self.remote)], cwd=self.data)
        retried = self.backup()
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(len(self.commits()), 2, 'the commit never reached the remote')
        stored = subprocess.run(['git', 'show', 'main:operational/applications.ndjson'],
                                cwd=str(self.remote), capture_output=True, text=True)
        self.assertIn('skipped', stored.stdout)

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

    def other_writer(self, path, text):
        """Another machine pushes to the data repository (2026-10-03: muse
        records applications from the user's laptop while this box backs up)."""
        other = self.root / 'other'
        if not other.exists():
            self.run_git(['clone', '--quiet', str(self.remote), str(other)], cwd=self.root)
            for name, value in (('user.name', 'other'), ('user.email', 'other@example.test')):
                self.run_git(['config', name, value], cwd=other)
        self.run_git(['pull', '--quiet', '--rebase', 'origin', 'main'], cwd=other)
        target = other / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a', encoding='utf-8') as handle:
            handle.write(text)
        self.run_git(['add', '-A'], cwd=other)
        self.run_git(['commit', '--quiet', '-m', 'other writer'], cwd=other)
        self.run_git(['push', '--quiet', 'origin', 'HEAD:main'], cwd=other)

    def remote_file(self, path):
        return subprocess.run(['git', 'show', f'main:{path}'], cwd=str(self.remote),
                              capture_output=True, text=True).stdout

    def test_a_remote_that_moved_on_is_merged_before_the_push(self):
        """Reported 2026-10-03: the push was refused, the two sides diverged, and
        the next deploy and the next pass both stopped on a fast-forward."""
        self.other_writer('job-applications/history.jsonl', '{"n":1}\n')
        self.ledger().write_text('{"url":"u","at":"t","status":"applied"}\n', encoding='utf-8')
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('applied', self.remote_file('operational/applications.ndjson'))
        self.assertIn('"n":1', self.remote_file('job-applications/history.jsonl'))

    def test_both_sides_appending_to_the_ledger_keep_every_line(self):
        self.ledger().write_text('{"url":"a","at":"1","status":"applied"}\n', encoding='utf-8')
        self.assertEqual(self.backup().returncode, 0)
        self.other_writer('operational/applications.ndjson', '{"url":"b","at":"2","status":"skipped"}\n')
        with self.ledger().open('a', encoding='utf-8') as handle:
            handle.write('{"url":"c","at":"3","status":"applied"}\n')
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        stored = self.remote_file('operational/applications.ndjson')
        for url in ('"a"', '"b"', '"c"'):
            self.assertIn(url, stored)
        self.assertNotIn('<<<<<<<', stored)

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
        unit = (ROOT / 'deploy/vps/operation1million-backup.timer').read_text(encoding='utf-8')
        self.assertIn('OnUnitActiveSec=15min', unit)

    def test_the_installer_installs_and_enables_it(self):
        installer = (ROOT / 'deploy/vps/install.sh').read_text(encoding='utf-8')
        self.assertIn('operation1million-backup.service', installer)
        self.assertIn('operation1million-backup.timer', installer)
        self.assertRegex(installer, r'systemctl enable --now operation1million-backup\.timer')

    def test_every_git_writer_shares_one_lock(self):
        for name in ('daily-pass.sh', 'compact-history.sh', 'install.sh',
                     'backup-applications.sh'):
            body = (ROOT / 'deploy/vps' / name).read_text(encoding='utf-8')
            with self.subTest(script=name):
                self.assertIn('collection.lock', body)
                self.assertIn('flock -n 9', body)


class DataRepositorySyncWiringTests(unittest.TestCase):
    """Every writer on the box merges what others pushed instead of stopping."""

    def test_no_data_repository_step_insists_on_a_fast_forward(self):
        for name in ('daily-pass.sh', 'install.sh', 'backup-applications.sh'):
            body = (ROOT / 'deploy/vps' / name).read_text(encoding='utf-8')
            with self.subTest(script=name):
                self.assertIn('sync_data', body)
                self.assertNotRegex(body, r'DATA"? pull --ff-only|/data"? merge --ff-only')

    def test_the_pass_merges_before_it_publishes(self):
        script = (ROOT / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')
        publish = script.split('publish_state() {')[1].split('\n}\n')[0]
        self.assertLess(publish.index('sync_data'), publish.index('git push origin main'))


class DailyPassKeepsGoingTests(unittest.TestCase):
    """The user's rule (2026-10-03): the daily pass runs every day, paid search
    included. A failing test stopped the whole pass that morning."""

    def script(self):
        return (ROOT / 'deploy/vps/daily-pass.sh').read_text(encoding='utf-8')

    def test_a_failing_suite_is_reported_and_the_pass_carries_on(self):
        self.assertIn("python -m unittest discover -s tests || note_problem", self.script())

    def test_paid_search_is_never_switched_off(self):
        script = self.script()
        body = script.split('collect_started=1')[1].split('collect_code=$?')[0]
        self.assertIn('--jsearch\n', body)
        self.assertNotIn('job-collect --workers 3 --delay 1.0\n', body)
        self.assertNotIn('paid=0', script)

    def test_a_ledger_behind_is_restored_as_the_guard_advises(self):
        body = self.script().split('if ! python -m operation1million.ledger_guard')[1].split('\nfi\n')[0]
        self.assertIn('cp "$DATA/operational/jsearch_usage.sqlite" "$CODE/.local/jsearch_usage.sqlite"', body)
        self.assertIn('note_problem', body)

    def test_a_pass_with_a_problem_says_so_and_a_preflight_still_fails(self):
        script = self.script()
        self.assertIn('exit 2', script.split('run_clean=1')[1].split('# EXIT publishes')[0])
        preflight = script.split('if [ "$PREFLIGHT" -eq 1 ]; then')[1].split('\nfi\n')[0]
        self.assertIn('if [ "$problems" -eq 1 ]', preflight)


class LocalRecoveryBackupTests(unittest.TestCase):
    """The remote SQLite snapshot command must survive two shell parsers."""

    def test_snapshot_python_is_valid_and_passed_as_one_argument(self):
        body = (ROOT / 'deploy/local/backup-from-vps.sh').read_text(encoding='utf-8')
        helper = ROOT / 'deploy/vps/backup-snapshot.py'
        compile(helper.read_text(encoding='utf-8'), str(helper), 'exec')
        self.assertIn('$(remote_quote "$REMOTE_STATE")', body)
        self.assertIn('< "$SCRIPT_DIR/../vps/backup-snapshot.py"', body)


class PassStatisticsTests(unittest.TestCase):
    """A6: the six numbers that have to add up."""

    def test_the_collector_reports_the_seen_split(self):
        source = (ROOT / 'src/operation1million/collector.py').read_text(encoding='utf-8')
        for field in ('seen_fetched', 'seen_new', 'seen_existing',
                      'seen_accepted', 'seen_rejected', 'seen_malformed'):
            self.assertIn(field, source)

    def test_fetched_splits_into_new_and_existing(self):
        """Counted from the table, because an upsert cannot report the split.

        By listing address since 2026-09-27: JSearch's job_id changes for the
        same listing, and the row count called every record new
        (`store.count_new_listings`, tests/test_jsearch_plan_bugs.py)."""
        source = (ROOT / 'src/operation1million/collector.py').read_text(encoding='utf-8')
        self.assertIn("seen_totals['fetched'] += len(rows)", source)
        self.assertIn("added, existing = store.count_new_listings(db, rows)", source)
        self.assertIn("seen_totals['new_seen'] += added", source)
        self.assertIn("seen_totals['existing_seen'] += existing", source)

    def test_summary_reads_accepted_from_pass_facts(self):
        report = collector.summary_block(
            {'jsearch_jobs_accepted': 0}, {'jsearch_jobs_accepted': 17}, {})
        self.assertRegex(report, r'accepted\s+17\b')


if __name__ == '__main__':
    unittest.main()
