#!/usr/bin/env bash
# Replace the data repository's history with a single commit holding the current
# rolling window. Run by hand, on the VPS, while watching it.
#
#   sudo -u jobdisco HOME=/opt/jobdisco bash deploy/vps/compact-history.sh
#
# WHY THIS IS NOT PART OF THE NIGHTLY PASS
#
# Pruning the working tree reclaims nothing: appending to a gzip file writes a
# whole new object every pass, so every byte the log has ever held stays in the
# history, and deleting a file in a new commit only adds to it. Measured three
# days in, 199 MB of working tree against 307 MB of history.
#
# Only replacing the history reclaims, and that is a force-push. It is
# irreversible, and it destroys the one place a bad prune could still be
# recovered from. Doing that unattended at 04:38 would mean the first anyone
# heard of a mistake was after it had been made permanent.
#
# AFTERWARDS, EVERY OTHER CLONE IS BROKEN
#
# A plain `git pull` will refuse. Each other checkout needs:
#
#   git fetch origin && git reset --hard origin/main
#
# This machine is the sole scheduled writer, which is the only reason rewriting
# the shared history is safe at all.
set -euo pipefail

ROOT=${JOBDISCO_ROOT:-/opt/jobdisco}
DATA=$ROOT/data
KEEP=${JOBDISCO_KEEP_DAYS:-14}
export JOBDISCO_STORE=$DATA
export PATH=$ROOT/venv/bin:$PATH

cd "$DATA"

# Never compact around a pass. The lock is the same one daily-pass.sh takes.
exec 9>"$ROOT/collection.lock"
if ! flock -n 9; then
  echo 'A collection or deployment is running; try again when it is done.' >&2
  exit 75
fi

echo "== Before =="
echo "  history:      $(du -sm .git | cut -f1) MiB"
echo "  working tree: $(du -sm --exclude=.git . | cut -f1) MiB"

if [ -n "$(git status --porcelain)" ]; then
  echo 'The data checkout has uncommitted changes. Let a pass publish them first.' >&2
  exit 1
fi
if ! git diff --quiet "@{u}" HEAD 2>/dev/null; then
  echo 'Local and remote differ. Push or reconcile before rewriting history.' >&2
  exit 1
fi

echo '== Verify the store before making anything permanent =='
job-store --verify

echo "== Prune to the last $KEEP days =="
python -m jobdisco.prune --store "$DATA" --keep "$KEEP"

echo '== Replace the history with one commit =='
git checkout --quiet --orphan compacted
git add -A
git -c user.name='jobdisco-vps' -c user.email='jobdisco-vps@users.noreply.github.com' \
    commit --quiet -m "Snapshot $(date -u +%Y-%m-%d): a ${KEEP}-day rolling backup

The log is a backup, not the working state. The derived index lives on the VPS,
postings close within weeks, and anything genuinely missed is collected again on
the next pass rather than recovered from an archive.

Everything under operational/ is carried across unchanged: the credit ledger,
the per-source cooldowns and the applications log are records of money and of
decisions, and nothing regenerates them."
git branch --quiet -M compacted main

echo '== Push =='
git push --force origin main

git reflog expire --expire=now --all
git gc --prune=now --quiet

echo '== After =='
echo "  history:      $(du -sm .git | cut -f1) MiB"
echo "  working tree: $(du -sm --exclude=.git . | cut -f1) MiB"
echo
echo 'Every other clone of the data repository must now run:'
echo '    git fetch origin && git reset --hard origin/main'
