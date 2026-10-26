#!/usr/bin/env bash
# The VPS owns the production schedule and its persistent operational ledgers.
set -euo pipefail

ROOT=${OPERATION1MILLION_ROOT:-/opt/operation1million}
CODE=$ROOT/code
DATA=$ROOT/data
export OPERATION1MILLION_STORE=$DATA
export PATH=$ROOT/venv/bin:$PATH
export PYTHONUNBUFFERED=1
export OPERATION1MILLION_PYTHON=$ROOT/venv/bin/python

# Manual invocations and installer updates share the service's lock.
exec 9>"$ROOT/collection.lock"
if ! flock -n 9; then
  echo 'Another collection or deployment is running; no requests sent.' >&2
  exit 75
fi

ENV_FILE=${OPERATION1MILLION_ENV_FILE:-/etc/operation1million/env}
# Read as data, not run: see env-file.sh.
# shellcheck source=env-file.sh
. "$CODE/deploy/vps/env-file.sh"
load_env_file "$ENV_FILE"
PREFLIGHT=0
NOW=
ONCE=()
for argument in "$@"; do
  case "$argument" in
    --no-heartbeat) unset HEALTHCHECK_URL ;;
    # "Cancel the autorun and run it now" (2026-10-06): a full run budget now,
    # not what is left of a budget day that ends at 04:38 Pacific.
    --ignore-daily-limit) NOW=--ignore-daily-limit ;;
    # One run's own paid budget and window, for a pass started by hand:
    # "today 2,000, a month back instead of three days" (2026-10-13). Only
    # with --ignore-daily-limit may the budget exceed a day's; the monthly
    # target binds either way. The scheduled pass never passes these.
    --jsearch-budget=[1-9]*) ONCE+=("--jsearch-budget" "${argument#*=}") ;;
    --date-posted=today|--date-posted=3days|--date-posted=week|--date-posted=month)
      ONCE+=("--date-posted" "${argument#*=}") ;;
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
# shellcheck source=data-sync.sh
. "$CODE/deploy/vps/data-sync.sh"
collect_started=0
run_clean=0
collect_code=0
# The user's rule (2026-10-03): the daily pass runs, paid search included,
# every day. A failed check that does not threaten the data is reported and the
# pass carries on; the pass then ends with code 2 so the heartbeat says so.
# Only a full disk, both ledgers lost or an index that cannot be rebuilt still
# stop it. Every paid page still goes through the RequestGuard and its budget.
problems=0
note_problem() {
  problems=1
  echo "WARNING: $1 -- the pass carries on, paid search included." >&2
}
sweep_code=0
# The fewest credits the final day must have left before Japan is asked at all.
JAPAN_SWEEP_MIN=1000
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
  git config user.name 'operation1million-vps'
  git config user.email 'operation1million-vps@users.noreply.github.com'
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
    #
    # That rebuild happens anyway, on every change to data/config, so the open
    # postings a pruned day alone describes are first written into today's log
    # from this index (#318). If that fails, nothing is pruned.
    python -m operation1million.prune --store "$DATA" --keep "${OPERATION1MILLION_KEEP_DAYS:-14}" \
      --db "$CODE/data/db/job_discovery.sqlite" \
      || note_problem 'the log was not pruned; open postings could not be carried forward'
    git add -A runs manifests source_state.json
  else
    publication_failed=1
    echo 'Collected history did not verify; publishing charges without unpublished cursors.' >&2
    # Both ledgers, the running one first. The published copy is what a new
    # machine would seed from; the one under $CODE/.local is what the next pass
    # on this machine reads, and rewinding only the copy left the next sweep
    # treating queries as finished whose results were never published.
    # Credits, credit events and cooldowns are kept in both.
    python -m operation1million.workflow_state "$CODE/.local/jsearch_usage.sqlite" \
      "$CODE/.local/jsearch_usage.before.sqlite"
    python -m operation1million.workflow_state operational/jsearch_usage.sqlite \
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
  if ! python -m operation1million.store --export-seen; then
    echo 'WARNING: the seen-jobs snapshot was not refreshed; it is now stale and' >&2
    echo '         a rebuilt machine would treat old rejections as new.' >&2
  fi
  # The descriptions Muse supplied for Applied entries the index has none for
  # (the user, 2026-10-16), read before the list of those still missing.
  if [ -f job-applications/applied-jds.jsonl ] && ! python -m operation1million.applied_jd \
      job-applications/applied-jds.jsonl --ledger operational/applications.ndjson; then
    echo 'WARNING: job-applications/applied-jds.jsonl was not read; supplied descriptions wait for the next pass.' >&2
  fi
  # The open queue as one CSV, for Muse to read through the GitHub API
  # (2026-10-06), each UTC day's new listings on their own (Muse,
  # 2026-10-16), and the Applied entries still without a description
  # (applied-missing-jd). A convenience like the snapshot above: warn, never abort.
  if ! python -m operation1million.export operational/review_queue.csv \
      --db "$CODE/data/db/job_discovery.sqlite" --ledger operational/applications.ndjson \
      --daily-dir operational/daily-new --missing-jd-dir operational; then
    echo 'WARNING: operational/review_queue.csv was not refreshed; it is from an earlier pass.' >&2
  fi
  if ! python -m operation1million.company_audit --db "$CODE/data/db/job_discovery.sqlite" \
      --output operational/company_alias_audit.json; then
    echo 'WARNING: company alias audit was not refreshed; it is from an earlier pass.' >&2
  fi
  for name in operational/source_access.sqlite operational/jsearch_usage.sqlite \
              operational/applications.ndjson operational/listing_links.ndjson \
              operational/manual_jobs.ndjson operational/application_outcomes.ndjson \
              operational/seen_jobs.ndjson.gz operational/review_queue.csv \
              operational/company_alias_audit.json operational/applied_descriptions.ndjson \
              operational/applied-missing-jd.csv operational/applied-missing-jd.json \
              operational/jsearch_query_runs.ndjson; do
    if [ -f "$name" ]; then git add -f "$name"; fi
  done
  if [ -d operational/daily-new ]; then git add -f operational/daily-new; fi
  if ! git diff --cached --quiet; then
    git commit -m "Checkpoint collection $(date -u +%Y-%m-%d)"
  fi
  # Take in what another writer pushed while the pass ran, before the READY
  # fingerprint is taken and before the push, which a moved remote refuses.
  if ! sync_data "$DATA"; then
    report_history_size
    return 1
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
  limit=${OPERATION1MILLION_HISTORY_LIMIT_MB:-2048}
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
# Another writer (the user's laptop) commits to the data repository too. A
# fast-forward-only pull stopped the whole pass once the two had diverged
# (2026-10-03); now it is merged, and a merge that cannot be made is reported
# and the pass collects anyway -- publication retries it at the end.
sync_data "$DATA" || echo 'WARNING: collecting on an unsynchronised data repository.' >&2
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
python -m operation1million.collection_policy "$CODE/.local/source_access.sqlite" "$DATA/operational/source_access.sqlite"
if ! python -m operation1million.ledger_guard "$CODE/.local/jsearch_usage.sqlite" "$DATA/operational/jsearch_usage.sqlite"; then
  # The guard's own remedy: the published ledger has counted more, so it wins.
  echo 'Restoring the local credit ledger from the published one, as the guard advises.' >&2
  cp "$DATA/operational/jsearch_usage.sqlite" "$CODE/.local/jsearch_usage.sqlite" || true
  python -m operation1million.ledger_guard "$CODE/.local/jsearch_usage.sqlite" "$DATA/operational/jsearch_usage.sqlite" \
    || note_problem 'the credit ledger still does not agree with the published one'
