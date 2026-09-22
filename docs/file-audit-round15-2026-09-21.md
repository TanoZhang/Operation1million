# File audit, round 15: identity continuity and recovery

## Scope and evidence

Inspected main `5e78ae814514115866532bf96f8397d0331354d2`. Main and the user
checkout remained unchanged during this round. Earlier audit documents are
preserved on the standing audit branch. No business-code changes, production
database access, provider requests, paid calls or deployments occurred.

This round completes the recovery-path checks begun with the store and
deployment inventories: moved identities, source checkpoints, seen snapshots,
sharded append failure, rescore rollback and replay. It also reads the complete
Review server to check what an unchanged file fingerprint can safely cache.
Application queue and browser callers were traced where these interfaces meet;
this is not a claim of a second complete audit of those two files.

Results: four new reproduced bugs, B81-B84; two remaining paths of previously
reported issues, retaining their original identifiers; one measured optimization
candidate, O10. Existing issues are not counted again as new bugs.

Reproducer: `docs/audit-repro-round15-2026-09-21.py`.

```powershell
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round15-2026-09-21.py
```

The harness imports the adjacent audited source explicitly, uses temporary
SQLite/log/ledger files, and starts Review only on loopback with an ephemeral
port. Dates are computed. No literal historical stamp determines whether a
fixture is sealed. B83 injects an `fsync` error and a next-day clock; it does
not simulate a real power outage or claim a production disk failure.

Existing suites: 193 tests, all passed, no skips:

| Suite | Tests | Seconds |
| --- | ---: | ---: |
| `test_store.py` | 93 | 7.323 |
| `test_applications.py` | 92 | 19.533 |
| `test_seen_durability.py` | 8 | 1.054 |

The store suite's printed `MISMATCH` belongs to its expected negative test;
the suite exited 0. The final reproducer, including strengthened continuity
and historical-decision checks, also exited 0.

## B81 - A moved requisition loses its history when its former URL is reused

**Location:** `src/jobdisco/store.py`, `record_source`, approximately lines
310-329 and 416-438.

B59's fix correctly stops pinning A to its old address when the batch says B
now owns that address. However, it deletes A's old alias and switches to its
new URL without carrying A's existing posting state to the new row. The
subsequent lookup sees no prior row at the new address and inserts it as new.

**Executed case:** A was first seen ten days ago, has a known publication date
and a description requiring five years of professional experience. Later its
board supplies a description-free listing at a new URL, while B takes its old
URL in the same batch.

- Both requisitions survive, so the original B59 disappearance is fixed.
- A's `first_seen` becomes the current pass time.
- A's known `posted_at` becomes null.
- A's retained description disappears.
- The source reports two new postings instead of only the genuinely new B.
- Actual Review eligibility changes from zero postings before the batch to two
  afterward: A is now shown without its previously retained requirement.

**Control:** Feed A's new URL without reusing its old URL first. The existing
canonicalization path retains its original first-seen time, publication date
and description, and it remains excluded by its requirement. Thus the loss
is specific to the newly allowed move-and-reuse branch, not a general policy
of discarding details when a list omits them.

**Expected:** The stable requisition carries its history to its new URL, while
the genuinely new requisition starts its own history at the reused URL.

**Fix direction:** Preserve A's prior row by identity before removing the old
mapping. Use it for metadata continuity and new/existing accounting at the new
URL, while ensuring none of that state contaminates B. Extend B59's permutation
tests to assert timestamps, missing-field fallback, descriptions and counts,
not only which IDs remain present.

## B82 - In-place rebuild replaces a newer rejection with an older snapshot

**Location:** `src/jobdisco/store.py:96-124` (`import_seen`, `_insert_seen`)
and the final snapshot import in `rebuild`.

Seen rows are restored with unconditional `INSERT OR REPLACE`. That is harmless
for an empty destination, but `job-store --rebuild` also replays into an
existing index. An old operational snapshot then overwrites newer local seen
events, including hard rejection decisions that Review relies upon.

**Executed case:**

1. Persist an accepted paid posting and a matching seen row; export the seen
   snapshot.
2. Record a newer `required_experience_over_2_years` decision in the live seen
   table, leaving the prior accepted job row as the collector normally does.
   The actual Review queue correctly hides it.
3. Leave the snapshot at its prior version and call real `store.rebuild(path)`.
4. The seen row's `last_seen` and decision both move backward. The actual Review
   queue contains the posting again: zero before rebuild, one afterward.

The log and manifests verify throughout this fixture. A stale seen snapshot
is a supported operational possibility: daily publication warns and continues
if refreshing it fails. This finding concerns an existing index with newer
evidence, not a fresh machine that has no newer copy available to preserve.

