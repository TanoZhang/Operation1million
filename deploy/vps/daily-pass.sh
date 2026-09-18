#!/usr/bin/env bash
# One daily collection pass, on a machine that keeps its disk.
#
# This mirrors .github/workflows/collect.yml step for step. Where it differs,
# it differs because the runner's empty disk was the reason for the original,
# and those reasons are noted inline rather than left to be rediscovered.
set -euo pipefail

ROOT=/opt/jobdisco
CODE=$ROOT/code
DATA=$ROOT/data
export JOBDISCO_STORE=$DATA
export PATH=$ROOT/venv/bin:$PATH
export PYTHONUNBUFFERED=1

# Only a real production pass has a heartbeat to send. HEALTHCHECK_URL comes
# from /etc/jobdisco/env by way of the systemd unit and appears nowhere in the
# source tree; a shell that does not have it -- a manual diagnostic, a test --
# stays silent, because a ping it sent would tell the check a production pass
# had succeeded when none had run. --no-heartbeat suppresses it even under
# systemd, for diagnosing the machine without disturbing the monitor.
for argument in "$@"; do
  case "$argument" in
    --no-heartbeat) unset HEALTHCHECK_URL ;;
    *) echo "unknown argument: $argument" >&2; exit 64 ;;
  esac
done

JOBDISCO_PYTHON=$ROOT/venv/bin/python
export JOBDISCO_PYTHON
# shellcheck source=heartbeat.sh
. "$CODE/deploy/vps/heartbeat.sh"
# Arms the EXIT trap and sends /start. From here every exit, including one the
# shell takes on its own under `set -e`, reports itself and keeps its code.
heartbeat_arm

# A full disk fails exactly where the store is least able to survive it, so it
# is refused up front rather than discovered halfway through a write.
available=$(df --output=avail -k / | tail -1)
if [ "$available" -lt 5242880 ]; then
  echo "Refusing to collect: only $((available / 1024)) MiB free on /; 5 GiB is the floor." >&2
  exit 1
fi

echo "== Pull the data repository =="
git -C "$DATA" pull --ff-only

echo "== Seed the operational ledgers if this machine has none =="
# Actions restores these from the data repository on every run because its disk
# is empty. Here they persist and are authoritative: a run whose push failed
# leaves the local ledger ahead of the published one, and copying the published
# one back over it would resurrect credits the provider has already charged.
# So the published copy seeds a new machine and never overwrites a live ledger.
mkdir -p "$CODE/.local"
for name in source_access.sqlite jsearch_usage.sqlite; do
  if [ ! -s "$CODE/.local/$name" ]; then
    if [ ! -s "$DATA/operational/$name" ]; then
      echo "Required operational ledger is missing or empty: $name" >&2
      exit 1
    fi
    echo "seeding $name from the data repository"
    cp "$DATA/operational/$name" "$CODE/.local/$name"
  fi
done
cp "$CODE/.local/jsearch_usage.sqlite" "$CODE/.local/jsearch_usage.before.sqlite"

cd "$CODE"

echo "== Offline regression tests =="
# Before collection, so a broken build cannot reach the boards.
python -m unittest discover -s tests

echo "== Database =="
# The expensive rebuild is why this machine exists: 639 MB and 21.5s, paid once
# on a disk that persists rather than on every run.
if [ ! -f "$CODE/data/db/job_discovery.sqlite" ]; then
  echo "no database on this machine; building it from the committed log"
  job-store --bootstrap --verify
else
  job-store --verify
fi

echo "== Collect =="
job-collect --jsearch-only --jsearch-plan
set +e
job-collect --workers 3 --delay 1.0 --jsearch-max-seconds 6000 --jsearch-timeout 30 --jsearch
collect_code=$?
set -e
if [ "$collect_code" -eq 2 ]; then
  echo "WARNING: collection completed with partial or paused sources; inspect the report." >&2
elif [ "$collect_code" -ne 0 ]; then
  echo "Collection failed with exit $collect_code." >&2
fi

if [ "$collect_code" -eq 0 ] || [ "$collect_code" -eq 2 ]; then
  echo "== Cycle window =="
  # The cycle rolls every 30 days from a date, so this is computed from the
  # ledger and never from the calendar the timer fired on.
  days_until_reset=$(python - <<'PY'
from jobdisco import jsearch
from jobdisco.jsearch_access import RequestGuard
settings, _ = jsearch.load_plan()
guard = RequestGuard(target_limit=settings['monthly_target'],
                     cycle_start=settings['cycle_start'],
                     cycle_days=settings['cycle_days'])
print(guard.days_until_reset())
PY
)
  echo "$days_until_reset days until the cycle resets"
  if [ "$days_until_reset" -le 3 ]; then
    echo "== Backfill sweep =="
    # Unused credits do not carry over, so the cycle's last three days spend
    # what the daily passes left. A failed daily pass skips this: a sweep on
    # top of a broken pass would spend the remainder for nothing.
    set +e
    job-collect --jsearch-only --backfill --workers 1 --delay 1.0 --jsearch-max-seconds 3000
    echo "sweep exited $?"
    set -e
  fi
fi

echo "== Publish durable state =="
mkdir -p "$DATA/operational"
for name in source_access.sqlite jsearch_usage.sqlite; do
  if [ -f "$CODE/.local/$name" ]; then
    cp "$CODE/.local/$name" "$DATA/operational/$name"
  fi
done

cd "$DATA"
git config user.name 'jobdisco-vps'
git config user.email 'jobdisco-vps@users.noreply.github.com'
# The data repository ignores SQLite generally because the job database is
# derived. These are different: the quota and cooldown ledgers are authoritative
# and must outlive this machine, and the applications log is the record of what
# has been applied for -- the one thing here that cannot be collected again.
for name in operational/source_access.sqlite operational/jsearch_usage.sqlite operational/applications.ndjson; do
  # applications.ndjson does not exist until the first decision is recorded.
  if [ -f "$name" ]; then
    git add -f "$name"
  fi
done

publication_failed=0
# Never publish a store that cannot verify itself. A pass killed outright can
# stop between sharding the day's log and sealing its manifest; committing that
# leaves the repository unable to rebuild, which is worse than losing a pass.
if python -c "
import sys
from jobdisco import store
bad = [(d, s) for d, s in store.verify() if s != 'ok']
for d, s in bad:
    print(f'unverified: {d}: {s}')
sys.exit(1 if bad else 0)
"; then
  git add runs manifests source_state.json
else
  echo "WARNING: collected postings were not committed; the store did not verify." >&2
  publication_failed=1
fi

if git diff --cached --quiet; then
  echo "No durable state changed."
else
  git commit -m "Checkpoint collection $(date -u +%Y-%m-%d)"
  # A changed remote may hold reservations this machine never saw. Reject the
  # push rather than merging independent quota histories.
  git push origin main
fi

if [ "$publication_failed" -ne 0 ]; then
  exit 1
fi
if [ "$collect_code" -ne 0 ] && [ "$collect_code" -ne 2 ]; then
  exit "$collect_code"
fi
echo "== Done =="
