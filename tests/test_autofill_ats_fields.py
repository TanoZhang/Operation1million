"""Provider field ids and autocomplete tokens as exact aliases (2026-10-02).

Runs tests/autofill-ats-fields.cjs, the actual extension scripts against
fictional forms, under Node and jsdom; skipped where they are not installed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

CASES = ('lever_required_marker', 'required_and_optional_words', 'workday_form_kit_paths', 'workday_automation_ids', 'a_wrapper_holding_two_inputs_names_neither',
         'greenhouse_application_fields', 'lever_and_ashby_full_name', 'autocomplete_tokens',
         'other_peoples_sections_stay_guarded', 'a_label_that_disagrees_is_ambiguous')


class AutofillFieldIdentityTests(unittest.TestCase):
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
        result = subprocess.run([self.node, str(ROOT / 'tests/autofill-ats-fields.cjs'), name],
                                cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def make_test(name):
    def test(self):
        self.run_case(name)
    return test


for case in CASES:
    setattr(AutofillFieldIdentityTests, 'test_' + case, make_test(case))


if __name__ == '__main__':
    unittest.main()
