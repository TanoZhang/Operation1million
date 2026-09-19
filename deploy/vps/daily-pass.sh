#!/usr/bin/env bash
# The VPS owns the production schedule and its persistent operational ledgers.
set -euo pipefail

ROOT=${JOBDISCO_ROOT:-/opt/jobdisco}
CODE=$ROOT/code
DATA=$ROOT/data
export JOBDISCO_STORE=$DATA
export PATH=$ROOT/venv/bin:$PATH
export PYTHONUNBUFFERED=1
export JOBDISCO_PYTHON=$ROOT/venv/bin/python

# Manual invocations and installer updates share the service's lock.
exec 9>"$ROOT/collection.lock"
if ! flock -n 9; then
  echo 'Another collection or deployment is running; no requests sent.' >&2
  exit 75
fi

ENV_FILE=${JOBDISCO_ENV_FILE:-/etc/jobdisco/env}
if [ -r "$ENV_FILE" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi
PREFLIGHT=0
for argument in "$@"; do
  case "$argument" in
    --no-heartbeat) unset HEALTHCHECK_URL ;;
    # Everything the pass depends on, checked in the order the pass depends on
    # it, and then stop before spending a credit or writing a row. This exists
    # because the rest of this file runs unattended at 04:38 against the
    # authoritative data, and the cheapest moment to find a broken token, a
    # missing ledger or a full disk is any moment other than that one.
    --preflight) PREFLIGHT=1; unset HEALTHCHECK_URL ;;
    *) echo "unknown argument: $argument" >&2; exit 64 ;;
  esac
done

# shellcheck source=heartbeat.sh
. "$CODE/deploy/vps/heartbeat.sh"
collect_started=0
run_clean=0
collect_code=0
sweep_code=0
READY=$CODE/.local/database-ready

database_inputs() {
  git -C "$CODE" rev-parse HEAD:data/config
  git -C "$DATA" rev-parse HEAD:runs HEAD:manifests HEAD:source_state.json
}

publish_state() {
  mkdir -p "$DATA/operational"
  for name in source_access.sqlite jsearch_usage.sqlite; do
    cp "$CODE/.local/$name" "$DATA/operational/$name"
  done
  cd "$DATA"
  git config user.name 'jobdisco-vps'
  git config user.email 'jobdisco-vps@users.noreply.github.com'
  publication_failed=0
  if job-store --verify; then
    # The published log is a rolling backup, not the working state: this box
    # keeps the derived index, and anything genuinely missed is collected again
    # rather than recovered from an archive.
    #
    # The ordering is the load-bearing part. Pruning here puts the deletions in
    # this commit, so the READY fingerprint written below -- which hashes
    # HEAD:runs -- describes the tree as it now stands. A prune that landed
    # after that fingerprint would read on the next pass as history this
    # machine has not replayed, trigger `job-store --bootstrap`, and rebuild
    # from the truncated log. That would shrink the live database and not only
    # the backup, because `seen` and `closed` events are UPDATE statements: a
    # posting whose job line was pruned is not recreated by them, it is gone.
    python -m jobdisco.prune --store "$DATA" --keep "${JOBDISCO_KEEP_DAYS:-14}"
    git add -A runs manifests source_state.json
  else
    publication_failed=1
    echo 'Collected history did not verify; publishing charges without unpublished cursors.' >&2
    python -m jobdisco.workflow_state operational/jsearch_usage.sqlite \
      "$CODE/.local/jsearch_usage.before.sqlite"
  fi
  # Knowing a job has been seen before lives in the derived index, which is
  # gitignored and dies with this machine. Snapshotted here so a rebuilt box
  # does not treat every previously rejected posting as new -- and kept under
  # operational/, outside the fourteen-day window, because that memory has to
  # outlast the log it was built from.
  # Loudly, but never fatally. Aborting publication over a snapshot would throw
  # away a whole pass of collected postings to protect a convenience; staying
  # quiet would leave a stale snapshot looking like a current one, which is the
  # failure this table exists to prevent. So: keep the data, say it plainly.
  if ! python -m jobdisco.store --export-seen; then
    echo 'WARNING: the seen-jobs snapshot was not refreshed; it is now stale and' >&2
    echo '         a rebuilt machine would treat old rejections as new.' >&2
  fi
  for name in operational/source_access.sqlite operational/jsearch_usage.sqlite \
              operational/applications.ndjson operational/seen_jobs.ndjson.gz; do
    if [ -f "$name" ]; then git add -f "$name"; fi
  done
  if ! git diff --cached --quiet; then
    git commit -m "Checkpoint collection $(date -u +%Y-%m-%d)"
  fi
  if [ "$publication_failed" -eq 0 ] && [ "$run_clean" -eq 1 ]; then
    database_inputs > "$READY.tmp"
    mv "$READY.tmp" "$READY"
  fi
  # Retry an earlier unpushed commit even when this pass added no new changes.
  git push origin main
  report_history_size
  return "$publication_failed"
}

