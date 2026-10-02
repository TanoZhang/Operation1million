"""Offline integration tests for ATS and answer-assessment modules."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

CASES = ('known_answer', 'unknown_and_missing', 'scope_and_ambiguity',
         'degree_major_and_school_aliases', 'sponsorship_context', 'ats_detection_and_label',
         'custom_dropdown', 'searchable_dropdown', 'dropdown_failure_preserves_value',
         'initialize_preserves_answers', 'basic_question_editor',
         'seed_import_preserves_learned_mapping', 'confirm_unknown_meaning', 'review_policy_switch',
         'repeated_education_identity')


class AutofillFrameworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('Node is needed for offline extension DOM tests')
        cls.env = dict(os.environ)
        cls.env['NODE_PATH'] = os.pathsep.join(filter(None, [
            str(ROOT / '.local/audit-node/node_modules'), cls.env.get('NODE_PATH')]))
        probe = subprocess.run([cls.node, '-e', "require('jsdom')"], env=cls.env,
                               capture_output=True, text=True, timeout=30)
        if probe.returncode:
            raise unittest.SkipTest('Install jsdom@22.1.0 under .local/audit-node for DOM tests')

    def run_case(self, name):
        result = subprocess.run([self.node, str(ROOT / 'tests/autofill-framework.cjs'), name],
                                cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def make_test(name):
    def test(self):
        self.run_case(name)
    return test


for case in CASES:
    setattr(AutofillFrameworkTests, 'test_' + case, make_test(case))


if __name__ == '__main__':
    unittest.main()
