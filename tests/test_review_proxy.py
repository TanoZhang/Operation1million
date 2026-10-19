"""The public HTTPS proxy in front of Review and the notes: never without a password."""
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from operation1million import review, review_login

ROOT = Path(__file__).resolve().parents[1]


def config(name):
    text = (ROOT / 'deploy/vps' / name).read_text(encoding='utf-8')
    return '\n'.join(line.split('#')[0] for line in text.splitlines())


class ReviewProxyTests(unittest.TestCase):
    def setUp(self):
        self.config = config('Caddyfile')

    def test_one_site_and_every_page_asks_the_login_before_the_proxy(self):
        # Review has no login and hands its write token to anyone who loads it.
        sites = re.findall(r'^(\S[^{\n]*)\{', self.config, re.M)
        self.assertEqual([site.strip() for site in sites], ['40-160-142-175.sslip.io'])
        catch_all = self.config[self.config.index('\thandle {'):]
        self.assertLess(catch_all.index('forward_auth 127.0.0.1:8765'), catch_all.index('reverse_proxy'))
        self.assertIn('uri /__auth', catch_all)
        # Only the password page itself is served without it.
        self.assertEqual(re.findall(r'^\thandle (\S+) \{', self.config, re.M), ['/__login'])
        self.assertNotIn('review-users', self.config)

    def test_it_proxies_only_to_loopback_ports(self):
        self.assertEqual(set(re.findall(r'(?:reverse_proxy|forward_auth)\s+(\S+)', self.config)),
                         {'127.0.0.1:8765'})
        self.assertEqual(self.config.count('header_up Host localhost:8765'), 3)

    def test_the_password_scripts_keep_passwords_off_the_command_line(self):
        script = (ROOT / 'deploy/vps/review-password.sh').read_text(encoding='utf-8')
        self.assertIn('operation1million.review_login --set', script)
        notes = (ROOT / 'deploy/vps/notes-password.sh').read_text(encoding='utf-8')
        self.assertIn('hash=$(caddy hash-password)', notes)
        self.assertNotIn('--plaintext', script + notes)


class NotesProxyTests(unittest.TestCase):
    """Obsidian's WebDAV folder (2026-10-19): /notes/ on Review's name, its own
    login, loopback only, and nothing that stops Review before it is set up."""

    def test_notes_require_their_own_login_before_the_proxy(self):
        route = config('notes-route.caddy')
        self.assertIn('@notes path /notes /notes/*', route)
        self.assertLess(route.find('basic_auth'), route.find('reverse_proxy'))
        self.assertIn('import /etc/caddy/notes-users', route)
        self.assertEqual(re.findall(r'reverse_proxy\s+(\S+)', route), ['127.0.0.1:8780'])

    def test_the_route_arrives_only_through_a_pattern_after_its_login(self):
        self.assertIn('import /etc/caddy/routes/*.caddy', config('Caddyfile'))
        script = (ROOT / 'deploy/vps/notes-password.sh').read_text(encoding='utf-8')
        self.assertLess(script.index('/etc/caddy/notes-users.new'), script.index('/etc/caddy/routes/notes.caddy'))

    def test_webdav_listens_on_loopback_under_notes_as_its_own_user(self):
        unit = config('operation1million-notes.service')
        self.assertIn('--addr 127.0.0.1:8780 --baseurl /notes', unit)
        self.assertIn('User=obsidian-notes', unit)
        self.assertIn('ReadWritePaths=/srv/obsidian-notes', unit)


