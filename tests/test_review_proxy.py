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


if __name__ == '__main__':
    unittest.main()
