#!/usr/bin/env bash
# A consistent copy of the live job index, taken while the collector is running.
#
#   bash deploy/vps/snapshot-database.sh /path/to/copy.sqlite
#   bash deploy/vps/snapshot-database.sh --stdout > copy.sqlite
#
# Copying the file is not the same thing as copying the database. The index is
# in WAL mode and a pass writes to it for an hour, so `cp` during that hour
# yields a main file missing every committed transaction still in the WAL, or
# -- worse, because it looks fine -- a torn page from a checkpoint that landed
# mid-read. Neither announces itself; both are discovered on the night the copy
# is needed. SQLite's own backup API is the supported answer: it copies page by
# page under a read transaction and restarts if a writer moves underneath it,
# so what lands is a database as of one instant that actually existed.
#
# Running as the owner is not optional. A read-only connection to a WAL
# database still has to take a read mark in the -shm file, which means write
# permission on it, so `ubuntu` cannot open this database read-only at all: it
# fails with a bare "unable to open database file" that reads like a missing
# path. This re-executes itself as the owning user rather than leaving that to
# be rediscovered.
#
# One direction only. Nothing here writes to the live index.
set -euo pipefail

ROOT=${JOBDISCO_ROOT:-/opt/jobdisco}
OWNER=${JOBDISCO_USER:-jobdisco}
DB=${JOBDISCO_DB:-$ROOT/code/data/db/job_discovery.sqlite}

if [ "$(id -un)" != "$OWNER" ] && [ "$(id -u)" -ne 0 ]; then
  # -n: never prompt. An ssh session has no terminal to prompt on, and a sudo
  # that blocks here would hang the backup rather than fail it.
  exec sudo -n -u "$OWNER" env JOBDISCO_ROOT="$ROOT" JOBDISCO_USER="$OWNER" \
       JOBDISCO_DB="$DB" bash "$0" "$@"
fi

destination=${1:-}
to_stdout=0
if [ "$destination" = '--stdout' ] || [ -z "$destination" ]; then
  to_stdout=1
  destination=''
fi

if [ ! -s "$DB" ]; then
  echo "No job index at $DB" >&2
  exit 1
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/jobdisco-snapshot.XXXXXX")
trap 'rm -rf "$work"' EXIT
snapshot=$work/job_discovery.sqlite

# The copy is the size of the original, and a backup that fills the disk it is
# protecting has made things worse. Checked against the filesystem the copy
# lands on, which is not necessarily the one the database is on.
bytes=$(stat -c %s "$DB")
target_dir=$([ -n "$destination" ] && dirname "$destination" || echo "$work")
available=$(df -kP "$target_dir" | awk 'NR==2 {print $4}')
if [ "$available" -lt $(( bytes / 1024 + 65536 )) ]; then
  echo "Refusing to snapshot: $(( bytes / 1048576 )) MiB needed, $(( available / 1024 )) MiB free on $target_dir." >&2
  exit 1
fi

PYTHON=${JOBDISCO_PYTHON:-$ROOT/venv/bin/python}
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi

"$PYTHON" - "$DB" "$snapshot" <<'PY' >&2
import sqlite3
import sys
from pathlib import Path

source = sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + '?mode=ro', uri=True)
copy = sqlite3.connect(sys.argv[2])
try:
    # `backup` is the online API: it holds a read transaction over each batch of
    # pages and starts again if a writer commits underneath it, which is what
    # makes the result a single instant rather than a smear of several.
    with copy:
        source.backup(copy)
    # Cheap and worth it: a snapshot is only useful if it opens, and the moment
    # to find out is now rather than during a restore.
    state = copy.execute('PRAGMA quick_check').fetchone()[0]
    if state != 'ok':
        raise SystemExit(f'Snapshot failed its integrity check: {state}')
    jobs, open_jobs = copy.execute(
        'SELECT COUNT(*), COUNT(*) FILTER (WHERE closed_at IS NULL) FROM jobs').fetchone()
    seen = copy.execute('SELECT COUNT(*) FROM seen_jobs').fetchone()[0]
    print(f'snapshot: {jobs} postings ({open_jobs} open), {seen} seen', file=sys.stderr)
finally:
    copy.close()
    source.close()
PY

if [ "$to_stdout" -eq 1 ]; then
  cat "$snapshot"
else
  # Into place in one step, so an interrupted run cannot leave a half-written
  # file where the last good copy used to be.
  mv "$snapshot" "$destination"
  echo "snapshot written to $destination" >&2
fi
