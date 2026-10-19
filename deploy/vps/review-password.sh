#!/usr/bin/env bash
# Set the password that opens Review over HTTPS, and (re)start the proxy.
# Run it yourself, over ssh -t, and again to change the password:
#
#   sudo bash /opt/operation1million/code/deploy/vps/review-password.sh
#
# A password alone, no username (the user, 2026-10-19). It is asked twice
# and stored only as an scrypt hash in /etc/operation1million; it never
# reaches an argument, the shell history or a repository. Changing it signs
# every browser out.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PYTHONPATH=/opt/operation1million/code/src /opt/operation1million/venv/bin/python \
  -m operation1million.review_login --set --owner operation1million
install -d -m 755 /etc/caddy/routes
install -m 644 "$here/Caddyfile" /etc/caddy/Caddyfile
# Caddy opens its access log itself; a root-owned one stopped it (2026-10-19).
install -d -o caddy -g caddy /var/log/caddy
touch /var/log/caddy/access.log
chown caddy:caddy /var/log/caddy/access.log
chmod 640 /var/log/caddy/access.log
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# The username-and-password file the site used before 2026-10-19.
rm -f /etc/caddy/review-users
systemctl restart operation1million-review.service
systemctl enable caddy
systemctl reload caddy || systemctl restart caddy
systemctl is-active --quiet caddy || { echo "Caddy did not start: journalctl -u caddy" >&2; exit 1; }
echo "Open https://40-160-142-175.sslip.io and enter the password."
