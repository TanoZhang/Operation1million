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
for argument in "$@"; do
  case "$argument" in
    --no-heartbeat) unset HEALTHCHECK_URL ;;
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
    git add runs manifests source_state.json
  else
    publication_failed=1
    echo 'Collected history did not verify; publishing charges without unpublished cursors.' >&2
    python -m jobdisco.workflow_state operational/jsearch_usage.sqlite \
      "$CODE/.local/jsearch_usage.before.sqlite"
  fi
  for name in operational/source_access.sqlite operational/jsearch_usage.sqlite operational/applications.ndjson; do
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
  return "$publication_failed"
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
