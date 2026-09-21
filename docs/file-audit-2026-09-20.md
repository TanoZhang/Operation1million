# File audit - 2026-09-20

## Scope and evidence

This is a findings checklist, not a fix. No application code, collection policy,
production data, deployment or schedule was changed.

- Source inspected: `b263553a7fe5ec47cd31c191134de8925a013c52`.
- Main inspected: `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`.
- Final synchronization: 2026-09-20 20:29:29 UTC; main and Claude tips still
  match that SHA. Codex contains this audit claim plus the inspected documentation
  cleanup. Remote inspection cannot reveal another machine's uncommitted work.
- These commits have identical application source; the Codex branch contains
  a separate startup-documentation cleanup. That change and its claim were read.
- The original checkout's uncommitted documentation was preserved.
- Coverage: all 92 tracked paths are accounted for below. Application code and
  operations received static control-flow review; tests received coverage review
  and execution; configuration received parsing/schema checks; documentation was
  checked against executable behavior. Historical handoff entries are evidence,
  not current instructions. This is not a claim that every possible input was tested.
- Existing suite: **405 tests in 69.784 seconds, exit 0, eight skips**. The suite
  imported this worktree's `src`; unmocked `requests.Session.request` calls were
  blocked. Skips cover the real-database audit, POSIX signal behavior and six
  flock-dependent backup cases. No live provider requests or VPS checks ran.
- All tracked Python files parsed; all TOML files parsed; fresh SQL plus all
  migrations passed `foreign_key_check`. The executable catalog contains 35
  companies and 35 queries (10 intern, 10 new_grad, 6 early_career, 9 A), capped
  at 320 pages.
- Nine defects below reproduced with synthetic, offline inputs. The backup
  reproducer uses real local Git repositories and stubs only the uncontended
  `flock` call on Windows. This does not establish production incidence.

