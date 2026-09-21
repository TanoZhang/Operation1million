#!/usr/bin/env bash
# Push the applications ledger to GitHub, often.
#
# Every other file in the data repository can be collected again. This one
# cannot: it is the record of what has been applied for, and nothing
# regenerates it. Until now it reached GitHub only when a pass published, so a
# decision made after one pass and before the next lived on a single disk for
# up to a day, and that disk is the thing being insured against.
#
# Committing without pushing would not have helped -- a commit that never
# leaves the machine dies with it -- so this pushes.
#
# It touches nothing but the ledger. It never writes to the file, only ever
# stages, commits and pushes it, so a failure here cannot damage the thing it
# is protecting; it says so and leaves the next run to try again.
set -euo pipefail

ROOT=${JOBDISCO_ROOT:-/opt/jobdisco}
DATA=$ROOT/data
LEDGER=operational/applications.ndjson

cd "$DATA"

# The same lock the pass, the installer and the compaction take. Two git
# processes in one repository is the failure this avoids; a pass in progress is
# ordinary, not an error, so this steps aside quietly and tries again in
# fifteen minutes.
exec 9>"$ROOT/collection.lock"
if ! flock -n 9; then
  echo 'A collection or deployment holds the lock; the ledger will go out on the next tick.'
  exit 0
fi

if [ ! -f "$LEDGER" ]; then
  echo 'No applications ledger yet; nothing to back up.'
  exit 0
fi

git add -- "$LEDGER"
if git diff --cached --quiet -- "$LEDGER"; then
  # No empty commits: a timer that runs every fifteen minutes would otherwise
  # add ninety-six commits a day saying nothing happened.
  git reset --quiet -- "$LEDGER"
else
  # -m before --, because everything after -- is a pathspec: with the message
  # after it, git looked for files called "-m" and "Back up application
  # decisions ...", failed, and the backup never committed anything.
  git -c user.name='jobdisco-vps' -c user.email='jobdisco-vps@users.noreply.github.com' \
      commit --quiet --only -m "Back up application decisions $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      -- "$LEDGER"
  echo "Committed $(wc -l < "$LEDGER") decisions."
fi

# A commit that exists here and not on the remote is the whole case this timer
# exists for, and it used to be the one case the timer could not fix: the push
# below ran only when a new decision had just been committed, so a failed push
# waited for the next decision rather than the next tick. That is exactly
# backwards -- a failed push is what leaves the ledger on one disk, and no
# further decision may arrive for days.
#
# `origin/main` is the last state this machine pushed or fetched. It cannot
# claim we are behind when we are not, and a push that is already up to date is
# a cheap no-op, so erring toward pushing is safe in both directions.
if git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null; then
  if [ "$(git rev-list --count refs/remotes/origin/main..HEAD)" -eq 0 ]; then
    exit 0
  fi
fi

if ! git push --quiet origin main; then
  # The commit is made and the next tick will try to push it again. Say so
  # loudly anyway: a backup that silently stopped reaching GitHub looks exactly
  # like one that is working.
  echo 'WARNING: the application ledger was committed but could not be pushed.' >&2
  echo '         It is still only on this machine. Check the remote and the token.' >&2
  exit 1
fi
echo 'Pushed.'
