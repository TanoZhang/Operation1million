"""The public HTTPS proxy in front of Review: never without its password."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReviewProxyTests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / 'deploy/vps/Caddyfile').read_text(encoding='utf-8')
        self.config = '\n'.join(line.split('#')[0] for line in text.splitlines())

    def test_every_site_requires_the_password_before_the_proxy(self):
        # Review has no login and hands its write token to anyone who loads it.
        sites = re.findall(r'^(\S[^{\n]*)\{', self.config, re.M)
        self.assertEqual([site.strip() for site in sites], ['40-160-142-175.sslip.io'])
        auth = self.config.find('basic_auth')
        self.assertGreater(auth, 0)
        self.assertLess(auth, self.config.find('reverse_proxy'))
        self.assertIn('import /etc/caddy/review-users', self.config)

    def test_it_proxies_only_to_the_loopback_review_port(self):
        self.assertEqual(re.findall(r'reverse_proxy\s+(\S+)', self.config), ['127.0.0.1:8765'])
        self.assertIn('header_up Host localhost:8765', self.config)

    def test_the_password_script_keeps_the_password_off_the_command_line(self):
        script = (ROOT / 'deploy/vps/review-password.sh').read_text(encoding='utf-8')
        self.assertIn('hash=$(caddy hash-password)', script)
        self.assertNotIn('--plaintext', script)


class NotesProxyTests(unittest.TestCase):
    """Obsidian's WebDAV folder (2026-10-19): its own login, loopback only,
    and nothing that can stop Review before its login exists."""

    def text(self, name):
        return '\n'.join(line.split('#')[0] for line in
                         (ROOT / 'deploy/vps' / name).read_text(encoding='utf-8').splitlines())

    def test_the_notes_site_requires_its_own_password_before_the_proxy(self):
        config = self.text('notes.caddy')
        self.assertEqual([s.strip() for s in re.findall(r'^(\S[^{\n]*)\{', config, re.M)],
                         ['notes-40-160-142-175.sslip.io'])
        self.assertLess(config.find('basic_auth'), config.find('reverse_proxy'))
        self.assertIn('import /etc/caddy/notes-users', config)
        self.assertEqual(re.findall(r'reverse_proxy\s+(\S+)', config), ['127.0.0.1:8780'])

    def test_review_imports_the_site_only_through_a_pattern(self):
        # A missing notes login must not stop Caddy, and with it Review.
        self.assertIn('import /etc/caddy/sites/*.caddy', self.text('Caddyfile'))
        self.assertNotIn('notes-users', self.text('Caddyfile'))
        script = (ROOT / 'deploy/vps/notes-password.sh').read_text(encoding='utf-8')
        self.assertLess(script.index('/etc/caddy/notes-users.new'), script.index('/etc/caddy/sites/notes.caddy'))

    def test_webdav_listens_on_loopback_as_its_own_user(self):
        unit = self.text('operation1million-notes.service')
        self.assertIn('--addr 127.0.0.1:8780', unit)
        self.assertIn('User=obsidian-notes', unit)
        self.assertIn('ReadWritePaths=/srv/obsidian-notes', unit)
        script = (ROOT / 'deploy/vps/notes-password.sh').read_text(encoding='utf-8')
        self.assertIn('hash=$(caddy hash-password)', script)
        self.assertNotIn('--plaintext', script)


if __name__ == '__main__':
    unittest.main()
