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

# Review uses a different lock: hold it too so a decision cannot arrive between
# checking the tree and replacing it after a successful publication.
exec 8>"$DATA/operational/applications.lock"
flock 8
if [ -n "$(git status --porcelain -- . ':(exclude)operational/applications.lock')" ]; then
  echo 'The data checkout has uncommitted changes. Let a pass publish them first.' >&2
  exit 1
fi
git fetch --quiet origin main
expected=$(git rev-parse refs/remotes/origin/main)
if [ "$(git branch --show-current)" != main ] || [ "$(git rev-parse HEAD)" != "$expected" ]; then
  echo 'Local and remote differ. Push or reconcile before rewriting history.' >&2
  exit 1
fi

echo '== Verify the store before making anything permanent =='
job-store --verify

echo "== Prune to the last $KEEP days =="
# Build off to the side. A rejected push must leave the live branch, index and
# files unchanged, so the ordinary daily pull and a later retry still work.
staging=$(mktemp -d)
cleanup() {
  git -C "$DATA" worktree remove --force "$staging/tree" 2>/dev/null || true
  rmdir "$staging" 2>/dev/null || true
}
trap cleanup EXIT
git worktree add --quiet --detach "$staging/tree" HEAD
python -m jobdisco.prune --store "$staging/tree" --keep "$KEEP"

echo '== Replace the history with one commit =='
git -C "$staging/tree" add -A
tree=$(git -C "$staging/tree" write-tree)
candidate=$(git -c user.name='jobdisco-vps' -c user.email='jobdisco-vps@users.noreply.github.com' \
    commit-tree "$tree" -m "Snapshot $(date -u +%Y-%m-%d): a ${KEEP}-day rolling backup

The log is a backup, not the working state. The derived index lives on the VPS,
postings close within weeks, and anything genuinely missed is collected again on
the next pass rather than recovered from an archive.

Everything under operational/ is carried across unchanged: the credit ledger,
the per-source cooldowns and the applications log are records of money and of
decisions, and nothing regenerates them.")

echo '== Push =='
git push --force-with-lease="refs/heads/main:$expected" origin "$candidate:refs/heads/main"
# The remote accepted the exact candidate. Keep a recovery ref until the local
# checkout has followed it, and never update the checkout before acceptance.
git update-ref refs/jobdisco/pre-compaction HEAD
git reset --hard --quiet "$candidate"
git update-ref -d refs/jobdisco/pre-compaction
cleanup
trap - EXIT

git reflog expire --expire=now --all
git gc --prune=now --quiet

echo '== After =='
echo "  history:      $(du -sm .git | cut -f1) MiB"
echo "  working tree: $(du -sm --exclude=.git . | cut -f1) MiB"
echo
echo 'Every other clone of the data repository must now run:'
echo '    git fetch origin && git reset --hard origin/main'
