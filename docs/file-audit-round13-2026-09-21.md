# File audit, round 13: deployment and disaster recovery

## Scope and evidence

Inspected commit `5e78ae814514115866532bf96f8397d0331354d2`, including the
latest Workday correction and merged B63-B67 fixes. The audit worktree was
fast-forwarded to that commit before claiming this work. No application or
deployment code was changed. No provider requests, production SSH, live
credentials, real credit spending, deployment or public publication occurred.

Read all deployment scripts, units, the backup workflow, and the complete
`prune.py` and `heartbeat.py` modules. Findings B68-B73 concern three scripts.
The coverage inventory below distinguishes execution from source tracing.
There are no priority labels.

Reproducer: `docs/audit-repro-round13-2026-09-21.py`.

```powershell
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round13-2026-09-21.py
```

The script imports the audit worktree's source explicitly. Git Bash executes
the unmodified workstation backup and history-compaction scripts. Every Git
remote is a temporary local bare repository. Compaction's `flock` is stubbed
successful: these tests establish single-process state transitions, not lock
behavior. Store verification uses the real verifier and pruning uses the real
module. Backup SSH is replaced with either a synthetic tar stream or execution
of the constructed remote command on temporary local files. B73 executes
extracted, unchanged startup/publication copy loops, then real quota and pause
checks; it does not execute the whole production pass.

All six cases passed assertions describing the defective behavior. An existing
valid backup is a control for B69 and B70. Existing relevant suites also pass:

| Suite | Discovered | Skipped | Seconds |
| --- | ---: | ---: | ---: |
| `test_backup.py` | 3 | 0 | 2.733 |
| `test_heartbeat.py` | 19 | 1 | 0.783 |
| `test_prune.py` | 9 | 0 | 0.044 |
| `test_prelaunch_fixes.py` | 21 | 7 | 0.091 |

Total: 52 discovered, 44 executed, 8 skipped, no failures. The skips are the
POSIX process-group heartbeat case and seven flock-dependent application
backup cases. These results are local, not VPS measurements.

## B68 - Workstation backup omits live credit reservations and cooldowns

**Location:** `deploy/local/backup-from-vps.sh:39-45`; compare
`deploy/vps/daily-pass.sh:56-58` and `:167-175`.

The remote command snapshots the job index and archives the data checkout.
Actual request reservations and direct-source pauses are written under
`code/.local/`, outside that checkout. Their copies in `data/operational/`
are refreshed by `publish_state` only after collection ends.

**Trigger:** Back up while a collection pass is in progress, or after an
interruption that prevented its publication, then lose the VPS. This is a
supported backup timing: the backup comments explicitly allow a live writer.

**Executed result:** A real temporary runtime quota ledger contains one mocked
request reservation and the runtime source ledger has an active 3,600-second
pause. The published files contain neither. Executing the backup's actual
constructed remote command locally exits 0, copies a valid one-row job-index
snapshot, and installs a backup with zero recorded credits and no source pause.
The live request itself is mocked; no HTTP call occurs.

**Expected:** A successful disaster-recovery copy includes the authoritative
operational state at an identifiable checkpoint. Reservations already sent
must not disappear on restore simply because publication had not happened.

**Impact:** Restoring this apparently successful copy undercounts spent credits
and forgets a refusal. Having an up-to-date, structurally valid job-index
snapshot does not compensate for losing those independent ledgers.

**Fix direction:** Snapshot the authoritative `.local` quota and source ledgers
with SQLite's backup API into the archive's operational paths. Define the
checkpoint relationship to the index and append-only files; use the collection
lock if a single consistent checkpoint is required. Do not copy open SQLite
main files directly or replace live state with older published state.

## B69 - Nonempty corrupt operational files replace both good backup generations

**Location:** `deploy/local/backup-from-vps.sh:58-65` and `:193-204`.

The operational validation is only `-s`. SQLite integrity checks apply to the
derived job-index snapshot, and manifest checks apply to run files; neither
checks these operational files. A damaged application ledger, quota database,
source database or seen snapshot therefore passes validation if nonempty.

**Executed result:** Start with a valid backup. Replace one operational file
with `broken nonempty state` and perform two pulls. Both pulls return 0 and both
`current` and `previous` then hold the invalid bytes. Repeat independently for
all four names:

- `jsearch_usage.sqlite`: SQLite rejects it as a database.
- `source_access.sqlite`: SQLite rejects it as a database.
- `applications.ndjson`: the application's real `read_events` rejects it.
- `seen_jobs.ndjson.gz`: gzip decompression rejects it.

All run-file digests and the job-index integrity check remain valid in these
fixtures. This is separate from B15, which concerned missing run-file digest
validation and is already fixed.

**Expected:** Reject unreadable authoritative state before rotating either
good generation. The failure should retain both generations and `last-pull`.

