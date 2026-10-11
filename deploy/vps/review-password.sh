#!/usr/bin/env bash
# Set the Review page's login on the VPS and start the HTTPS proxy. Run it
# yourself, over ssh -t:
#
#   sudo bash /opt/operation1million/code/deploy/vps/review-password.sh
#
# Caddy asks for the password twice and stores only its bcrypt hash. The
# password never reaches an argument, the shell history or a repository.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi
read -r -p 'Username: ' user
case "$user" in
  ''|*[!A-Za-z0-9._-]*) echo 'Use letters, digits, dot, dash or underscore.' >&2; exit 64 ;;
esac
hash=$(caddy hash-password)
install -m 640 -o root -g caddy /dev/null /etc/caddy/review-users.new
printf '%s %s\n' "$user" "$hash" > /etc/caddy/review-users.new
mv /etc/caddy/review-users.new /etc/caddy/review-users
install -m 644 /opt/operation1million/code/deploy/vps/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable caddy
systemctl restart caddy
echo "Open https://40-160-142-175.sslip.io and sign in as $user."
