# Second offline audit - 2026-09-20

This supplements [the first audit](file-audit-2026-09-20.md). The user is fixing
the first findings. This pass changes only audit documentation and its standalone
reproducer; it does not change production code or compete with those fixes.

Inspected base: `a7572bec2e09b14506b7fd42152414c809d2d465`. Its application source
is identical to inspected main `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`.
At the 2026-09-20 23:43:35 UTC synchronization, main and Claude still had that
SHA; Codex held the earlier documentation and this audit's claim. Other machines'
uncommitted changes are not visible through remote Git references.

Final synchronization at 2026-09-20 23:46:21 UTC found no new main/Claude commits.

## Results

- Seven new defects, B10-B16, reproduced offline.
- First-audit risk R02 is now reproduced over loopback HTTP, not counted as a new finding.
- Two additional optimization candidates have measured synthetic results.
- Existing suite rerun: 405 tests in 65.320 seconds, exit 0, eight environment
  skips; all executed tests passed. Imports were pinned to this worktree's `src`,
  and unmocked `requests.Session.request` calls were blocked. Skips remain the
  collected-database audit, one POSIX signal case and six flock-dependent tests.
- The complete round-two reproducer was rerun successfully after adding verified
  prior-generation fixtures to the backup scenario. `git diff --check` passed.
- No provider requests, paid credits, production writes or deployments occurred.
  HTTP transport is mocked except for the temporary local Review server. Backup
  transfer uses a local tar stream in place of SSH.

