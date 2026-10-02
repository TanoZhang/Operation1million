"""Run the real extension in an offline DOM, without private profiles or Chrome.

Optional test runtime: npm install --prefix .local/audit-node --no-package-lock
--no-audit --no-fund jsdom@22.1.0. Node and jsdom are not VPS requirements.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CASES = ('hidden_ancestor', 'disabled_fieldset', 'radio_form_scope', 'unnamed_radios',
         'disabled_optgroup', 'select_mismatch_atomic', 'duplicate_option_labels',
         'changed_control', 'query_position_identity', 'reuse_existing_unknown',
         'ordinary_fill_preserves_values', 'stale_page_and_options')


class AutofillRuntimeTests(unittest.TestCase):
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
        result = subprocess.run([self.node, str(ROOT / 'tests/autofill-runtime.cjs'), name],
                                cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def make_test(name):
    def test(self):
        self.run_case(name)
    return test


for case in CASES:
    setattr(AutofillRuntimeTests, 'test_' + case, make_test(case))


if __name__ == '__main__':
    unittest.main()
