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
# It takes the whole data tree plus a SQLite backup snapshot. The small files
# under operational/ are the ones that cannot be collected again, and the live
# SQLite file is a faster, fuller restore point than the rolling fourteen-day
# event log. The database is copied with SQLite's backup API on the VPS first;
# the script never directly copies a database file that may be mid-write.
#
# It uses tar over ssh rather than rsync: rsync has to exist at both ends, and a
# Windows checkout has no rsync. tar transfers everything each time, which is
# the cost of not needing anything installed.
set -euo pipefail

HOST=${JOBDISCO_VPS:-ubuntu@40.160.142.175}
KEY=${JOBDISCO_VPS_KEY:-$HOME/.ssh/op1m_vps}
REMOTE=${JOBDISCO_VPS_DATA:-/opt/jobdisco/data}
REMOTE_DB=${JOBDISCO_VPS_DB:-/opt/jobdisco/code/data/db/job_discovery.sqlite}
TARGET=${1:-${JOBDISCO_BACKUP_DIR:-$HOME/op1m-backup}}

mkdir -p "$TARGET"
incoming=$TARGET/.incoming
rm -rf "$incoming"
mkdir -p "$incoming"

echo "== Pulling $HOST:$REMOTE =="
# --exclude=.git: the history is on GitHub and is not what a rebuild reads.
# The working tree is: runs, manifests, source_state.json and operational/.
# The SQLite snapshot is made through sqlite3.Connection.backup(), so it is
# consistent even if review or collection has the live WAL database open.
SNAPSHOT_CODE="import sqlite3, sys; src, dst = sys.argv[1:3]; source = sqlite3.connect('file:' + src.replace('?', '%3f') + '?mode=ro', uri=True); target = sqlite3.connect(dst); source.backup(target); target.close(); source.close()"
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
    "tmp=\$(mktemp -d); \
     trap 'rm -rf \"\$tmp\"' EXIT; \
     mkdir -p \"\$tmp/sqlite\"; \
     python3 -c \"$SNAPSHOT_CODE\" '$REMOTE_DB' \"\$tmp/sqlite/job_discovery.sqlite\"; \
     tar czf - -C '$(dirname "$REMOTE")' --exclude=.git '$(basename "$REMOTE")' -C \"\$tmp\" sqlite" \
  | tar xzf - -C "$incoming"

tree=$incoming/$(basename "$REMOTE")
if [ -d "$incoming/sqlite" ]; then
  mv "$incoming/sqlite" "$tree/sqlite"
fi
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
# The snapshot is the one file here that is not simply transferred: it is
# produced on the far end by a command whose failure the tar pipeline does not
# report, so it is checked rather than assumed. Present and non-empty is not
# the same question as openable, and a restore is the wrong moment to find out.
snapshot=$tree/sqlite/job_discovery.sqlite
if [ ! -s "$snapshot" ]; then
  echo "WARNING: sqlite/job_discovery.sqlite is missing or empty in the copy." >&2
  missing=1
elif [ "$(head -c 16 "$snapshot" | tr -d '\0')" != 'SQLite format 3' ]; then
  echo "WARNING: sqlite/job_discovery.sqlite is not a SQLite database; the" >&2
  echo "         snapshot command on the VPS most likely failed." >&2
  missing=1
else
  # A deeper check where a Python happens to be available. Not required: this
  # runs on a workstation that may not have one, and a header check has already
  # caught the failure mode that actually happens.
  for python in "${JOBDISCO_PYTHON:-}" python3 python; do
    [ -n "$python" ] && command -v "$python" >/dev/null 2>&1 || continue
    if ! "$python" -c 'import sqlite3, sys
db = sqlite3.connect("file:" + sys.argv[1].replace("?", "%3f") + "?mode=ro", uri=True)
state = db.execute("PRAGMA quick_check").fetchone()[0]
if state != "ok":
    sys.exit("integrity check says: " + state)
print("  sqlite:   %d postings, %d open" % db.execute(
    "SELECT COUNT(*), COUNT(*) FILTER (WHERE closed_at IS NULL) FROM jobs").fetchone())' "$snapshot"; then
      echo "WARNING: the snapshot did not pass its integrity check." >&2
      missing=1
    fi
    break
  done
fi

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
echo "  sqlite:   $current/sqlite/job_discovery.sqlite"
echo "  decisions: $(wc -l < "$current/operational/applications.ndjson" 2>/dev/null || echo 0)"
echo "  pulled:   $(cat "$TARGET/last-pull")"
echo
echo "Fast restore from the copied SQLite snapshot:"
echo "    install -D $current/sqlite/job_discovery.sqlite /opt/jobdisco/code/data/db/job_discovery.sqlite"
echo
echo "Rebuild the index from event history instead:"
echo "    JOBDISCO_STORE=$current job-store --bootstrap --verify"
exit "$missing"