Run the retained reproducers from this worktree in PowerShell:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& D:/Operation1million/.venv/Scripts/python.exe docs/audit-repro-2026-09-20.py
```

The assertions deliberately describe the current defects. After fixes, convert
them into regression tests asserting the intended behavior. The script uses
temporary databases and local repositories, never production records.

## Reproduced defects

### B01 - P1: A capped board can retire valid postings

- Location: `src/jobdisco/collector.py:369`, `collect_json`; related final-page
  shortcut in `collect_html:395`. Storage consequence: `store.record_source`.
- Trigger: a Workday page reports four jobs while `max_jobs=3`.
- Expected: partial inventory; no inventory-based closures or new validators.
- Actual: `add` retains three, then `offset >= total` returns `complete` before
  checking the cap. With four previously open jobs, storage closes the fourth.
  Exactly 25% is permitted by the closure fuse, so it does not prevent this.
- Evidence: `B01_cap_false_complete` reports complete, 3/4 retained, one valid
  job closed. The analogous HTML branch is statically identified, not replayed.
- Fix direction: track omitted rows and test cap/truncation before every terminal
  completeness return. Add the same final-page case for each adapter family.

### B02 - P1: An early empty page overrides a contradictory total

- Location: `src/jobdisco/collector.py:346`, `collect_json`.
- Trigger: first page returns three of a reported four jobs; second page is empty
  while still reporting four.
- Expected: incomplete inventory with an explicit count discrepancy.
- Actual: any empty page after page one returns `complete`, enabling the same
  closure/validator path as B01.
- Evidence: `B02_early_empty_page` reports complete with only 3/4 jobs.
- Existing coverage problem: `test_store.py::EmptyBoardTests.
  test_a_blank_later_page_just_ends_pagination` explicitly expects complete for
  one item against a reported count of 99. Its expected behavior needs review.
- Fix direction: retain and reconcile reported totals before accepting an empty
  terminal page; keep no-total endpoints as a separate case.

### B03 - P2: One malformed object discards later valid page entries

- Location: `src/jobdisco/collector.py:304`, `Collector.add` and `normalize`.
- Trigger: a jobs array begins with `null`, followed by a valid posting.
- Expected: quarantine the malformed item, continue with the valid one, mark partial.
- Actual: `normalize` calls `.get` on null; `add` catches only `ValueError`.
  `run` catches the resulting `AttributeError` at source level and stops the board.
- Evidence: `B03_malformed_item_aborts_page` returns failed and zero jobs.
- Fix direction: validate object and field types at normalization boundaries;
  isolate expected provider-data errors without hiding programming errors.

### B04 - P2: "No less than" is mistaken for an upper bound

- Location: `src/jobdisco/experience.py:25,98`, `NOT_A_MINIMUM` / `evaluate`.
- Trigger: `No less than 5 years of professional experience required.`
- Expected: effective experience 5; reject under the protected two-year policy.
- Actual: no experience requirement is recorded and the role passes.
- Evidence: `B04_lower_bound` records null years and an empty rejection reason.
- Fix direction: parse lower-bound idioms before broad denial/upper-bound patterns;
  test both "no less than" and "not less than" against existing ceiling examples.

### B05 - P2: Negated internship language bypasses mandatory experience

- Location: `src/jobdisco/experience.py:39`, `entry_level`.
- Trigger: ordinary RTL role with `This is not an internship. 5 years of
  professional experience required.`
- Expected: no entry override; reject the five-year requirement.
- Actual: entry override is true despite recording five required years.
- Evidence: `B05_incidental_intern` reproduces the bypass.
- Fix direction: distinguish positive role self-description from negation and
  incidental mentions. Preserve explicit genuine intern/new-grad title overrides.

### B06 - P2: A persisted cooldown is checked after a network request

- Location: `src/jobdisco/collection_policy.py:83`, `SourcePolicy.__init__`.
- Trigger: restart with a current 403 pause and an empty robots cache.
- Expected: reject the source before dispatching another request.
- Actual: constructor calls `request_interval` -> `robots_delay` -> GET robots.txt;
  only the later `check` consults the durable pause.
- Evidence: `B06_robots_before_cooldown_check` observes one mocked HTTP request
  before `SourcePaused`. Both collector and validator construct this policy.
- Fix direction: initialize local policy state first, check cooldown, then lazily
  obtain pacing metadata through the guarded request path.

### B07 - P2: Explicit zero totals become "no count"

- Location: `src/jobdisco/collector.py:170`, `reported_total`.
- Trigger: `total=0`, `totalCount=0`, or `totalFound=0` without a fallback field.
- Expected: preserve numeric zero and recognize a validly empty board.
- Actual: boolean `or` chains turn zero into null. The first-page logic reports
  partial with "no count was reported" and does not advance the checkpoint.
- Evidence: `B07_zero_total` reproduces all three shapes.
- Fix direction: select the first present non-null count, not the first truthy one.
  Keep the separate closure fuse intact for a suddenly empty established board.

### B08 - P1: A failed ledger push is never retried on an unchanged ledger

- Location: `deploy/vps/backup-applications.sh:40`.
- Trigger: backup commits a decision, push fails, remote becomes available, and
  the next timer fires without another decision.
- Expected: retry the unpublished commit even with an unchanged working file.
- Actual: clean index causes exit 0 before `git push`; remote remains behind.
  A future successful daily pass can rescue it, but the fifteen-minute backup
  promise does not hold while that pass is unavailable.
- Evidence: `B08_backup_retry`: first exit 1, second exit 0, local and remote
  heads still differ. No external Git remote is used.
- Fix direction: skip only commit creation for unchanged files; still retry push.
  Extend the existing failed-push test to exercise the next timer tick.

### B09 - P2: Fresh-checkout source validation fails when writing its report

- Location: `src/jobdisco/validate_sources.py:357`, `main`.
- Trigger: valid catalog but absent ignored `data/raw/` output directory.
- Expected: create the directory and save the report.
- Actual: validation completes, then `OUT_CSV.open` raises `FileNotFoundError`.
  The command loses the report after doing the network work.
- Evidence: `B09_validator_missing_directory` patches validation and reproduces
  the output failure without making requests.
- Fix direction: prepare the output directory before validation; handle an empty
  source list as well instead of indexing `rows[0]`.

## Additional risks requiring focused validation

- **R01 - P1, automatic rebuild from pruned history.** `daily-pass.sh:183-187`
  bootstraps an existing index when READY is absent or its input hashes differ;
  line 205 removes READY before collection. An interrupted run or catalog edit
  can therefore replace the live index with only the retained fourteen-day log.
  `store.rebuild` cannot recreate old jobs from compact seen/score events. This
  conflicts with the stated protection against automatically shrinking the live
  index after pruning. Static path trace only; no VPS interruption was attempted.
  Validate with an old open posting whose full event has been pruned, then simulate
  a missing READY file. Prefer in-place migration/reconciliation or a full snapshot.
- **R02 - P2, nested descriptions absent in Review.** `store.record_source`
  deliberately places paid enrichment under `raw.jsearch`, and the scorer walks
  nested content. `review.py:84` reads only top-level description keys. A direct
  row with no prose and a nested JSearch description can be scored using text
  the user cannot see. Static finding; add an HTTP fixture for enriched raw data.
- **R03 - P2, Python 3.10 installation contract.** `pyproject.toml:9` advertises
  Python >=3.10, but `tomli` is only in optional `[compat]` at line 22. The documented
  `pip install -e .` path omits it; Python 3.10 lacks `tomllib`, so importing the
  collector/JSearch needs an undeclared default dependency. Metadata/import trace
  only; a clean Python 3.10 install was not performed. Make the conditional
  dependency mandatory or narrow the supported Python version.

## Optimization checklist (not measured speedup claims)

- [ ] **O01: Reuse per-posting analysis.** `jsearch.take` scores at line 651,
  `rejection_reason` can score again, and line 671 calls `experience_debug` again
  after the rejection path has already computed it. Return a single analysis
  result containing score, reason and experience evidence; prove identical output.
- [ ] **O02: Avoid rebuilding the whole queue for every decision.**
  `applications.queue` parses raw descriptions and replays all decisions; POST
  calls it, then the browser fetches the full queue again. Profile first, then
  add a correctly invalidated queue projection or a scoped lookup that preserves
  complete requisition groups and current-rule validation.
- [ ] **O03: Stream history replay.** `store.py:881` expands every line of a gzip
  shard into a list before replaying it. Stream records to bound peak memory,
  while preserving file order, verification, transaction behavior and identities.
- [ ] **O04: Persist completed sources as they finish.** `collector.main` uses
  ordered `pool.map`; a slow first source delays persistence of later completed
  sources. Consider `submit/as_completed`, then explicitly sort presentation
  reports if stable output ordering is required. Test interruption durability.
- [ ] **O05: Measure quota-query indexes.** `RequestGuard.daily_used` scans
  timestamped events and groups lifetime history on each reservation. Evaluate
  `credit_events(at)` and `(period, day)` using query plans and realistic ledgers;
  do not alter either protected clock or reservation-before-dispatch ordering.
- [ ] **O06: Reduce browser work during search.** `app.js` filters the complete
  queue and fetches a description on every render/keystroke. Debounce search,
  cache descriptions by content identity, and abort obsolete requests. Add a
  refresh sequence guard so an older response cannot overwrite newer state.
- [ ] **O07: Strengthen test coverage before more refactoring.** Replace assertions
  that only search source text with behavioral fixtures for critical operations.
  Add B01-B09 to regression coverage, especially B02's contradictory-total case
  and B08's second timer tick. Keep a POSIX run for flock/signal behavior.

## Documentation consistency checklist

**D01 - Verified against local executable configuration, not external services.**
Update active instructions; preserve dated historical observations.

- README still says 52 queries, A-before-intern tier ordering, a daily Actions
  schedule, and a reviewed `runs/latest.json` pointer. Current code has 35 queries,
  intern-first ordering, a VPS timer and no maintained pointer.
- `docs/search-queries.md` and `docs/job-source-collection.md` also say 52 queries.
- `docs/jsearch.md` says 36 queries/seven early-career queries and still describes
  overlapping-window attribution for undated legacy credits. Current behavior is
  35/six and same-date-label attribution.
- `docs/github-actions.md` describes an enabled daily schedule and obsolete
  paid runtime ceilings; the workflow is dispatch-only and uses 6000/3000 seconds.
- `docs/application-review.md` says missing evidence-title descriptions are not
  admitted and reopening requires the 72-hour window. Code retains missing prose
  and allows eligible older jobs in backlog.
- `docs/vps-deployment.md` says bootstrap happens only when the DB is absent;
  the READY/hash branch also triggers it (R01).
- `ats_providers.toml` has descriptive capabilities/readiness entries that do not
  always match implemented adapters. It is not the runtime policy authority;
  label that distinction or derive shared metadata to avoid misleading edits.

## Per-file checklist

Each original tracked path has one row. "No new finding" means none identified
within the review method shown, not proof of correctness. Tests were inspected
for covered behavior and executed; no claim of exhaustive line-by-line proof is made.

| File | Review / result |
| --- | --- |
| `.env.example` | Credential template: blank values only; no new finding. |
| `.gitattributes` | Shell/service/timer LF policy checked; no new finding. |
| `.github/workflows/collect-backup.yml` | Dispatch-only workflow, paid opt-in, checkpoint/cursor paths reviewed; D01; timeout headroom needs operational measurement. |
| `.gitignore` | Derived data and secrets excluded; no new finding. |
| `AGENTS.md` | Startup rules and protected invariants read; separate cleanup preserved. |
| `CLAUDE.md` | Shared rulebook and virtualenv/test instructions checked; no new finding. |
| `CONTEXT.md` | Domain vocabulary reviewed; no behavioral finding. |
| `README.md` | Active setup and execution claims checked; D01, R03. |
| `data/config/ats_providers.toml` | TOML parsed; adapter metadata compared with runtime dispatch; D01. |
| `data/config/discovery_queries.toml` | TOML parsed; no configured company fallbacks; no new finding. |
| `data/config/jsearch_queries.toml` | Parsed and load_plan validated; 35 queries, 320 pages; no policy changes proposed. |
| `data/config/migrations/001_search_queries.sql` | Executed after fresh schema; legacy catalog compatibility tests pass. |
| `data/config/migrations/002_job_store.sql` | Schema, indexes and status constraints reviewed; fresh execution passes. |
| `data/config/migrations/003_job_identities.sql` | Scoped identity keys and replay use reviewed; tests pass. |
| `data/config/migrations/004_relevance.sql` | One-time ALTER guard and relevance index reviewed; tests pass. |
| `data/config/migrations/005_seen_jobs.sql` | Independent seen table and snapshot columns reviewed; tests pass. |
| `data/config/schema.sql` | Executed in fresh in-memory DB; 35 companies; foreign_key_check clean. |
| `data/config/sources_search.toml` | Endpoint/header and one-page transport contract checked; no new finding. |
| `deploy/local/backup-from-vps.sh` | Transfer, SQLite snapshot, validation and rotation reviewed; existing fixtures pass; no live SSH test. |
| `deploy/vps/backup-applications.sh` | Commit/push retry path reviewed and reproduced; B08. |
| `deploy/vps/compact-history.sh` | Lock, prune and history rewrite reviewed statically; consider fresh fetch and explicit lease instead of unconditional force push. |
| `deploy/vps/daily-pass.sh` | Lifecycle, publication and READY recovery reviewed; R01; no VPS execution. |
| `deploy/vps/heartbeat.sh` | Exit/signal contract reviewed; Windows-compatible fixtures pass, POSIX signal case skipped. |
| `deploy/vps/install.sh` | Update lock, fast-forward, virtualenv and units reviewed statically; no deployment performed. |
| `deploy/vps/jobdisco-backup.service` | User, environment, timeout and writable paths checked; B08 in invoked script. |
| `deploy/vps/jobdisco-backup.timer` | 15-minute schedule checked; retry guarantee depends on B08. |
| `deploy/vps/jobdisco-collect.service` | Three-hour timeout and shared pass entry point checked; R01. |
| `deploy/vps/jobdisco-collect.timer` | 04:38 Pacific matches budget configuration; no new finding. |
| `deploy/vps/jobdisco-review.service` | Loopback review, source tree, DB and ledger write paths checked; no new finding. |
| `docs/agent-protocol.md` | Main and remote Codex claims compared; this audit claimed separately. |
| `docs/agents/domain.md` | Vocabulary/documentation guidance read; no new finding. |
| `docs/agents/issue-tracker.md` | Issue conventions read; no external issues/messages created. |
| `docs/agents/triage-labels.md` | Label mapping reviewed; no new finding. |
| `docs/application-review.md` | Compared with queue/filter/backlog behavior; D01. |
| `docs/architecture.md` | Module map, protected choices and existing bug log read; R01 conflicts with recovery protection. |
| `docs/collection-rules.md` | Pacing, empty-board, cap and isolation contracts checked; B01-B03, B06-B07. |
| `docs/github-actions.md` | Compared with current workflow; D01. |
| `docs/handoff.md` | Newest section read; historical findings cross-checked against merged source, not treated as open bugs. |
| `docs/job-source-collection.md` | Active behavior and historical notes distinguished; B03 and D01. |
| `docs/jsearch.md` | Budget/cycle contracts checked against executable plan; D01. |
| `docs/public-overview/.gitignore` | Public publication allowlist checked; unchanged. |
| `docs/public-overview/README.md` | Concept-only boundary checked; status is historical/planned, not a current deployment report; unchanged. |
| `docs/publication-policy.md` | Private/public boundaries read; no public publishing performed. |
| `docs/search-queries.md` | Active query count checked; D01. |
| `docs/vps-deployment.md` | Compared with timer, installer, backup and READY behavior; D01, R01. |
| `pyproject.toml` | TOML parsed; package/dependency/entry-point review; R03. |
| `requirements.txt` | Editable compat installation checked; differs from README default install (R03). |
| `src/jobdisco/__init__.py` | Package/version metadata reviewed; no new finding. |
| `src/jobdisco/applications.py` | Identity replay, grouping, ledger locking and filtering reviewed; O02. |
| `src/jobdisco/collection_policy.py` | Cooldown order, Retry-After and pacing reviewed; B06. |
| `src/jobdisco/collector.py` | Adapters, normalization, pagination, caps, checkpoints and CLI reviewed; B01-B03, B07, O04. |
| `src/jobdisco/experience.py` | Experience clauses, overrides and optional sections reviewed; B04-B05. |
| `src/jobdisco/heartbeat.py` | Endpoint and nonfatal retry contract reviewed; tests pass. |
| `src/jobdisco/job_text.py` | Title/suffix normalization and callers reviewed; tests pass. |
| `src/jobdisco/jsearch.py` | Plan, transport, filtering, sweep cursor and per-page durability reviewed; O01. |
| `src/jobdisco/jsearch_access.py` | Atomic reservations, cycle/day split and cooldowns reviewed; tests pass; O05. |
| `src/jobdisco/ledger_guard.py` | Current-cycle comparison and missing-ledger handling reviewed; tests pass. |
| `src/jobdisco/local_config.py` | Supported-key loading and environment precedence reviewed; no new finding. |
| `src/jobdisco/paths.py` | Repository-relative runtime/config paths reviewed; deployment assumes editable/source checkout. |
| `src/jobdisco/prune.py` | Whole-day retention and operational exclusions reviewed; tests pass; recovery interaction R01. |
| `src/jobdisco/query_catalog.py` | Legacy migration backup and read-only query access reviewed; tests pass. |
| `src/jobdisco/ranking.py` | Band/date/score ordering and deliberate day precision reviewed; tests pass. |
| `src/jobdisco/review.py` | Host/token checks, projection, read/write routes reviewed; R02, O02. |
| `src/jobdisco/review_static/app.js` | Escaping, safe links, selection, async detail guard and refresh reviewed; O06. |
| `src/jobdisco/review_static/index.html` | Control IDs, labels, dialog and payload contract checked; no browser accessibility audit. |
| `src/jobdisco/review_static/style.css` | Responsive rules and band classes reviewed; consider consolidating repeated override blocks; no browser visual QA. |
| `src/jobdisco/store.py` | Identity, closure fuse, logging, sharding, verification, replay and scoring reviewed; B01/B02 consequence, R01, O03. |
| `src/jobdisco/validate_sources.py` | Request construction, extraction, cooldown and report path reviewed; B06, B09. |
| `src/jobdisco/workflow_state.py` | Cursor rollback preserves charges/cooldowns; tests pass. |
| `tests/test_applications.py` | Coverage review + suite: Identity, replay, backlog, HTTP fixtures pass; add nested enrichment description fixture (R02). |
| `tests/test_backup.py` | Coverage review + suite: Local-copy validation/rotation fixtures pass; no production restore test. |
| `tests/test_collect_sql_sources.py` | Coverage review + suite: Existing pagination/normalization fixtures pass; add final-page cap and non-object record cases (B01/B03). |
| `tests/test_collection_policy.py` | Coverage review + suite: Existing pause/pacing fixtures pass; constructor robots is mocked, leaving B06 uncovered. |
| `tests/test_exclusion_alternation.py` | Coverage review + suite: Synthetic equivalence passes; real collected-database comparison skipped. |
| `tests/test_experience.py` | Coverage review + suite: Existing cases pass; add negated internship and lower-bound idioms (B04/B05). |
| `tests/test_heartbeat.py` | Coverage review + suite: Delivery/exit fixtures pass; POSIX signal case skipped. |
| `tests/test_jsearch.py` | Coverage review + suite: Existing plan, transport, paging and cursor fixtures pass; O01 equivalence must retain these. |
| `tests/test_jsearch_access.py` | Coverage review + suite: Budget windows/reservations/concurrency fixtures pass; preserve two-clock contract. |
| `tests/test_ledger_guard.py` | Coverage review + suite: Missing/stale/current ledger fixtures pass; no provider account reconciliation performed. |
| `tests/test_prelaunch_fixes.py` | Coverage review + suite: Six flock-dependent backup cases skipped; failed-push case lacks next-tick retry (B08); source-text assertions noted (O07). |
| `tests/test_prune.py` | Coverage review + suite: Retention fixtures pass; add end-to-end READY recovery test (R01). |
| `tests/test_queue_cache.py` | Coverage review + suite: Per-call cache equivalence fixtures pass; no cross-request cache currently tested (O02). |
| `tests/test_ranking.py` | Coverage review + suite: Band, date and stable-order fixtures pass; no new finding. |
| `tests/test_review_payload.py` | Coverage review + suite: Projection/JS field contract passes; does not test browser request races (O06). |
| `tests/test_review_rules.py` | Coverage review + suite: Hard reject, evidence and queue filtering fixtures pass; D01 contradicts current expectations. |
| `tests/test_search_queries.py` | Coverage review + suite: Legacy migration/schema equivalence fixtures pass. |
| `tests/test_seen_durability.py` | Coverage review + suite: Snapshot replay fixtures pass; production counters not checked. |
| `tests/test_seen_jobs.py` | Coverage review + suite: Identity/upsert/decision fixtures pass. |
| `tests/test_seen_publication.py` | Coverage review + suite: Verified/dry-run/failed-verification shell fixtures pass. |
| `tests/test_store.py` | Coverage review + suite: Existing tests pass; B02 is encoded as expected behavior; B01/B07 gaps; R01 wrapper not covered. |
| `tests/test_validator_resources.py` | Coverage review + suite: SQLite closure fixture passes; no fresh output-directory case (B09). |
| `tests/test_workflow_state.py` | Coverage review + suite: Rollback and paid sweep opt-in fixtures pass. |
