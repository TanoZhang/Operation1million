#!/usr/bin/env bash
# Install or update the daily pass on a fresh Ubuntu VPS. Idempotent: run it
# again after a code change and it updates the checkout, the virtualenv and the
# units without touching the database, the ledgers or the secrets.
#
#   sudo ./install.sh
#
# The secrets are never arguments and never reach the shell history. The first
# run writes /etc/jobdisco/env with blanks and stops; you fill it in with an
# editor on the box and run this again.
set -euo pipefail

ROOT=/opt/jobdisco
ENV_FILE=/etc/jobdisco/env
SERVICE_USER=jobdisco
CODE_REPO=https://github.com/TanoZhang/Operation1million.git
DATA_REPO=https://github.com/TanoZhang/Operation1million-data.git

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi

echo "== Packages =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-dev git curl ca-certificates

echo "== Service account =="
# A system account with no login and no password: the pass needs a home for
# git's config and nothing else.
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$ROOT" "$ROOT/bin"

echo "== Secrets =="
install -d -o root -g root -m 755 /etc/jobdisco
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'TEMPLATE'
# Mode 600, root-owned, readable by the jobdisco group. These are the whole
# credential set the pass needs. Nothing here belongs in either repository.
#
# JSEARCH_API_KEY   RapidAPI key for the fixed JSearch plan.
# GITHUB_TOKEN      Fine-grained PAT: Contents read on the code repository,
#                   Contents read+write on the data repository.
# HEALTHCHECK_URL   Healthchecks.io ping URL for the production check. Leaving
#                   this blank silences the heartbeat, which is what a
#                   diagnostic machine should do -- but on the production box a
#                   blank here means nothing will ever notice the pass dying.
JSEARCH_API_KEY=
GITHUB_TOKEN=
HEALTHCHECK_URL=
TEMPLATE
fi
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

# shellcheck source=/dev/null
set +u
. "$ENV_FILE"
set -u
missing=()
[ -n "${GITHUB_TOKEN:-}" ] || missing+=(GITHUB_TOKEN)
[ -n "${JSEARCH_API_KEY:-}" ] || missing+=(JSEARCH_API_KEY)
if [ "${#missing[@]}" -gt 0 ]; then
  echo
  echo "Fill in ${missing[*]} first:"
  echo "    sudo nano $ENV_FILE"
  echo "then run this script again. Editing on the box keeps the values out of"
  echo "your shell history and off your workstation."
  exit 2
fi
if [ -z "${HEALTHCHECK_URL:-}" ]; then
  echo "WARNING: HEALTHCHECK_URL is blank. Nothing will notice a pass that stops running." >&2
fi

echo "== Repositories =="
# The token is handed to git on stdout by a helper that reads it from the
# environment, so it is never written into .git/config and never appears in a
# remote URL that `git remote -v` or a process listing would show.
HELPER='!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f'
clone_or_update() {
  local url=$1 path=$2
  if [ ! -d "$path/.git" ]; then
    sudo -u "$SERVICE_USER" GITHUB_TOKEN="$GITHUB_TOKEN" \
      git -c credential.helper="$HELPER" clone "$url" "$path"
  fi
  sudo -u "$SERVICE_USER" git -C "$path" config credential.helper "$HELPER"
  sudo -u "$SERVICE_USER" GITHUB_TOKEN="$GITHUB_TOKEN" \
    git -C "$path" fetch --quiet origin
}
clone_or_update "$CODE_REPO" "$ROOT/code"
clone_or_update "$DATA_REPO" "$ROOT/data"
# The code checkout tracks the remote exactly; the data checkout is only ever
# fast-forwarded, because it holds commits this machine made.
sudo -u "$SERVICE_USER" git -C "$ROOT/code" checkout --quiet main
sudo -u "$SERVICE_USER" git -C "$ROOT/code" reset --hard --quiet origin/main
sudo -u "$SERVICE_USER" git -C "$ROOT/data" merge --ff-only --quiet origin/main || \
  echo "NOTE: the data checkout could not fast-forward; resolve it before the next pass." >&2

echo "== Virtualenv =="
if [ ! -x "$ROOT/venv/bin/python" ]; then
  sudo -u "$SERVICE_USER" python3 -m venv "$ROOT/venv"
fi
sudo -u "$SERVICE_USER" "$ROOT/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$ROOT/venv/bin/pip" install --quiet -e "$ROOT/code"

echo "== Entry point =="
ln -sfn "$ROOT/code/deploy/vps/daily-pass.sh" "$ROOT/bin/daily-pass.sh"
chmod +x "$ROOT/code/deploy/vps/daily-pass.sh"

echo "== Units =="
install -m 644 "$ROOT/code/deploy/vps/jobdisco-collect.service" /etc/systemd/system/
install -m 644 "$ROOT/code/deploy/vps/jobdisco-collect.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jobdisco-collect.timer

echo
echo "Installed. Next run:"
systemctl list-timers jobdisco-collect.timer --no-pager || true
echo
echo "The first pass builds the database from the committed log, which takes"
echo "about 30 seconds and 639 MB. Every pass after it skips that."