fi

cp "$CODE/.local/jsearch_usage.sqlite" "$CODE/.local/jsearch_usage.before.sqlite"
cd "$CODE"

# Only a preflight runs the suite. GitHub Actions runs it on every push to main
# on this Ubuntu and Python (tests.yml), and deploy-vps.bat before each install,
# so the scheduled pass would only repeat it -- a failure never stopped the pass
# anyway. A preflight still does, to catch this machine drifting under the code.
# A failing test stopped the whole pass on 2026-10-03, free boards included.
# In a clean environment: with OPERATION1MILLION_STORE exported the tests read
# the production resume profile, and 65 of them failed on 2026-10-09 for that
# alone. Nor should a test see the production store or the paid key.
if [ "$PREFLIGHT" -eq 1 ]; then
  echo '== Offline regression tests =='
  env -i HOME="$HOME" PATH="$PATH" LANG=C.UTF-8 PYTHONUNBUFFERED=1 \
    python -m unittest discover -s tests || note_problem 'the offline tests did not all pass'
fi
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
  # A pass would carry on regardless; a preflight exists to say what is wrong.
  if [ "$problems" -eq 1 ]; then echo 'Preflight FAILED: see the warning above.' >&2; exit 1; fi
  echo '== Preflight: can the data repository be pushed to? =='
  git -C "$DATA" push --dry-run origin main
  echo '== Preflight OK: nothing was collected, charged or written. =='
  exit 0
