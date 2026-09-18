"""Publication failure must retain charges but not unpublished page progress."""
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from jobdisco.jsearch_access import RequestGuard
from jobdisco.workflow_state import restore_cursors


class WorkflowStateTests(unittest.TestCase):
    def test_rejected_history_restores_cursors_but_keeps_charges_and_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / 'usage.sqlite'
            baseline = Path(folder) / 'before.sqlite'
            guard = RequestGuard(ledger)
            guard.advance('existing', 4)
            shutil.copyfile(ledger, baseline)
            guard.advance('existing', 9, exhausted=True)
            guard.advance('new', 2, exhausted=True)
            guard.get(Mock(), 'https://example.test')
            guard.pause(900)
            restore_cursors(ledger, baseline)
            self.assertEqual(guard.resume_page('existing'), (4, False))
            self.assertEqual(guard.resume_page('new'), (1, False))
            self.assertEqual(guard.used(), 1)
            with closing(sqlite3.connect(ledger)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM credit_events').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM account_pause').fetchone()[0], 1)

    def test_first_run_without_a_baseline_discards_only_cursors(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / 'usage.sqlite'
            guard = RequestGuard(ledger)
            guard.advance('new', 8)
            guard.baseline(100)
            restore_cursors(ledger, Path(folder) / 'missing.sqlite')
            self.assertEqual(guard.resume_page('new'), (1, False))
            self.assertEqual(guard.balance()['period_used'], 100)

    def test_manual_sweep_requires_paid_opt_in(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/collect.yml').read_text()
        step = workflow.split('- name: Backfill sweep', 1)[1].split('- name:', 1)[0]
        condition = next(line for line in step.splitlines() if line.strip().startswith('if:'))
        expression = condition.split('${{', 1)[1].split('}}', 1)[0].strip()
        for event in ('schedule', 'workflow_dispatch'):
            for enabled in (False, True):
                for dry in (False, True):
                    evaluated = (expression.replace('steps.sweep_window.outputs.run', "'true'")
                                 .replace('github.event_name', repr(event))
                                 .replace('inputs.enable_jsearch', repr(enabled))
                                 .replace('inputs.dry_run', repr(dry))
                                 .replace('!= true', '!= True')
                                 .replace('&&', 'and').replace('||', 'or'))
                    self.assertEqual(bool(eval(evaluated, {'__builtins__': {}})),
                                     not dry and (event == 'schedule' or enabled))
