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
  exit 0
fi

# -m before --, because everything after -- is a pathspec: with the message
# after it, git looked for files called "-m" and "Back up application
# decisions ...", failed, and the backup never committed anything.
git -c user.name='jobdisco-vps' -c user.email='jobdisco-vps@users.noreply.github.com' \
    commit --quiet --only -m "Back up application decisions $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -- "$LEDGER"
echo "Committed $(wc -l < "$LEDGER") decisions."

if ! git push --quiet origin main; then
  # The commit is made and will go out with the next tick or the next pass. Say
  # so loudly: a backup that silently stopped reaching GitHub looks exactly like
  # one that is working.
  echo 'WARNING: the application ledger was committed but could not be pushed.' >&2
  echo '         It is still only on this machine. Check the remote and the token.' >&2
  exit 1
fi
echo 'Pushed.'