**Expected:** Import must not downgrade newer local seen evidence. A rebuild
must not silently reverse a hard rejection that still exists locally.

**Fix direction:** Merge seen rows using timestamp instants, retaining the
earliest first-seen time and the fields associated with the latest observation.
Define the equal-timestamp rule explicitly. Keep fresh-index restoration and
newer-snapshot updates working; do not simply skip all conflicts.

## B83 - Interrupted sharded rescore leaves history that a successful retry cannot repair

**Location:** `src/jobdisco/store.py:766-796` (`_append_records`),
`:842-861` (`append_scores`), and the rollback in `rescore`.

Recursive append may durably write one sub-batch before a later sub-batch
fails. Sharding moves that completed member to a numbered shard and deletes
the primary manifest. The failed next member is truncated, but its primary log
file remains without a manifest. `describe_day` runs only after the entire
append returns successfully, so it never repairs this partial result.

**Executed case:** Persist 20 valid jobs and their log, then rescore all of
them with a 300-byte synthetic shard threshold. Inject an `OSError` at the
second gzip member's `fsync`.

- The SQLite score transaction rolls back correctly to all original values.
- A completed score member/shard survives, as intended for log-first recovery.
- `verify()` reports `missing-manifest` for the primary day file.
- Advance the mocked clock by one UTC day and repeat the rescore without the
  injected error. It succeeds for all 20 jobs, but the earlier day's integrity
  error remains unchanged.
- Real `rebuild` still refuses the history with a daily-log integrity error.

The threshold is reduced to exercise branching with small fixtures; the
production 90 MB threshold is not exceeded in this test. The error is injected,
not a measured full-disk incident. Unlike B30, the database correctly rolls
back here; it is the surviving log fragments that have no complete recovery
description. Unlike B62, merely making every successful append describe itself
does not cover a partially successful recursive append.

**Expected:** Either roll back the complete append across its new shards, or
leave every surviving durable fragment verifiable before propagating failure.
A successful retry on a later day should not leave recovery permanently gated
on an undocumented manual repair of the previous day.

**Fix direction:** Make partial append recovery explicit, including shard
renames, primary manifest removal and the newly created zero-length file.
Describe or remove surviving primary state on the failure path without
pretending unwritten records were persisted. Test failures after each member,
across shard rollover, and a retry after UTC midnight.

## B84 - Review cache ignores filter configuration changes

**Location:** `src/jobdisco/review.py`, `make_server.current_queue`, lines
101-109; compare `applications.queue`, which calls `jsearch.load_plan`.

The cache key includes the application ledger, index, WAL sidecar and UTC
date, but not the filter configuration. Queue eligibility does depend on that
configuration. A refresh on the same day with no data or decision change can
therefore continue returning the prior rules' result.

**Executed case:** Start the actual Review HTTP server with one eligible RTL
posting and a synthetic TOML plan. Load the queue, then change only the TOML
exclusions to reject `RTL`. A direct call to the actual application queue now
returns zero entries, but GET `/api/queue` still returns the cached one. The
writer connection is held open and the initial WAL lifecycle is allowed to
settle before the rule change, so this is not a sidecar timing artifact.

The fixture redirects the plan loader to a temporary file; the actual project
configuration is untouched. A normal deployment that restarts Review clears
the cache. The bug affects changes while the server remains running, rather
than claiming every deployment is stale.

**Expected:** Refresh uses the current eligibility rules even when no posting
or application decision has changed.

**Fix direction:** Include the loaded filter configuration's version/fingerprint
in the cache dependency key, or invalidate the queue explicitly when its rule
configuration changes. Preserve the existing index/WAL invalidation.

## Previously reported paths still reproducible

These are follow-ups, not B85/B86.

### R02: Review still omits supported description fields

`review.py`'s `/api/job` route lists a small set of top-level description keys.
A real stored record with `raw.content = "Current provider description."`
returns `{"description": ""}` over loopback HTTP. The earlier R02 fixture
used nested `raw.jsearch.job_description`; this is another unsupported display
path under the same description-extraction problem, not a new root cause.

Use a shared display-appropriate extractor that understands supported provider
description fields and provenance, while respecting which payload is current.
Do not dump unrelated metadata or superseded requirements into the description.

### B23/B27: Historical detail still mistakes a replacement for a provider move

The queue now checks identity aliases before letting a decision follow a
provider change. `/api/job` still accepts a different provider plus an equal
cleaned title as sufficient, without consulting those aliases.

