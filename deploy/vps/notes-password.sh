#!/usr/bin/env bash
# Set the notes login and start Obsidian's WebDAV folder. Run it yourself,
# over ssh -t, and again to change the password:
#
#   sudo bash /opt/operation1million/code/deploy/vps/notes-password.sh
#
# Caddy asks for the password twice and stores only its bcrypt hash. The
# password never reaches an argument, the shell history or a repository.
# In Obsidian's Remotely Save: WebDAV, https://40-160-142-175.sslip.io/notes/,
# the same username and password.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# /notes/ lives in Review's site, which review-password.sh installs.
if [ ! -f /etc/operation1million/review-login.json ]; then
  echo 'Run review-password.sh first: /notes/ is served from the same site.' >&2
  exit 1
fi
command -v rclone >/dev/null || apt-get install -y rclone
id obsidian-notes >/dev/null 2>&1 || useradd --system --home-dir /srv/obsidian-notes --shell /usr/sbin/nologin obsidian-notes
install -d -m 750 -o obsidian-notes -g obsidian-notes /srv/obsidian-notes /srv/obsidian-notes/vault
read -r -p 'Username: ' user
case "$user" in
  ''|*[!A-Za-z0-9._-]*) echo 'Use letters, digits, dot, dash or underscore.' >&2; exit 64 ;;
esac
hash=$(caddy hash-password)
install -m 640 -o root -g caddy /dev/null /etc/caddy/notes-users.new
printf '%s %s\n' "$user" "$hash" > /etc/caddy/notes-users.new
mv /etc/caddy/notes-users.new /etc/caddy/notes-users
install -m 644 "$here/operation1million-notes.service" /etc/systemd/system/operation1million-notes.service
systemctl daemon-reload
systemctl enable --now operation1million-notes.service
systemctl restart operation1million-notes.service
install -d -m 755 /etc/caddy/routes
install -m 644 "$here/notes-route.caddy" /etc/caddy/routes/notes.caddy
# Caddy opens its access log itself; a root-owned one stopped it (2026-10-19).
install -d -o caddy -g caddy /var/log/caddy
touch /var/log/caddy/access.log
chown caddy:caddy /var/log/caddy/access.log
chmod 640 /var/log/caddy/access.log
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy || systemctl restart caddy
systemctl is-active --quiet caddy || { echo "Caddy did not start: journalctl -u caddy" >&2; exit 1; }
echo "WebDAV for Remotely Save: https://40-160-142-175.sslip.io/notes/  user: $user"