Reproducer: [audit-repro-round2-2026-09-20.py](audit-repro-round2-2026-09-20.py).
Run from this worktree:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& D:/Operation1million/.venv/Scripts/python.exe docs/audit-repro-round2-2026-09-20.py
```

Assertions describe defects present at the inspected source revision. They are
not acceptance tests for fixed code; convert them to expected-behavior regression
tests when implementing fixes. All state lives in temporary directories.

## New defect checklist

### B10 - P2: Upgrading a JSearch row to its direct source loses its decision association

- Files: `applications.py:20,139-148`; `store.py:record_source`.
- Trigger: collect one URL through JSearch, mark it applied, then collect the
  same URL from Ashby with its direct requisition ID.
- Expected: the explicit alias relation retained by storage lets Review preserve
  the existing decision for the same opening.
- Actual: storage retains both `(jsearch, search-1)` and `(ashby, fixture,
  direct-1)` identities at the URL, but Review checks only the row's current
  provider/ID. The opening appears simultaneously in applied and pending.
- Reproducer result: `B10_provider_upgrade_loses_decision`: pending=1, applied=1,
  two recorded aliases; before the provider upgrade pending was empty.
- Impact: previously handled openings return as work and can be applied to again.
  The decision ledger itself remains intact.
- Fix direction: resolve decisions through authoritative scoped identity aliases,
  or persist a provider-independent requisition key. Do not restore unconditional
  URL fallback: that would reintroduce the already-fixed URL-reuse bug. Test both
  provider upgrade and true requisition replacement at the same URL.

### B11 - P2: Rescoring is undone by rebuilding the index

- File: `store.py:1087-1110`, `rescore`, and the replay path.
- Trigger: a durable job event carries score 99, `--rescore` corrects its current
  index score to 0, then a fresh index is rebuilt from that history.
- Expected: the corrected interpretation survives recovery, either as a durable
  score event or as version-aware recomputation under current rules.
- Actual: `rescore` commits only SQLite updates; replay trusts the old non-null
  score in the event. The new index contains 99 again.
- Reproducer result: `B11_rescore_not_durable`: after_rescore=0, after_rebuild=99.
  The fixture uses the existing supported stale embedded-score scenario.
- Impact: Review's evidence gate and ranking can revert after recovery. This is
  separate from first-audit R01's loss of old rows after a pruned rebuild.
- Fix direction: wire the existing `append_scores` helper into a complete durable
  operation, including manifest updates and failure handling, or version stored
  scores and recalculate stale versions. Do not rewrite sealed historical logs.

### B12 - P2: An invalid paid job ID aborts a page before valid results are checkpointed

- File: `jsearch.py:188-195,738`, `page_identity`.
- Trigger: a successful paid response contains a list/object `job_id` alongside
  an otherwise valid posting.
- Expected: isolate the malformed record, record its count, persist the valid
  posting, retain the already-spent credit, and report partial data.
- Actual: the set comprehension raises `TypeError: unhashable type: 'list'`
  before `take`, `record_seen` or `checkpoint` can process the page. The exception
  escapes the paid collection loop.
- Reproducer result: `B12_paid_malformed_id_loses_page`: credits=1,
  checkpoint_calls=0, seen_calls=0.
- Impact: a single bad ID loses valid results on that page and aborts later
  queries. This is the paid-page fingerprint boundary, distinct from B03's direct
  adapter normalization failure. Credit reservation itself behaves correctly.
- Fix direction: validate scalar identity types before fingerprinting and
  normalization; an uncomparable page should not crash the run. Test null, list,
  object and missing IDs together with valid records.

### B13 - P2: A conditional probe changes a POST listing request into GET

- File: `collector.py:495-502`, `Collector.run`.
- Trigger: a completed Workday source has a saved ETag, so `store.plan` selects
  conditional mode. Its listing endpoint requires the POST described by
  `request_for`, but rejects GET with 405.
- Expected: use validators only for the correct resource, method and body, or
  restrict conditional mode to adapters that explicitly support it.
- Actual: `self.fetch(request_for(self.source)[0])` discards both method and body.
  The GET receives 405, and the source is paused for at least 24 hours.
- Reproducer result: `B13_post_validator_uses_get`: method=GET, status=paused.
- Evidence limit: synthetic endpoint behavior; no claim that a current live
  Workday board emits the triggering ETag. The reachable method mismatch is
  established by code and fixture.
- Fix direction: adapter-specific conditional capability, including validator
  resource identity. Merely keeping POST is insufficient if a first-page ETag
  is later interpreted as proof that every page of the board is unchanged.

### B14 - P2: One idle connection blocks the entire Review server

- File: `review.py:118`; the handler also has an unbounded body read at line 106.
- Trigger: connect to loopback and leave that socket idle; another client sends
  a complete ordinary GET request.
- Expected: the second client can load Review, or the idle connection expires
  within a bounded timeout.
- Actual: single-threaded `HTTPServer` waits for the first socket indefinitely.
  The second request remains unanswered until that socket is closed.
- Reproducer result: `B14_idle_socket_blocks_review`: second request times out
  while the first socket is held, then returns 200 after it closes. Acceptance
  of the first connection is synchronized with an event, not guessed by a sleep.
- Impact: an idle or stalled browser/tunnel connection can freeze all Review
  users without stopping the service process.
- Fix direction: bounded connection/read timeouts and concurrent request serving;
  retain ledger locking and add concurrent-write tests if using ThreadingHTTPServer.

### B15 - P1: Backup validation accepts mismatched content and rotates away recovery copies

- File: `deploy/local/backup-from-vps.sh:97-145`.
- Trigger: all run/manifest names match and the SQLite snapshot is valid, but a
  compressed log's bytes differ from the hash in its manifest.
- Expected: reject the incoming backup before replacing retained generations.
- Actual: validation checks counts and matching names, not manifest hashes.
  It returns success and rotates the unverifiable copy into current.
- Reproducer result: `B15_backup_accepts_checksum_mismatch`: two consecutive
  backup runs exit 0; `store.verify` reports MISMATCH; both previously retained
  fixture generations, whose log checksums passed verification, have been replaced.
- Impact: the script can mark an unrebuildable event history as a good backup.
  A concurrent remote write between copying a log and its manifest is one possible
  trigger, but that production race was not exercised here.
- Fix direction: verify every referenced digest before rotation, reject orphaned
  or missing files, and capture a coherent remote snapshot. Validate operational
  ledgers and the decision-log tail too; a nonempty file is not integrity evidence.
- This is a new missing integrity check, not a repeat of the already-fixed failure
  to abort rotation when existing validation detects a bad filename or snapshot.

### B16 - P2: Paid request totals count queries instead of requests

- File: `collector.py:878-884`, `persist_query`; aggregate consumers include
  `finish_run` and `write_manifest`.
- Trigger: one JSearch query fetches two pages.
- Expected: its source report contains two requests, matching actual dispatches.
- Actual: `count = 1 if detail['pages_used'] else 0` reports one regardless of
  page count. Run/manifest request totals derived from these reports undercount too.
- Reproducer result: `B16_query_request_count_underreported`: the collector CLI
  path dispatches two mocked HTTP calls, while company_results.csv reports one.
  The aggregate consumers' consequences are traced in code, not separately replayed.
- Impact: operational request statistics disagree with the correctly recorded
  page-credit ledger. This is a reporting error, not an underbilling bug.
- Fix direction: report per-query dispatch/page totals under the one-page request
  contract; verify sum-of-source requests against guard attempts, including failures.

## Prior risk confirmed

**R02 - P2, nested descriptions missing in Review.** A stored record with
`raw.jsearch.job_description = "Design RTL and verify hardware."` is readable
by the scoring text extractor, but GET `/api/job` returns an empty description.
The loopback fixture `R02_confirmed_nested_description` now establishes the
previous static finding. Use a shared, display-appropriate description extractor
that understands enriched payloads; do not dump all raw metadata into the UI.

## Additional measured optimization candidates

### O08 - Index the duplicate-identity lookup used for every incoming job

`store.py:385` checks jobs by provider and source_job_id for each pending identity.
The current schema has no jobs index on that pair. The JSearch form has no company
predicate and its query plan is `SCAN jobs`. A provider's own board can instead
scan all of that company's open rows repeatedly through `jobs_open`.

Synthetic measurement: 5,000 rows, 500 queries, identical result lists:

| Query | Time | Plan |
| --- | ---: | --- |
| Current schema | 0.078467 s | SCAN jobs |
| Experimental partial index | 0.000601 s | SEARCH by provider_key and source_job_id |

The experiment used `(provider_key, source_job_id, company_key, url) WHERE
closed_at IS NULL`, only inside a temporary database. Evaluate an appropriately
sized covering/partial index in a migration and measure write overhead as well.
This is a local query measurement, not a production pass speedup estimate.

### O09 - Avoid HTML parsing for titles containing neither markup nor entities

`collector.py:68` creates BeautifulSoup for every `clean` call, including ordinary
plain-text titles. An experimental fast path uses the existing parser when `<`
or `&` occurs and otherwise returns the stripped string.

Synthetic measurement: 6,000 inputs mixing plain titles, padding, entities,
markup, empty strings and nulls; output lists were identical:

| Variant | Time |
| --- | ---: |
| Existing clean | 0.099769 s |
| Experimental fast path | 0.041396 s |

These six repeated input shapes are not broad provider-data equivalence proof.
Before adopting the fast path, compare real retained titles and add Unicode,
whitespace, malformed markup and entity cases. No source change was made here.

## Suggested implementation order

1. B15: protect retained recovery copies before adding more backup behavior.
2. B10 and B11: preserve identity decisions and corrected scores across transitions.
3. B12 and B13: harden collection boundaries without spending real credits.
4. B14 and the confirmed R02: keep Review responsive and show available descriptions.
5. B16 and O08/O09: correct reporting, then measure and apply performance changes.

Keep B01-B09 and the first audit's other risks on their existing checklist.
This document does not claim those have been fixed or reverified on another branch.