**Executed lifecycle:** Discover JSearch ID OLD; append an actual applied
decision; upgrade the posting to direct ID DIRECT-OLD; then replace it at the
same URL with direct ID NEW, retaining the same title. The queue correctly
contains the historic applied group and the new pending group. OLD's alias is
gone. Requesting the old applied group's description with the same parameters
the browser sends nevertheless returns NEW's description, not `replaced: true`.

The existing queue correction works in this fixture. Extend its alias check to
the detail endpoint instead of allowing title equality alone to override a
mismatched historical identity. Preserve legitimate upgrades with matching
aliases as a control.

## O10 - Per-checkpoint manifests repeatedly decompress the whole active day

**Location:** `store.describe_day`, `_file_facts`, and append callers.

The B62 fix correctly creates a manifest after each successful append, but
`_file_facts` rereads the entire compressed file to hash it, then decompresses
the entire file to count records. Repeating that for every small checkpoint
makes accumulated work quadratic in the number of checkpoints within a shard.

**Measured synthetic work:** Twenty one-job checkpoints each add one job and
one source-state event. The final log contains 40 records. Instrumentation of
the actual `_file_facts` calls records decompression counts `2, 4, ..., 40`,
totalling 420 record visits. This is a work-count measurement, not a claim of
a particular VPS wall-clock speedup.

**Optimization direction:** Maintain record count and incremental digest state
while appending within a process, initializing once from existing files and
resetting correctly on rollover. Continue atomically publishing a manifest at
every durable checkpoint. Any optimization needs fault/rollback controls from
B83 so speed does not weaken recovery. Streaming decompression alone does not
remove this repeated work; it only bounds memory.

## Function and interface coverage

| Functions or path | Evidence this round |
| --- | --- |
| `store.record_source`, `replaces_requisition`, `merge_raw`, `slim` | Read the complete preparation/write/alias/closure/state path and metadata handling. B81 plus unchanged-move control. Existing store suite passes. |
| `record_seen`, `export_seen`, `import_seen`, `_insert_seen` | Read complete snapshot lifecycle and conflict handling. B82 drives export, later live decision and actual replay. Eight durability tests pass. |
| `sealed`, `daily_log`, `manifest_path`, `_file_facts`, `_file_digest`, `_write_json_atomic` | Read all boundary/path/digest/write operations. B83 uses computed dates and injected clock; O10 instruments real file facts. |
| `shard_daily_log`, `_append_records`, `append_log`, `append_scores` | Read full rollover, recursion, member writes, fsync and truncate paths. B83 reaches partial success, rollback and subsequent replay refusal. |
| `write_manifest`, `describe_day`, `finalize_manifest`, `refresh_manifest`, `verify` | Read manifest creation/update/seal behavior and integrity gating. B83 and O10; successful append controls remain verifiable. |
| `export_state`, `bootstrap`, `log_lines`, `rebuild`, `rescore` | Read complete recovery ordering, source-state fallback, snapshot import and batched score transactions. B82-B83 execute in-place rebuild; no claim of testing a concurrent live bootstrap replacement. |
| `collector.main.persist`, `seal`, paid query checkpoints | Trace log-before-commit, rollback, state export and finalization. These callers explain which failure paths have an outer seal and which do not. No provider collection this round. |
| `review.slim`, `fingerprint`, `make_server`, `current_queue`, every Handler method, `main` | Read whole server, cache, historical description check, decision serialization, token/Host handling and resource lifetime. B84 and two follow-ups use real loopback GET routes. Existing application suite passes. |
| `applications.queue`, decision snapshots/aliases and rejection selection; browser detail caller | Trace actual queue consequences for B81-B82 and follow-ups. Actual decisions are appended for the historical replacement fixture. Not a complete new audit of these files. |

Previously reported rolling-log retention/rebuild loss is not renumbered. A
potential concurrent bootstrap/WAL interaction was not promoted without an
appropriate platform reproducer. The fixed B59 identity disappearance and B30
score rollback were not described as still broken; the reports above specify
what now works and the separate uncovered contract.

## Source fingerprints

SHA-256 includes checked-out line endings:

| File | SHA-256 |
| --- | --- |
| `src/jobdisco/store.py` | `86DC74C4F65425AE536A7BCBC2D03D4D622E3466E9EC026C116381809F968F3E` |
| `src/jobdisco/review.py` | `C1F427B0DECBE12CAD894048EA33E8E36172C5E154399D785834B01ACBB92065` |
| `src/jobdisco/applications.py` | `37A5F01C94FE923477B3DF31EF7E09283D49F6366B9F247B6DF8C286E2CB8FF7` |

Next scope: provider response-shape and pagination contracts, with the current
Workday and Eightfold fixes as the baseline and offline fixtures only.
