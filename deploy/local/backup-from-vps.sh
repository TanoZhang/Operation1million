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
# It uses tar over ssh rather than rsync: rsync has to exist at both ends, and a
# Windows checkout has no rsync. tar transfers everything each time, which is
# the cost of not needing anything installed.
set -euo pipefail

HOST=${JOBDISCO_VPS:-ubuntu@40.160.142.175}
KEY=${JOBDISCO_VPS_KEY:-$HOME/.ssh/op1m_vps}
REMOTE=${JOBDISCO_VPS_DATA:-/opt/jobdisco/data}
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

# The four files nothing regenerates. A backup missing one of these is the kind
# that is discovered to be useless at the moment it is needed.
missing=0
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
echo "  pulled:   $(cat "$TARGET/last-pull")"
echo
echo "To rebuild the index from this copy:"
echo "    JOBDISCO_STORE=$current job-store --bootstrap --verify"
exit "$missing"
