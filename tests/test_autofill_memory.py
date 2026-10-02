"""Portable answer memory and settings integration, using fictional data."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AutofillMemoryTests(unittest.TestCase):
    def test_memory_round_trip_conflicts_history_and_continuous_file(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for extension memory tests')
        env = dict(os.environ)
        env['NODE_PATH'] = os.pathsep.join(filter(None, [
            str(ROOT / '.local/audit-node/node_modules'), env.get('NODE_PATH')]))
        probe = subprocess.run([node, '-e', "require('jsdom')"], env=env, capture_output=True, timeout=30)
        if probe.returncode:
            self.skipTest('jsdom is required for extension memory tests')
        result = subprocess.run([node, str(ROOT / 'tests/autofill-memory.cjs')],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
