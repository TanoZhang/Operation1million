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
# Windows checkout has no rsync. Python is required at both ends to snapshot
# SQLite and validate the incoming operational state.
set -euo pipefail

HOST=${JOBDISCO_VPS:-ubuntu@40.160.142.175}
KEY=${JOBDISCO_VPS_KEY:-$HOME/.ssh/op1m_vps}
REMOTE=${JOBDISCO_VPS_DATA:-/opt/jobdisco/data}
REMOTE_DB=${JOBDISCO_VPS_DB:-/opt/jobdisco/code/data/db/job_discovery.sqlite}
REMOTE_STATE=${JOBDISCO_VPS_STATE:-/opt/jobdisco/code/.local}
REMOTE_USER=${JOBDISCO_VPS_USER:-jobdisco}
TARGET=${1:-${JOBDISCO_BACKUP_DIR:-$HOME/op1m-backup}}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

mkdir -p "$TARGET"
# Recover a previous interrupted installation before discarding any staging.
if [ -d "$TARGET/previous.tmp" ]; then
  if [ ! -e "$TARGET/current" ]; then
    mv "$TARGET/previous.tmp" "$TARGET/current"
  else
    rm -rf "$TARGET/previous"
    mv "$TARGET/previous.tmp" "$TARGET/previous"
  fi
fi
incoming=$TARGET/.incoming
rm -rf "$incoming"
mkdir -p "$incoming"

echo "== Pulling $HOST:$REMOTE =="
# --exclude=.git: the history is on GitHub and is not what a rebuild reads.
# The working tree is: runs, manifests, source_state.json and operational/.
# The SQLite snapshot is made through sqlite3.Connection.backup(), so it is
# consistent even if review or collection has the live WAL database open.
# Quote paths for the remote shell independently of the local one.
remote_quote() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
# Run as the service account, which owns every file read here. As the SSH
# user it failed whenever nothing else had the index open: a WAL database with
# no -shm needs one created, and the SSH user cannot write that directory --
# measured on the VPS, 2026-09-22. The same account owns the decision lock.
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
    "sudo -n -u $(remote_quote "$REMOTE_USER") python3 - $(remote_quote "$REMOTE") $(remote_quote "$REMOTE_DB") $(remote_quote "$REMOTE_STATE")" \
    < "$SCRIPT_DIR/../vps/backup-snapshot.py" \
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
for name in jsearch_usage.sqlite source_access.sqlite seen_jobs.ndjson.gz; do
  if [ ! -s "$tree/operational/$name" ]; then
    echo "WARNING: operational/$name is missing or empty in the copy." >&2
    missing=1
  fi
done
if [ ! -f "$tree/operational/applications.ndjson" ]; then
  echo 'WARNING: the application ledger is missing.' >&2
  missing=1
fi
validator=
for python in "${JOBDISCO_PYTHON:-}" python3 python; do
  [ -n "$python" ] && command -v "$python" >/dev/null 2>&1 || continue
  validator=$python
  break
done
if [ -z "$validator" ]; then
  echo 'Python is required to validate operational state; preserving existing backups.' >&2
  exit 1
fi
if ! "$validator" "$SCRIPT_DIR/validate-backup.py" "$tree"; then
  echo 'WARNING: operational state did not pass validation.' >&2
  missing=1
fi
# Validate the derived index as well as the irreplaceable operational state.
# The remote helper and pipefail propagate snapshot or transfer failures.
snapshot=$tree/sqlite/job_discovery.sqlite
if [ ! -s "$snapshot" ]; then
  echo "WARNING: sqlite/job_discovery.sqlite is missing or empty in the copy." >&2
  missing=1
elif [ "$(head -c 16 "$snapshot" | tr -d '\0')" != 'SQLite format 3' ]; then
  echo "WARNING: sqlite/job_discovery.sqlite is not a SQLite database; the" >&2
  echo "         snapshot command on the VPS most likely failed." >&2
  missing=1
else
  # Python was required above; every accepted snapshot receives this check.
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

# Equal counts do not prove that the two sets describe the same days/shards.
for log in "$tree"/runs/*.ndjson.gz; do
  [ -f "$log" ] || continue
  name=$(basename "$log" .ndjson.gz)
  if [ ! -f "$tree/manifests/$name.json" ]; then
    echo "WARNING: runs/$name.ndjson.gz has no matching manifest." >&2
    missing=1
  fi
done
for manifest in "$tree"/manifests/*.json; do
  [ -f "$manifest" ] || continue
  name=$(basename "$manifest" .json)
  if [ ! -f "$tree/runs/$name.ndjson.gz" ]; then
    echo "WARNING: manifests/$name.json has no matching run file." >&2
    missing=1
  fi
done
# Pairing says the two sets name the same days. It does not say the run files
# are the ones their manifests describe. Each manifest carries the sha256 of its
# file, and that is the only check here that would notice a truncated transfer
# or a file corrupted on the way: without it a damaged copy validates, rotates
# into current, and a second one moves it into previous -- which is how two
# consecutive pulls replace both intact generations.
#
# The day still being written is exempt. A pass may be appending to it while tar
# reads it and rewrites the manifest when it finishes, so a mismatch there is a
# race with a live pass rather than a damaged copy.
verified=no
for python in "${JOBDISCO_PYTHON:-}" python3 python; do
  [ -n "$python" ] && command -v "$python" >/dev/null 2>&1 || continue
  if ! "$python" - "$tree" <<'CHECKSUMS'
import datetime, hashlib, json, pathlib, sys

root = pathlib.Path(sys.argv[1])
today = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
live = today + '.ndjson.gz'
problems, checked = [], 0
for manifest_path in sorted((root / 'manifests').glob('*.json')):
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except ValueError as exc:
        problems.append('%s is not readable JSON (%s)' % (manifest_path.name, exc))
        continue
    name, digest = manifest.get('file'), manifest.get('sha256')
    if not name or not digest:
        problems.append('%s records no file or no digest' % manifest_path.name)
        continue
    data = root / name
    if not data.is_file():
        problems.append('%s names %s, which is not in the copy' % (manifest_path.name, name))
        continue
    running = hashlib.sha256()
    with data.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            running.update(block)
    checked += 1
    if running.hexdigest() == digest:
        continue
    if pathlib.PurePosixPath(name).name == live:
        print('  note:     %s is today and still being written; its digest is not final' % name)
        continue
    problems.append('%s does not match the digest in %s' % (name, manifest_path.name))
for problem in problems:
    sys.stderr.write('WARNING: ' + problem + '\n')
print('  checksums: %d run files verified against their manifests' % checked)
sys.exit(1 if problems else 0)
CHECKSUMS
  then
    missing=1
  fi
  verified=yes
  break
done
if [ "$verified" != yes ]; then
  echo 'Run-file checksums could not be verified; preserving existing backups.' >&2
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  echo "Backup validation failed; current, previous and last-pull were preserved." >&2
  echo "The failed copy remains under $incoming for inspection." >&2
  exit 1
fi

# Swap only once the copy has been looked at. The previous one is kept until
# the next successful pull, so a bad night never leaves zero copies.
previous=$TARGET/previous
current=$TARGET/current
if [ -d "$current" ]; then
  mv "$current" "$previous.tmp"
fi
if ! mv "$tree" "$current"; then
  if [ -d "$previous.tmp" ] && [ ! -e "$current" ]; then
    mv "$previous.tmp" "$current"
  fi
  echo 'Backup installation failed; the previous good generation was preserved.' >&2
  exit 1
fi
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
