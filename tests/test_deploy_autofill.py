"""Exercise deployment's new-file allowlist in an isolated Git repository."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeployAutofillTests(unittest.TestCase):
    def test_staging_includes_new_extension_code_and_excludes_private_answers(self):
        if not shutil.which('git'):
            self.skipTest('Git is required')
        script = (ROOT / 'deploy/local/deploy-vps.bat').read_text()
        paths = next(line.split('=', 1)[1].split() for line in script.splitlines()
                     if line.startswith('set NEW_PATHS='))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            git('init', '-q')
            directories = {'src', 'tests', 'docs', 'data/config', 'deploy', 'application-autofill'}
            for item in paths:
                target = root / item
                if item in directories:
                    target.mkdir(parents=True, exist_ok=True)
                    (target / 'fixture.txt').write_text('fixture\n')
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('fixture\n')
            (root / '.gitignore').write_text((ROOT / '.gitignore').read_text())
            (root / '.gitattributes').write_text((ROOT / '.gitattributes').read_text())
            files = {'application-autofill/extension/portable-memory.js': 'code\n',
                     'application-autofill/data-files.py': 'code\n',
                     'application-autofill/schema/memory.schema.json': '{}\n',
                     'application-autofill/extension/local-profile.json': '{}\n',
                     '.local/autofill/data/profile.json': '{}\n'}
            for name, value in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(value)
            git('add', '-u')
            git('add', '--', *paths)
            staged = set(git('diff', '--cached', '--name-only').splitlines())
            for name in list(files)[:3]:
                self.assertIn(name, staged)
            for name in list(files)[3:]:
                self.assertNotIn(name, staged)

    def test_autofill_and_documentation_have_explicit_lf_endings(self):
        result = subprocess.run(['git', 'check-attr', 'eol', '--',
                                 'application-autofill/extension/profile.js', 'docs/handoff.md'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(line.endswith(': lf') for line in result.stdout.splitlines()), result.stdout)
