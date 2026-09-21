# File audit, round 11: store lifecycle

## Scope, source versions and verification

Read all functions in `src/jobdisco/store.py`, from migration and identity
handling through logging, sharding, replay, CLI, rescoring and ranking. Five new
root causes are B58-B62. No priorities, business-code edits, production reads,
external collection or real page-credit spending.

The stable baseline is main commit
`79fe1690dee09a7c8d4afc11e1679eb7ae24a6cd`, whose business code is also in
`D:/Operation1million-file-audit`. That worktree contains only audit changes
after the baseline. During inspection, the user checkout at
`D:/Operation1million` acquired uncommitted fixes for round 10 in `collector.py`,
`store.py`, tests and migration `006_source_full_pass.sql`. Those changes were
read without editing or reverting them.

All five new cases reproduce on both the committed baseline and that modified
user source. The user source fingerprints remained unchanged across the final
reproduction and subsequent check; fingerprints are at the end of this report.
The existing suites were run against the stable audit worktree, not against an
in-progress test file in the user checkout:

| Suite | Tests | Time | Result |
| --- | ---: | ---: | --- |
| `test_store.py` | 83 | 5.469 s | exit 0, no skips |
| `test_applications.py` | 92 | 20.068 s | exit 0, no skips |

Total: 175 existing tests pass. The store suite's printed synthetic `MISMATCH`
comes from its negative integrity-check test and is not a production finding.

The new script is `docs/audit-repro-round11-2026-09-21.py`. It uses real store
operations, temporary databases/logs and the reusable round-5 collector helper.
Its HTTP boundary rejects external requests. B62 injects a deterministic UTC
clock transition; B60 reduces the shard threshold to test the same branch with
small fixtures. These are fault and boundary simulations, not VPS observations.

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round11-2026-09-21.py