class LoginRecordTests(unittest.TestCase):
    def setUp(self):
        self.record = review_login.make_record('correct horse')

    def test_only_the_password_opens_it(self):
        self.assertTrue(review_login.check('correct horse', self.record))
        self.assertFalse(review_login.check('correct hors', self.record))
        self.assertFalse(review_login.check('correct horse', None))
        self.assertNotIn('correct horse', json.dumps(self.record))

    def test_a_cookie_is_signed_and_expires(self):
        value = review_login.session(self.record, now=1000)
        cookie = f'other=1; {review_login.COOKIE}={value}'
        self.assertTrue(review_login.signed_in(cookie, self.record, now=1001))
        self.assertFalse(review_login.signed_in(cookie, self.record, now=1000 + review_login.LIFETIME + 1))
        expires = value.split('.')[0]
        forged = f'{review_login.COOKIE}={int(expires) + 99}.{value.split(".")[1]}'
        self.assertFalse(review_login.signed_in(forged, self.record, now=1001))
        # A new password signs everyone out.
        self.assertFalse(review_login.signed_in(cookie, review_login.make_record('correct horse'), now=1001))
        self.assertFalse(review_login.signed_in(cookie, None, now=1001))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class LoginEndpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'review-login.json'
        self.path.write_text(json.dumps(review_login.make_record('correct horse')), encoding='utf-8')
        for target in (patch.object(review_login, 'PATH', self.path),
                       patch.object(review.applications, 'queue',
                                    side_effect=lambda *a: {n: [] for n in ('pending', 'backlog', 'applied', 'skipped')})):
            target.start()
            self.addCleanup(target.stop)
        self.server = review.make_server(Path(temporary.name) / 'none.sqlite', Path(temporary.name) / 'ledger.ndjson', 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.open = build_opener(NoRedirect).open

    def ask(self, path, data=None, headers=None):
        request = Request(self.base + path, data=data, headers=headers or {})
        try:
            response = self.open(request)
        except HTTPError as error:
            return error.code, error.headers
        return response.status, response.headers

    def login(self, password):
        return self.ask('/__login', urlencode({'password': password}).encode(),
                        {'X-Forwarded-For': '203.0.113.9'})

    def test_auth_sends_a_stranger_to_the_password_page(self):
        code, headers = self.ask('/__auth')
        self.assertEqual((code, headers['Location']), (302, '/__login'))
        self.assertEqual(self.ask('/__login')[0], 200)

    def test_the_right_password_sets_a_cookie_that_passes(self):
        code, headers = self.login('correct horse')
        self.assertEqual((code, headers['Location']), (303, '/'))
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Secure', cookie)
        self.assertEqual(self.ask('/__auth', headers={'Cookie': cookie.split(';')[0]})[0], 204)

    def test_a_wrong_password_is_logged_for_fail2ban_and_refused(self):
        with patch('builtins.print') as said, patch.object(review.time, 'sleep'):
            code, headers = self.login('wrong')
        self.assertEqual((code, headers['Location']), (303, '/__login?failed'))
        self.assertIsNone(headers['Set-Cookie'])
        said.assert_called_once_with('review login refused for 203.0.113.9', flush=True)

    def test_without_a_password_record_nobody_is_let_in(self):
        self.path.unlink()
        self.assertEqual(self.login('correct horse')[1]['Location'], '/__login?failed')


class Fail2banTests(unittest.TestCase):
    """The filters match the lines as written, and nothing that succeeded."""

    def pattern(self, name):
        text = (ROOT / 'deploy/vps/fail2ban' / name).read_text(encoding='utf-8')
        regex = re.search(r'^failregex = (.+)$', text, re.M).group(1)
        return re.compile(regex.replace('<HOST>', r'(?P<host>[0-9a-fA-F.:]+)'))

    def test_review_failures(self):
        found = self.pattern('op1m-review.conf').search('review login refused for 198.51.100.7')
        self.assertEqual(found['host'], '198.51.100.7')

    def test_webdav_failures_and_not_successes(self):
        line = ('{"level":"info","ts":1792443407.2,"logger":"http.log.access","msg":"handled request",'
                '"request":{"remote_ip":"10.0.0.1","remote_port":"5","client_ip":"198.51.100.8","proto":"HTTP/2.0",'
                '"method":"PROPFIND","host":"40-160-142-175.sslip.io","uri":"/notes/vault/a.md"},"status":401}')
        pattern = self.pattern('op1m-webdav.conf')
        self.assertEqual(pattern.search(line)['host'], '198.51.100.8')
        self.assertIsNone(pattern.search(line.replace('"status":401', '"status":207')))
        self.assertIsNone(pattern.search(line.replace('"/notes/vault/a.md"', '"/api/queue"')))

    def test_install_puts_the_jails_in_place(self):
        script = (ROOT / 'deploy/vps/install.sh').read_text(encoding='utf-8')
        for name in ('filter.d/op1m-review.conf', 'filter.d/op1m-webdav.conf', 'jail.d/op1m.local'):
            self.assertIn('/etc/fail2ban/' + name, script)


if __name__ == '__main__':
    unittest.main()