**Fix direction:** Validate both operational SQLite files and required schema,
parse the complete application ledger using its existing validation rules,
and decompress/validate the seen snapshot before rotation. If a fresh system
legitimately has zero decisions, handle that separately from corrupt content.
Validation establishes readability, not freshness; B68 needs its own fix.

## B70 - Retrying an interrupted rotation deletes the last installed good backup

**Location:** `deploy/local/backup-from-vps.sh:193-204`.

The rotation first deletes `previous.tmp`, moves `current` there, and then
installs the incoming tree. If installation fails, no rollback puts the old
current back. On the next attempt, `previous.tmp` is deleted before the script
checks whether a current generation exists.

**Executed result with injected filesystem failure:**

1. Make the first successful backup: `current` exists, no `previous` yet.
2. Inject a failure only for `mv <incoming tree> backup/current`. The script
   exits 73, leaving the good generation at `previous.tmp`.
3. Repeat the same failure on the next pull. The script first deletes that
   surviving generation and exits 73 again. None of `current`, `previous`, or
   `previous.tmp` remains.

The newly downloaded incoming tree still exists. This test does **not** claim
that every copy of the data is gone; it proves that both failed operations
destroyed the last installed, previously successful recovery generation.
The rename failure is injected, not a measured physical disk failure.

**Expected:** Failed rotation and its retries preserve the last successful
generation. A leftover `previous.tmp` is recovery state, not disposable trash.

**Fix direction:** Recover an interrupted rotation before cleanup, retain the
old generation until the new current is successfully installed, and roll back
on a failed rename. Test interruption at each rename and a second failure
during retry, including the first-backup case without an older `previous`.

## B71 - History compaction can overwrite a newer remote decision

**Location:** `deploy/vps/compact-history.sh:48-55` and `:79`.

The preflight compares local HEAD with the cached upstream ref, without
fetching. It then force-pushes unconditionally. A remote update absent from the
cached ref is invisible to the check and is overwritten. The local collection
lock does not synchronize a different machine or the manual Actions backup.

**Executed result:** Two temporary clones share a temporary bare remote. The
second clone publishes an additional application decision. The first clone's
cached upstream still matches its HEAD. Running the complete compaction script
on the first clone passes its preflight and exits 0. A real local force-push
replaces remote main; the additional decision is no longer in its ledger.

No real repository was rewritten. The initial audit mentioned fresh fetch and
lease protection as a static concern without a numbered finding; this round
promotes that concern to a reproduced data-loss case.

**Expected:** Refuse compaction if remote state has moved, including movement
between the initial comparison and the final push. The script says it refuses
unreconciled local/remote changes before making history permanent.

**Fix direction:** Fetch and reconcile first, capture the exact remote main
OID, and push with an explicit lease against that OID. A lease rejection must
also preserve a usable local branch, which is the separate B72 problem.

## B72 - Failed compaction push leaves the normal pass unable to pull

**Location:** `deploy/vps/compact-history.sh:61-79`.

The script prunes files, creates an orphan commit and replaces local `main`
before confirming that the remote accepts it. A failed push leaves local main
on unrelated history with a different tree, while the remote still has the
original history. There is no failure rollback.

**Executed result:** A fixture contains a current day and a 30-day-old day.
Compaction keeps one day. The temporary remote is configured to reject
non-fast-forward updates, causing the force-push to fail. After removing that
restriction, rerunning compaction exits 1 with `Local and remote differ`.
The ordinary `git pull --ff-only`, used by the daily pass, exits 128 as well.

**Expected:** A publication failure should leave the existing scheduled pass
usable, and correcting the push failure should permit a safe retry. The
completed compaction's documented instruction for *other* clones does not
restore the source VPS after its own unsuccessful publication.

**Impact:** A transient or corrected push problem becomes an ongoing local
history repair requirement. Subsequent daily collection cannot get through its
initial pull. No assertion is made about an actual production outage.

**Fix direction:** Keep the original main and working state until publication
succeeds, construct the candidate on a temporary ref/worktree, and switch the
local main only after successful leased publication. Retain explicit recovery
information if remote success is uncertain. Do not silently reset away local
operational data to make the histories match.

## B73 - A newer published source cooldown is ignored and then erased

**Location:** `deploy/vps/daily-pass.sh:167-183` and `:56-58`.

Startup copies each operational ledger only when its local file is absent or
empty. It checks quota counts afterward, but never reconciles the source pause
ledger. A new refusal recorded by the manually invoked backup workflow can
therefore be ignored when the VPS resumes, even when those two writers never
run concurrently.

**Trigger:** Stop VPS collection, run the documented manual backup collector,
and have a direct source return a refusal with a cooldown extending past the
VPS's next run. The published source ledger is updated. The existing local
source ledger has no pause; quota counts can legitimately remain unchanged.