fi

job-collect --jsearch-only --jsearch-plan || note_problem 'the JSearch plan preview failed'
# A killed process must not leave a disposable index marked as synchronized.
rm -f "$READY"
collect_started=1
set +e
job-collect --workers 3 --delay 1.0 --jsearch-max-seconds 6000 --jsearch-timeout 90 $NOW "${ONCE[@]}" --jsearch
collect_code=$?
set -e
if [ "$collect_code" -eq 2 ]; then
  echo 'WARNING: collection completed with partial or paused sources.' >&2
elif [ "$collect_code" -ne 0 ]; then
  exit "$collect_code"
fi

read -r days_until_reset sweep_period day_left < <(python - <<'PY'
from operation1million import jsearch
from operation1million.jsearch_access import RequestGuard
settings, _ = jsearch.load_plan()
guard = RequestGuard(limit=settings['monthly_quota'], target_limit=settings['monthly_target'],
                     daily_limit=settings['daily_budget'],
                     cycle_start=settings['cycle_start'], cycle_days=settings['cycle_days'],
                     day_zone=settings['budget_timezone'], day_resets_at=settings['budget_day_resets_at'])
print(guard.days_until_reset(), guard.period()[0], guard.balance()['day_remaining'] or 0)
PY
)
# Depth for the U.S. (the user, 2026-10-24: "jsearch美国的 大量改进 我要大量深度").
# The 3-day plan runs out of results after a page or two and left about 165 of
# its 350 daily credits unspent; those go to the month-wide sweep of the same
# U.S. queries at their sweep depth. Its pages resume across the cycle, so each
# day reads further down the month instead of buying page one again.
if [ "$day_left" -gt 0 ]; then
  set +e
  job-collect --jsearch-only --backfill --backfill-us-fallback --jsearch-budget "$day_left"     --workers 1 --delay 1.0 --jsearch-max-seconds 6000
  sweep_code=$?
  set -e
fi
if [ "$sweep_code" -ne 0 ]; then exit "$sweep_code"; fi
if [ "$days_until_reset" -le 1 ]; then
  # Credits do not carry into the next cycle. Japan is asked only when the
  # final day still has plenty left (the user, 2026-10-24: "日本的jsearch取消
  # 除非月底有很多额度"); whatever it leaves goes to the U.S. sweep.
  read -r fallback_period fallback_left < <(python - <<'PY'
from operation1million import jsearch
from operation1million.jsearch_access import RequestGuard
settings, _ = jsearch.load_plan()
guard = RequestGuard(target_limit=settings['monthly_target'],
                     cycle_start=settings['cycle_start'], cycle_days=settings['cycle_days'])
print(guard.period()[0], guard.balance()['period_remaining'])
PY
)
  if [ "$fallback_period" = "$sweep_period" ] && [ "$fallback_left" -ge "$JAPAN_SWEEP_MIN" ]; then
    set +e
    job-collect --jsearch-only --backfill --workers 1 --delay 1.0 --jsearch-max-seconds 6000
    sweep_code=$?
    set -e
    if [ "$sweep_code" -ne 0 ]; then exit "$sweep_code"; fi
  fi
  if [ "$fallback_period" = "$sweep_period" ] && [ "$fallback_left" -gt 0 ]; then
    job-collect --jsearch-only --backfill --backfill-us-fallback       --workers 1 --delay 1.0 --jsearch-max-seconds 6000
  fi
fi
# Each pass writes its raw output (jobs.jsonl, jobs.csv, a debug trace) under
# code/runs/, about 800 MB a day, and nothing reads it again: the data
# checkout keeps the same run compressed. 157 of them held 21 GB of a 38 GB
# disk (2026-10-25), so only the last week is kept (about 6 GB).
find "$CODE/runs" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null \
  || note_problem 'old run output under code/runs could not be removed'
run_clean=1
if [ "$problems" -eq 1 ]; then
  echo 'WARNING: the pass completed, but a check failed; see the warning above.' >&2
  exit 2
fi
# EXIT publishes before the success heartbeat, including on collection failure.