# Repeat on the committed baseline business code:
$env:PYTHONPATH='D:/Operation1million-file-audit/src'
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round11-2026-09-21.py
```

Locations below refer to the stable baseline; the pending user changes shift
some line numbers. Function names identify the same paths in both versions.

## B58: Slimming discards the only available description

Locations: `store.py:540` (`DROP_FIELDS`), `store.py:578` (`slim`), and
`store.py:345` (`record_source`).

`description_short` and `descriptionTeaser` are removed unconditionally as
duplicate/truncated renderings, although the record may contain no full
description at all. The equivalence check used for duplicate description HTML
does not protect these fields.

Tested a normal `RTL Engineer` row whose only requirement text is:

```json
{"description_short": "5 years of experience required."}
```

Before storage, the real filter returns `required_experience_over_2_years`.
After `record_source`, raw is `{}` and the real Review queue contains one pending
group. The description was not missing from the provider record; the storage
layer deleted it. Historical replay cannot restore text that was removed before
the log was written.

Suggested correction: discard an alternate rendering only when retained content
actually supersedes it. Keep the sole supplied description regardless of its
field name or length. Test the semantic decision before and after slimming.
This is separate from B57: B57 discarded the fetched page during extraction;
B58 discards an already normalized provider field during storage.

## B59: A moved requisition disappears depending on batch order

Locations: `store.py:279` through `store.py:320`, especially canonical URL
rewriting and removal of displaced prepared rows.

Start with requisition A at `/shared`. The next complete batch contains:

- A at its new URL `/new-A`;
- B at the reused old URL `/shared`.

If A is processed first, its identity mapping rewrites `/new-A` back to
`/shared`. B then displaces that prepared A row, so A disappears from the batch
and the store. If B is processed first, it releases the old alias before A is
processed, and both records survive.

Measured through `record_source`, `append_log`, manifest creation and a fresh
database rebuild:

| Order | Live stored IDs | Rebuilt IDs | Source status |
| --- | --- | --- | --- |
| moved A, then replacement B | B | B | complete |
| replacement B, then moved A | A, B | A, B | complete |

Thus the data loss is durable, not just an uncommitted intermediate view.
The two inputs contain identical postings and differ only in ordering.
This is distinct from B18's stale raw blending: the moved opening itself is
discarded after its new address has been overwritten.

Suggested correction: resolve the complete batch's address ownership before
pinning incoming rows to previous canonical URLs. Preserve a live requisition's
new address when another current requisition owns its old address. Add a
permutation test comparing identities and replay results.

## B60: One batch can exceed the daily shard limit

Locations: `store.py:563`, `store.py:693` (`_append_records`).

The writer compresses all records into one gzip member. It may rotate an
existing file before appending that member, but never partitions a member that
itself exceeds `MAX_DAILY_LOG_BYTES`. On an empty day the size check is skipped
entirely because it requires `path.exists()`.

The production threshold is 90,000,000 bytes. The reproducer substitutes 1,024
bytes and writes 12 distinct job records through the ordinary `append_log`
path. Each individual compressed record is below the limit (largest observed:
636 bytes), so splitting at record boundaries is possible. The resulting single
file is approximately 4.4 KB (4,494 bytes in the recorded modified-tree run),
and `verify()` reports `ok` because it validates the digest, not the size bound.

The actual 90 MB threshold was not exceeded during this audit. The tested
defect is the size-independent algorithm: a large append has no splitting path.

Suggested correction: partition records into bounded gzip members/shards and
recheck the destination size between chunks. Define a separate explicit policy
for an individual record larger than the limit. Do not rely solely on rotating
whatever happened to exist before a batch arrived.

## B61: Stale paid requirements override a current direct description

Locations: `store.py:318` through `store.py:342`, `store.py:566` (`merge_raw`).

When a direct record replaces/enriches a paid record for the same URL, raw
fields from both versions are merged. Different provider field names make two
versions of the description look like independent current evidence.

Tested this transition without an application decision:

1. A paid `RTL Intern` record has `job_description` requiring 5 years. Its
   explicit internship title permits storage under the existing policy.
2. The direct source publishes the current `RTL Engineer` with `content`
   requiring 2 years. This direct record alone passes the filter.
3. Storage makes the direct title/provider authoritative but retains both the
   old `job_description` and new `content`.
4. The experience gate takes the older 5-year requirement; the real pending
   Review queue becomes empty.

The retained raw object contains both contradictory versions:

```json
{
  "job_description": "5 years of experience required.",
  "content": "2 years of experience required."
}
```

Suggested correction: retain provenance/history without treating superseded
descriptions as current requirements. Define which provider/version supplies
the active description, and apply that authority consistently to filtering as
well as title and identity. The synthetic test establishes the stale-evidence
path; it does not assert a live employer made this particular edit.

## B62: UTC midnight can leave an appended day without a valid manifest

Locations: `store.py:602` (`sealed`), `store.py:713` (`append_log`),
`store.py:778` (`write_manifest`); the caller uses one run stamp in
`collector.main` and attempts a failure seal.

A pass checks its run stamp at startup, appends and commits source records, and
writes the manifest later. If UTC midnight falls between append and manifest
creation, the same stamp becomes sealed. Both ordinary completion and the
failure-seal path refuse to create its manifest.

The test executes the real collector with one synthetic Greenhouse job:

1. The clock starts at 23:59:59 UTC on the test day.
2. The real append completes, then the clock advances two seconds.
3. Completion raises `Daily manifest is sealed; that day is over`.
4. `verify()` reports `missing-manifest` for the appended day.
5. A fresh `rebuild()` refuses to replay it with a daily-log integrity error.

No process kill or disk fault is required. This fixture starts without an
existing daily manifest. A pre-existing manifest becoming stale is a related
reasoned consequence, not an additional executed case in this harness.

Suggested correction: design manifest finalization and rollover as part of each
durable append/checkpoint, so a source committed before midnight cannot strand
the previous day. Preserve immutable completed days and the distinction between
the UTC log/billing clock and the Pacific daily budget clock; changing either
clock is not the correction.

## Candidate excluded because concurrent work already fixes it

The baseline retains an old ETag after a complete changed response supplies no
validator. The concurrent `record_source` change clears it on complete passes.
The script records both outcomes: baseline selects `conditional` with the old
tag, modified user source selects `full` with no tag. This candidate receives
no new bug number and is not included in the five findings.

The user's round-10 work and migration were preserved. The script also runs
successfully with that migration, so this report is not an artifact of testing
only the older schema. No claim is made that all of the user's pending tests
were run or that their entire patch was reviewed to completion.

## Function coverage ledger

Every listed function was read. Runtime evidence covers the named cases and
existing test suites, not every possible input, OS failure or provider response.

| Functions | Inspection and evidence |
| --- | --- |
| `now`, `migrate`, `connect` | UTC clock, migration/backup and transaction setup; used by all fixtures and existing migration tests |
| `export_seen`, `import_seen`, `_insert_seen`, `record_seen` | Snapshot, batch insertion and conflict behavior read; existing snapshot/rebuild tests pass |
| `load_state`, `plan`, `known_urls` | State/cursor strategy read, including pending reconciliation changes; excluded validator candidate checked on both versions |
| `filter_rules`, `score_row`, `calculate_score` | Read cached versus recomputed scores and hard-exclusion path; existing score tests plus B58/B61 |
| `replaces_requisition`, `record_source` | Read identity mapping, prepared batches, raw authority, duplicate closure, listed-only reopening, closure fuse and state upsert; B59 durable permutation test |
| `touch_source` | Read 304 freshness and source-state updates; existing unchanged-source tests pass |
| `merge_raw`, `slim` | Read dictionary/list handling, provenance merging and dropped fields; B58/B61 |
| `sealed`, `daily_log`, `manifest_path` | Read date/path boundaries; B62 uses actual collector and clock rollover |
| `_file_facts`, `_file_digest`, `_write_json_atomic` | Read hashing, counting and atomic replacement; used by replay/verification fixtures |
| `shard_daily_log`, `_append_records` | Read numbering, manifest transfer, gzip append/fsync and OSError rollback; B60; existing sharding tests pass |
| `append_log`, `append_scores` | Read full snapshots, identities, compact events and source-state events; B59 replay and existing score durability tests |
| `write_manifest`, `refresh_manifest`, `verify` | Read seal checks, manifest metadata and digest coverage; B60/B62 plus existing mismatch tests |
| `export_state`, `bootstrap`, `log_lines`, `rebuild` | Read snapshot fallback, temporary rebuild, stream order, event replay and identity restoration; B59 fresh replay and B62 refused replay |
| `start_run`, `finish_run` | Read run replacement and accounting updates; exercised through the collector fixture |
| `main` and nested rescore `tick` | Read all flags, one-off export, historical manifests, verification and summary behavior; existing CLI tests pass |
| `summary`, `rescore`, `ranked` | Read SQL selection, reader/writer batches, publication-before-commit and ranking; existing application/store tests pass |

Previously reported rolling-history recovery limitations are not renumbered.
The next planned module group is request quota/pacing, ledger/workflow recovery,
then deployment and configuration. The store function inventory is complete
for this pass; it is not a claim that the module has no further defects.

## Source fingerprints

SHA-256 of the two compared versions:

```text
Baseline store.py:
47E10FF21CAFB5CD54372EF370DD9B13C9C81E4518B3E9BDCE4C6C3BFFDFD8D9
Baseline collector.py:
C43C898A7288550AA403440E2BBF0B041E793984A0BF7D03AB2F9D0CAF592387
Modified user store.py:
6815946CE46079C0937C831C98D65DE8FC135DF085CFA1636CCF97D7E805F34C
Modified user collector.py:
9BA1E68BC719660E9535EDEBA470D836D3B221709FBAE4D768D007DA2674DB6D
```