report_history_size() {
  # Pruning the working tree reclaims nothing. Appending to a gzip file writes a
  # whole new object every pass, so every byte the log has ever held is still in
  # the history, and deleting a file in a new commit only adds to it. Measured
  # three days in: 199 MB of working tree against 307 MB of history.
  #
  # Reclaiming means replacing the history, which means a force-push, which is
  # irreversible and removes the one place a bad prune could be recovered from.
  # That is a thing to do while looking at it, not at 04:38 with nobody awake,
  # so this only says when it is due. `deploy/vps/compact-history.sh` does it.
  local limit size
  limit=${JOBDISCO_HISTORY_LIMIT_MB:-2048}
  size=$(du -sm .git 2>/dev/null | cut -f1)
  if [ -n "$size" ] && [ "$size" -ge "$limit" ]; then
    echo "NOTE: the data repository's history is ${size} MiB against a ${limit} MiB" >&2
    echo "      limit. Run deploy/vps/compact-history.sh to replace it." >&2
  fi
}

finish() {
  code=$?
  trap - EXIT
  set +e
  if [ "$collect_started" -eq 1 ]; then
    # Run with errexit in a subshell: checkpoint failures must not be swallowed.
    (set -e; publish_state)
    publication_code=$?
    if [ "$code" -eq 0 ] && [ "$publication_code" -ne 0 ]; then code=$publication_code; fi
  fi
  if [ "$code" -eq 0 ]; then heartbeat success; else heartbeat fail; fi
  exit "$code"
}
trap finish EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
heartbeat start

available=$(df --output=avail -k "$DATA" | tail -1)
if [ "$available" -lt 5242880 ]; then
  echo "Refusing to collect: only $((available / 1024)) MiB free on $DATA; 5 GiB required." >&2
  exit 1
fi

echo '== Pull the data repository =='
git -C "$DATA" pull --ff-only
mkdir -p "$CODE/.local"
for name in source_access.sqlite jsearch_usage.sqlite; do
  if [ ! -s "$CODE/.local/$name" ]; then
    if [ ! -s "$DATA/operational/$name" ]; then
      echo "Required operational ledger is missing or empty: $name" >&2
      exit 1
    fi
    cp "$DATA/operational/$name" "$CODE/.local/$name"
  fi
done

# "Present and non-empty" is not the same question as "still knows what was
# spent". A ledger left by an interrupted run, a restore from the wrong place,
# or a diagnostic that merely opened the path is several kilobytes of valid
# SQLite with nothing in it, and it passes every check but the one that
# matters. The local ledger may be ahead of the published one -- a pass whose
# push failed leaves exactly that -- but it may never be behind.
python -m jobdisco.ledger_guard   "$CODE/.local/jsearch_usage.sqlite" "$DATA/operational/jsearch_usage.sqlite"

cp "$CODE/.local/jsearch_usage.sqlite" "$CODE/.local/jsearch_usage.before.sqlite"
cd "$CODE"

echo '== Offline regression tests =='
python -m unittest discover -s tests
echo '== Database =='
inputs=$(database_inputs)
if [ ! -f "$CODE/data/db/job_discovery.sqlite" ] || [ ! -f "$READY" ] || [ "$(cat "$READY")" != "$inputs" ]; then
  # Rebuild after an interrupted pass, catalog change, or newly pulled history.
  job-store --bootstrap --verify
else
  job-store --verify
fi

if [ "$PREFLIGHT" -eq 1 ]; then
  # The lock, the secrets, the disk, the pull, the ledgers and their ordering,
  # the suite and the index have all been exercised by the time we reach here.
  # What is left is the credential that only reveals itself at the very end of
  # a pass, ninety minutes after anyone stopped watching.
  echo '== Preflight: can the data repository be pushed to? =='
  git -C "$DATA" push --dry-run origin main
  echo '== Preflight OK: nothing was collected, charged or written. =='
  exit 0
fi

job-collect --jsearch-only --jsearch-plan
# A killed process must not leave a disposable index marked as synchronized.
rm -f "$READY"
collect_started=1
set +e
job-collect --workers 3 --delay 1.0 --jsearch-max-seconds 6000 --jsearch-timeout 90 --jsearch
collect_code=$?
set -e
if [ "$collect_code" -eq 2 ]; then
  echo 'WARNING: collection completed with partial or paused sources.' >&2
elif [ "$collect_code" -ne 0 ]; then
  exit "$collect_code"
fi

days_until_reset=$(python - <<'PY'
from jobdisco import jsearch
from jobdisco.jsearch_access import RequestGuard
settings, _ = jsearch.load_plan()
guard = RequestGuard(target_limit=settings['monthly_target'],
                     cycle_start=settings['cycle_start'], cycle_days=settings['cycle_days'])
print(guard.days_until_reset())
PY
)
if [ "$days_until_reset" -le 3 ]; then
  set +e
  job-collect --jsearch-only --backfill --workers 1 --delay 1.0 --jsearch-max-seconds 3000
  sweep_code=$?
  set -e
fi
if [ "$sweep_code" -ne 0 ]; then exit "$sweep_code"; fi
run_clean=1
# EXIT publishes before the success heartbeat, including on collection failure.