**Executed result:** With real temporary source and quota databases, execute
the exact startup copy loop. The local source check allows collection while
the published source check refuses it for 3,600 seconds. The real
`ledger_guard.compare` returns true. Execute the publication copy loop: it
overwrites the published ledger, removing its still-active pause as well.

The loops and Python checks were executed; the workflow-to-VPS scenario and
which files they use were source-traced. No production source was contacted,
and the whole VPS script was not run for this case.

**Expected:** A valid cooldown remains binding after switching collectors.
Keeping local quota reservations authoritative does not justify dropping a
newer source refusal published by the other supported execution path.

**Fix direction:** Reconcile source cooldowns monotonically, preserving the
later retry time per source from either ledger before collection. Keep that
separate from credit reconciliation; copying an entire older quota ledger
over the local one would revive already spent credits.

## Coverage inventory

Each file was finished before moving to the next; interface tracing returned
to callers as needed. A row without a new finding is not a proof of safety.

| File / functions or blocks | Inspection and evidence |
| --- | --- |
| `deploy/vps/install.sh`, including `clone_or_update` | Read privilege/packages, account/lock, credential template and helper, clone/fetch/fast-forward, editable install, links, unit enable/restart and installed commit reporting. No root-level install executed. Executable Git modes checked; the backup entry point is executable. |
| `deploy/vps/daily-pass.sh`: `database_inputs` | Read config/history fingerprints, preflight, bootstrap decision and READY lifecycle. Previously recorded rolling-log rebuild risk remains an existing concern, not renumbered here. |
| Same: `publish_state` | Read copies, verification, prune/stage, cursor recovery, seen export, commit, READY and push. B73 copy loop executed. B67 now rewinds both runtime and published cursor ledgers. |
| Same: `report_history_size`, `finish`, top-level flow | Read disk check, pull/seeding, quota check, tests, database, preflight, collection codes, sweep decision, signal and EXIT handling. B73 startup loop executed. Partial-source exit 2 is intentionally a warning on the daily pass. |
| `deploy/vps/backup-applications.sh` | Read lock/missing-ledger behavior, path-only commit, unchanged-ledger handling, outstanding-commit push retry and failure reporting. No new finding. Seven existing flock tests skipped on this Windows host; do not claim those ran. |
| `deploy/local/backup-from-vps.sh` | Read entire script: incoming cleanup, remote snapshot/archive, directory checks, four operational files, snapshot integrity, manifest pairing/digests, rotation and restore output. Whole script executed for B68-B70 and existing backup suite. |
| `deploy/vps/compact-history.sh` | Read entire script: lock, cleanliness/upstream gate, verifier, prune, orphan creation, branch replacement, force push, reflog/gc and recovery message. Whole script executed against disposable local Git remotes for B71-B72; flock stubbed. |
| `deploy/vps/heartbeat.sh`: `heartbeat`, `heartbeat_finish`, `heartbeat_arm` | Read retry isolation, exit-code capture and signal traps. Existing shell contracts pass; POSIX process-group case skipped. |
| All three `.service` and both `.timer` files | Read execution paths, user/environment, working directory, sandbox write paths, restart/timeout and schedule. Source inspection only; no systemd run. |
| `.github/workflows/collect-backup.yml`, every step | Read checkout/restore, setup/tests/bootstrap, collect args and exit codes, sweep, always-save, durable publication/dry-run/recovery, triage artifact and final failure reporting. Supplies the supported state-switch scenario for B73. No GitHub Actions execution. |
| `prune.py`: `day_of`, `plan`, `prune`, `main` | Read matching/shards, cutoff, nonempty safeguard, file removal and CLI. Nine existing tests pass; actual pruning exercised inside B71-B72. |
| `heartbeat.py`: `endpoint`, `ping`, `main` | Read URL selection, acknowledgments, retries, warning behavior and CLI. Existing transport-injected tests pass. No real pings. |

Deferred ideas were not added as bugs merely to increase the count: backup
checks deliberately exempt the primary current-day run digest; the known
rolling-history/bootstrap risk is not new; installer behavior was inspected
but not experimentally exercised under root/systemd; workflow timeout handling
was not inferred to have run on GitHub.

## Source fingerprints

SHA-256 of inspected worktree files (including their checked-out line endings):

| File | SHA-256 |
| --- | --- |
| `deploy/local/backup-from-vps.sh` | `19A9FC90555817BE67184AB6499A0F3178F7052D2C1A558BC687754304801DA1` |
| `deploy/vps/compact-history.sh` | `EBA6616891ABA965866789032154986E708E59C5BF98139E1E1571ECE1195F6E` |
| `deploy/vps/daily-pass.sh` | `52674F60A169269D02ADB144D2F1ECBEAC403FCC6C9C1EDE63954C812B62009F` |

The final fetch still showed main at `5e78ae8`; no business-source changes
occurred during the audit. Next useful scope: complete configuration/catalog
validation and local credential loading, with no provider probing.
