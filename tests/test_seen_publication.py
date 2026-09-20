"""Execute the Actions publication body offline with stubbed external commands."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = (str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe')
        if os.name == 'nt' else shutil.which('bash'))


@unittest.skipUnless(BASH and Path(BASH).is_file(), 'Bash required for publication regression')
class SeenPublicationTests(unittest.TestCase):
    def publish(self, *, dry=False, verified=True):
        workflow = (ROOT / '.github/workflows/collect-backup.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Commit durable state\n', 1)[1]
        body = textwrap.dedent(step.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0])
        body = body.replace('${{ inputs.dry_run || false }}', 'true' if dry else 'false')
        # Exercise the real shell branches without collecting, pushing, or
        # requiring a hosted runner. Verification's exit status is the input.
        stubs = '''set -e
git() { printf '%s\\n' "$*" >> calls.txt; }
python() {
  if [ "$1" = '-c' ]; then return "$VERIFY_EXIT"; fi
  return 0
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'operational').mkdir()
            (root / 'operational/seen_jobs.ndjson.gz').write_bytes(b'synthetic snapshot')
            script = root / 'publish.sh'
            script.write_text(stubs + body, encoding='utf-8', newline='\n')
            result = subprocess.run([BASH, 'publish.sh'], cwd=root,
                                    env={**os.environ, 'VERIFY_EXIT': '0' if verified else '1',
                                         'GITHUB_STEP_SUMMARY': 'summary.txt'},
                                    capture_output=True, text=True)
            calls = (root / 'calls.txt').read_text(encoding='utf-8').splitlines()
        return result, calls

    def test_verified_collection_stages_seen_snapshot(self):
        result, calls = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('add -f operational/seen_jobs.ndjson.gz', calls)

    def test_dry_run_does_not_publish_seen_snapshot(self):
        result, calls = self.publish(dry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('add -f operational/seen_jobs.ndjson.gz', calls)

    def test_failed_verification_does_not_publish_seen_snapshot(self):
        result, calls = self.publish(verified=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('add -f operational/seen_jobs.ndjson.gz', calls)
