"""Review's login over HTTPS: a password alone (the user, 2026-10-19).

The browser's own login box always asks for a username as well, so Caddy asks
this server instead (`forward_auth` to /__auth) and sends a stranger to a page
with one field. A right password sets a signed cookie for thirty days. A wrong
one waits a second and logs a line that fail2ban counts. The SSH tunnel reaches
the server directly and is not asked.

The record lives outside both repositories: an scrypt hash of the password
and the key that signs cookies. Without it nobody is let in. Set it with

    sudo python -m operation1million.review_login --set
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time

PATH = Path(os.environ.get('OPERATION1MILLION_REVIEW_LOGIN', '/etc/operation1million/review-login.json'))
COOKIE = 'op1m_review'
LIFETIME = 30 * 24 * 3600
_SCRYPT = {'n': 2 ** 14, 'r': 8, 'p': 1, 'dklen': 32}


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)


def make_record(password):
    salt = secrets.token_bytes(16)
    return {'salt': base64.b64encode(salt).decode(), 'hash': base64.b64encode(_hash(password, salt)).decode(),
            'secret': secrets.token_hex(32)}


def read(path=None):
    """The record, or None: then nobody is let in."""
    try:
        record = json.loads(Path(path or PATH).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and {'salt', 'hash', 'secret'} <= set(record) else None


def check(password, record):
    if not record or not isinstance(password, str) or not password:
        return False
    return hmac.compare_digest(_hash(password, base64.b64decode(record['salt'])),
                               base64.b64decode(record['hash']))


def _sign(record, expires):
    return hmac.new(record['secret'].encode(), str(expires).encode(), hashlib.sha256).hexdigest()


def session(record, now=None):
    """A cookie value good for LIFETIME seconds."""
    expires = int(now if now is not None else time.time()) + LIFETIME
    return f'{expires}.{_sign(record, expires)}'


def signed_in(cookie_header, record, now=None):
    if not record:
        return False
    for part in (cookie_header or '').split(';'):
        name, _, value = part.strip().partition('=')
        if name != COOKIE:
            continue
        expires, _, signature = value.partition('.')
        if (expires.isdigit() and int(expires) > (now if now is not None else time.time())
                and hmac.compare_digest(signature, _sign(record, int(expires)))):
            return True
    return False


PAGE = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Review</title>
<style>body{font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0 16px}
form{display:grid;gap:12px;width:min(320px,100%)}input,button{font:inherit;padding:10px;border-radius:6px;
border:1px solid #999}button{cursor:pointer}p{color:#b00;margin:0}</style></head><body>
<form method="post" action="/__login">{notice}<input type="password" name="password" autocomplete="current-password"
autofocus required placeholder="Password"><button>Open Review</button></form></body></html>'''


def page(failed=False):
    return PAGE.replace('{notice}', '<p>Wrong password.</p>' if failed else '').encode()


def main():
    parser = argparse.ArgumentParser(description='Set the password for Review over HTTPS.')
    parser.add_argument('--set', action='store_true', required=True)
    parser.add_argument('--owner', default='operation1million', help='The account the review server runs as')
    args = parser.parse_args()
    first = getpass.getpass('Password: ')
    if len(first) < 8:
        parser.error('Use at least eight characters.')
    if getpass.getpass('Again: ') != first:
        parser.error('The two did not match.')
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix('.new')
    temporary.write_text(json.dumps(make_record(first)), encoding='utf-8')
    os.chmod(temporary, 0o600)
    if hasattr(os, 'chown') and os.geteuid() == 0:
        import pwd
        account = pwd.getpwnam(args.owner)
        os.chown(temporary, account.pw_uid, account.pw_gid)
    os.replace(temporary, PATH)
    print(f'Review password set in {PATH}. Every browser signs in again.')


if __name__ == '__main__':
    main()
