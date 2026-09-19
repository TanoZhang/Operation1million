#!/usr/bin/env bash
# Pull a disaster-recovery copy of the VPS's data directory to this machine.
#
#   ./deploy/local/backup-from-vps.sh
#
# One direction only: the VPS owns everything -- the scraper, the index, the
# seen table, the review UI and the application decisions written through it --
# and this machine holds a copy in case that one is lost. Nothing here is ever
# pushed back, because a second writer is how two copies of a decision log stop
# agreeing.
#
# It takes the whole data tree rather than just the irreplaceable parts. The
# small files under operational/ are the ones that cannot be collected again,
# but a copy that could not rebuild the index without a network round trip is a
# worse copy, and the log is capped at fourteen days anyway.
#
# And it takes the index itself, which the data tree does not hold. Rebuilding
# from the log only reconstructs what the fourteen-day window still carries:
# `seen`, `closed` and `score` events are UPDATE statements, so a posting whose
# job line has aged out of the window is not recreated by them. The rebuild
# path stays the tested one, but a copy of the database is the difference
# between losing a day and losing everything older than a fortnight.
#
# It uses tar over ssh rather than rsync: rsync has to exist at both ends, and a
# Windows checkout has no rsync. tar transfers everything each time, which is
# the cost of not needing anything installed.
set -euo pipefail

HOST=${JOBDISCO_VPS:-ubuntu@40.160.142.175}
KEY=${JOBDISCO_VPS_KEY:-$HOME/.ssh/op1m_vps}
REMOTE=${JOBDISCO_VPS_DATA:-/opt/jobdisco/data}
CODE=${JOBDISCO_VPS_CODE:-/opt/jobdisco/code}
TARGET=${1:-${JOBDISCO_BACKUP_DIR:-$HOME/op1m-backup}}

mkdir -p "$TARGET"
incoming=$TARGET/.incoming
rm -rf "$incoming"
mkdir -p "$incoming"

echo "== Pulling $HOST:$REMOTE =="
# --exclude=.git: the history is on GitHub and is not what a rebuild reads.
# The working tree is: runs, manifests, source_state.json and operational/.
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
    "tar czf - -C '$(dirname "$REMOTE")' --exclude=.git '$(basename "$REMOTE")'" \
  | tar xzf - -C "$incoming"

tree=$incoming/$(basename "$REMOTE")
if [ ! -d "$tree/operational" ]; then
  echo "The copy has no operational/ directory; refusing to replace the last good one." >&2
  exit 1
fi

# Taken through SQLite's backup API rather than copied, because the collector
# may be writing to it right now; see deploy/vps/snapshot-database.sh. Not
# fatal on its own: the log and operational/ are still the irreplaceable parts,
# and a pull that kept those is worth keeping even if the index did not come.
echo "== Snapshotting the job index =="
index=$tree/job_discovery.sqlite
if ssh -i "$KEY" -o BatchMode=yes "$HOST" \
       "bash '$CODE/deploy/vps/snapshot-database.sh' --stdout" > "$index"; then
  echo "  index:    $(du -h "$index" | cut -f1)"
else
  echo 'WARNING: no consistent index snapshot was taken; this copy can only be' >&2
  echo '         rebuilt from the log, which reaches back fourteen days.' >&2
  rm -f "$index"
  missing_index=1
fi

# The four files nothing regenerates. A backup missing one of these is the kind
# that is discovered to be useless at the moment it is needed.
missing=${missing_index:-0}
for name in applications.ndjson jsearch_usage.sqlite source_access.sqlite seen_jobs.ndjson.gz; do
  if [ ! -s "$tree/operational/$name" ]; then
    echo "WARNING: operational/$name is missing or empty in the copy." >&2
    missing=1
  fi
done

# Every run file needs its manifest, or the copy cannot be verified on restore.
runs=$(find "$tree/runs" -name '*.ndjson.gz' 2>/dev/null | wc -l)
manifests=$(find "$tree/manifests" -name '*.json' 2>/dev/null | wc -l)
if [ "$runs" -ne "$manifests" ]; then
  echo "WARNING: $runs run files against $manifests manifests; the copy may not verify." >&2
  missing=1
fi

# Swap only once the copy has been looked at. The previous one is kept until
# the next successful pull, so a bad night never leaves zero copies.
previous=$TARGET/previous
current=$TARGET/current
rm -rf "$previous.tmp"
if [ -d "$current" ]; then
  mv "$current" "$previous.tmp"
fi
mv "$tree" "$current"
rm -rf "$incoming"
if [ -d "$previous.tmp" ]; then
  rm -rf "$previous"
  mv "$previous.tmp" "$previous"
fi

date -u '+%Y-%m-%dT%H:%M:%SZ' > "$TARGET/last-pull"
echo "== Copy =="
echo "  at:       $TARGET/current"
echo "  size:     $(du -sh "$current" | cut -f1)"
echo "  runs:     $runs files, $manifests manifests"
echo "  decisions: $(wc -l < "$current/operational/applications.ndjson" 2>/dev/null || echo 0)"
echo "  index:    $([ -s "$current/job_discovery.sqlite" ] && du -h "$current/job_discovery.sqlite" | cut -f1 || echo 'not taken')"
echo "  pulled:   $(cat "$TARGET/last-pull")"
echo
echo "To restore, prefer the snapshot -- it holds postings older than the log:"
echo "    cp $current/job_discovery.sqlite <checkout>/data/db/job_discovery.sqlite"
echo "Or rebuild from the log alone, which reaches back fourteen days:"
echo "    JOBDISCO_STORE=$current job-store --bootstrap --verify"
exit "$missing"
