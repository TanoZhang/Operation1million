"""How the scanner names questions and sections, #227-229 (2026-10-02).

Runs tests/autofill-scanner.cjs, the actual extension scripts against
fictional forms, under Node and jsdom; skipped where they are not installed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

CASES = ('the_heading_before_a_field_is_its_section', 'a_radio_group_is_named_by_its_question',
         'a_lever_radio_question', 'a_radio_group_with_no_question_text_is_left_alone',
         'boxes_without_a_legend_are_not_repeated_rows', 'untitled_rows_with_the_same_questions_still_are')


class AutofillScannerTests(unittest.TestCase):
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
        result = subprocess.run([self.node, str(ROOT / 'tests/autofill-scanner.cjs'), name],
                                cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def make_test(name):
    def test(self):
        self.run_case(name)
    return test


for case in CASES:
    setattr(AutofillScannerTests, 'test_' + case, make_test(case))


if __name__ == '__main__':
    unittest.main()
