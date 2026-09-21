# Systematic function audit: text to Review

This pass follows files in order and records every function before moving to the next file. It covers the text-to-Review path, not the entire repository. Ten new root-cause findings are reproduced, B34-B43. Existing B27 is rechecked separately and is not counted again. No business code was edited.

## Version and test method

Audit lineage: `7ecafb4a4494c9b6011c102b7156723e09465323`, claim `647d3cb`. Initial main/claude: `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`. Executable diagnostics import the user's source at `D:/Operation1million/src`, not the older business code in the audit worktree. During this audit the user's fixes were committed and merged. Final fetch found main/claude at **`005766ee0630464f99fe815e42e472ef0740e379`**; comparison of all six audited files against that commit showed no differences. The final fingerprints and reproduced findings therefore also describe those files at this main commit. The latest handoff and the intervening source changes were inspected before reporting.

Final inspected file fingerprints (SHA256):

| File | Fingerprint |
| --- | --- |
| experience.py | 709CF09DC122E80A737FED202FD9F8D21FF0AFF570F701D5C5AB66C48CDA70D7 |
| job_text.py | 0E6CFF8BFA7A6624F45B4A8021593E77A3A6A7F879213EA49C9EF884175C4A55 |
| ranking.py | 0F5A5522519DFB53C62A60F155763038C87CFE5064401AF7F6AB1803F8FC724D |
| applications.py | 61E6FEFE7DAB911448BC738DFE95EE99DE20D1C13118355F426BA989BB38CA94 |
| review.py | CC288B9F3E229DF3B143C84F72BE4D2A08B4AA29DA956A7884DDE36865694CC5 |
| review_static/app.js | 69DDA85B47F8B696BF390A843808182CB912D9CE1E47A75C66912F1D2D2F126A |

Tests use synthetic postings and temporary databases, logs and decision ledgers. Provider transport is blocked or mocked; Review HTTP tests use loopback. Frontend tests execute the unchanged `app.js` in Node with a small DOM harness and controllable fetch promises. They verify JavaScript state transitions, not browser layout or accessibility. No external collection, paid charge, live-data write or deployment occurred.

The diagnostic script passes all ten defect assertions and its positive/negative controls. Related existing tests are run separately: `test_experience`, `test_review_rules`, `test_ranking`, `test_applications`, `test_review_payload`, and `test_queue_cache`. Final result: **164 tests in 16.577 seconds, exit 0, no skips; all six source hashes stable during the run**. The earlier 154-test run was superseded after the user's ongoing test additions. The local validation log is `.local/round8-targeted-tests.txt`. A passing existing suite does not establish that the new cases are correct: these cases were missing from its expectations.

## Function coverage, in inspection order

"Checked" below means the whole function was read, its callers traced, and the listed boundaries exercised or explicitly reasoned about. It does not mean every possible input has been exhausted.

### 1. experience.py

| Function | Boundaries and callers checked | Result |
| --- | --- | --- |
| entry_level | Title overrides; role statements versus past internship experience; supervising and denying internships; called by evaluate and paid/Review filtering | B35; supervising and preceding-denial controls pass |
| evaluate | Required/preferred clauses and sections; upper/lower bounds; BS/MS alternatives; independent requirements; non-work durations; negation placement; slash location; actual collector and queue | B34, B36; 14 control combinations pass; earlier numeric/heading findings remain separately numbered |

### 2. job_text.py

| Function | Boundaries and callers checked | Result |
| --- | --- | --- |
| clean_title | Unicode/whitespace normalization; posting suffix; known location/country aliases; title words without location; suffix order; repeat application; direct row to Review | B37; five normal-form controls pass |

### 3. ranking.py

| Function | Boundaries and callers checked | Result |
| --- | --- | --- |
| bucket | Core, related, unrelated, internships, SOC security exception | Controls pass |
| summarize | Every band counted exactly once; total preserved | Controls pass |
| posted_day | ISO day, timestamp, text date, empty and invalid dates | Controls pass |
| _seconds | UTC same-day second ordering; called only as ranking tie-break | Controls pass for normal writer-produced UTC stamps |
| rank | Empty groups, publication versus discovery fallback, band/date/score/tie order | Diagnostic and existing tests pass |
| order | Empty input, reversed input, stable deterministic ordering | Controls pass |

No new ranking defect is asserted. Offset-bearing legacy discovery timestamps and visual browser date presentation are not conflated with the normal UTC writer path; B41 belongs to frontend date parsing.

### 4. applications.py

| Function | Boundaries and callers checked | Result |
| --- | --- | --- |
| ledger_path | Environment-selected root versus default | Control passes |
| decision_key | Company-scoped direct IDs and provider-wide paid IDs; stable queue/replay use | Controls pass |
| locked | Existing ledger and lock/read/append lifecycle; existing concurrency tests | Controls pass on this Windows host; POSIX lock internals not exercised here |
| read_events | Missing file, complete events, incomplete tail and preservation of evidence | Controls pass; arbitrary malformed snapshot schemas were not fuzzed exhaustively |
| append_decision | Apply/reopen append-only replay; reason/status validation and concurrent-write tests | Controls pass |
| queue and nested decision_for/verdict/collect_into/label/undecided | Pending/backlog/history, filter replay, identity transitions, later rejection, query-scoped rejection overwrite, ledger history | B38; existing B27 still reproduces for a same-title replacement |

The new company/title restriction in `moved_states` does not resolve B27 when the replacement has the same company and title. The script verifies A applied through JSearch, direct B, then unrelated direct C at the same address: C remains hidden. This is an outstanding instance of B27, not a new issue number.

### 5. review.py

| Function | Boundaries and callers checked | Result |
| --- | --- | --- |
| slim | Queue field projection and token/labels addition via real endpoint | Controls and payload tests pass |
| make_server | Loopback binding, startup, shutdown, temporary ledger | Controls pass |
| Handler.log_message / send | Real requests, JSON, static asset MIME and no-store header | Controls pass |
| Handler.do_GET | Queue, description, actual identity replacement versus provider alias, plaintext templates, forbidden Host and missing routes | B39, B40; 403/404 controls pass |
| Handler.do_POST | Missing token, malformed payload, missing group, authorized append/replay | 403/400/409/200 controls pass |
| main | Missing-index CLI refusal; KeyboardInterrupt cleanup with a server double | Controls pass; systemd deployment is outside this pass |

### 6. review_static/app.js

| Function/callback group | Boundaries checked | Result |
| --- | --- | --- |
| band, bandLabel, bandChip, flagChip, bandSummary | Normal server bands, missing labels, rendering of groups | Exercised by rendering controls; no new finding |
| $, escapeText, safeLink | Selector access, HTML escaping, rejected javascript URL | Controls pass |
| date, postedToday, postedLabel | Calendar-only date versus timestamp in Pacific time | B41 |
| error, api | HTTP error JSON and visible error state | Control passes |
| refresh | Two concurrent queue requests resolving in reverse order | B42 |
| filtered, render | Search/no match, selection, pagination and show-more callback | Controls pass; selection mutation contributes to B43 |
| renderDetail | Old/new detail responses, replacement message, Skip click callback | Existing detail-generation guard passes; B43 |
| decide and skip-form submit | Decision identity captured when submitting versus when opening modal | B43 |
| Tab/search/refresh/cancel callbacks | Tab switching, search reset, busy-tab guard, dialog cancellation | Controls pass |

`index.html` IDs, dialog structure and script wiring were read against these selectors. `style.css` was read for structure only; no browser viewport/layout audit is claimed. Tests do not substitute for that separate visual check.

## New findings

### B34 - A trailing denial is read as a mandatory minimum

**File/function:** `experience.py`, `evaluate`, matching context around a year expression.

**Trigger:** `2 years experience required. 5 years experience is not required.`

**Expected:** the mandatory minimum is two; the five-year statement explicitly denies a requirement.

**Observed:** effective years become five, paid discovery rejects it and Review has zero pending groups. `3 years experience not necessary` demonstrates the same postfix-denial root cause. The parser only checks denial/upper-bound words before the number.

**Fix direction:** bind negation on either side to its year requirement, preserving controls such as `no less than 5 years`. Do not globally discard a sentence merely because it contains a negative word.

### B35 - Past internship experience is treated as an internship opening

**File/function:** `experience.py`, `entry_level`.

**Trigger:** `Candidates must have prior internship experience. 5 years experience required.` An additional variant is `5 years experience required, including internship experience.`

**Expected:** neither statement says the advertised role is an internship. The explicit five-year minimum still applies.

**Observed:** `entry_override=true`; the five-year requirement is detected but bypassed, and the posting is stored and shown in Review.

**Fix direction:** distinguish the role being offered from the candidate's past experience. The preceding supervisor/denial guards already tested do not cover this case. This is a separate reference-to-experience case, not a renumbering of B05's negated internship wording.

### B36 - A slash in a skill name invents a BS/MS alternative

**File/function:** `experience.py`, `evaluate`, `explicit_alternative` and degree aggregation.

**Trigger:** `BS with 5 years experience and MS with 2 years experience in RTL/FPGA design required.`

**Expected:** a slash joining skill names must not change the meaning of the degree/experience conditions joined by `and`.

**Observed:** with `RTL/FPGA`, effective years are two and the posting is accepted. Replacing only that skill text with `RTL and FPGA` makes effective years five and rejects it. The implementation treats any `/` or `or` anywhere in the block as evidence that BS/MS requirements are alternatives.

**Fix direction:** locate the alternative connector between the actual degree paths. Retain the valid `BS+4 / MS+2` control and independent mandatory requirements.

### B37 - Reversed suffix order leaves publisher text in direct-source Review titles

**File/function:** `job_text.py`, `clean_title`.

**Trigger:** title `RTL Engineer Posted today - Austin, Texas, US`, with the matching location supplied.

**Expected:** a cleaned title of `RTL Engineer`.

**Observed:** one pass returns `RTL Engineer Posted today`; the direct-source row displays that in Review. A second call returns `RTL Engineer`. Cleanup is not idempotent because it removes a posting suffix before removing the location that currently hides that suffix.

**Fix direction:** handle both valid suffix orders or remove recognized suffixes until stable, with a bound and existing role-word protection. This is a display/normalization bug, not a claim that application decision keys currently depend on titles.

### B38 - A query-specific mismatch erases a global rejection and resurrects stale content

**Files/functions:** `applications.py`, queue superseded lookup, traced through `jsearch.collect.take` and the collector's seen callback.

**Sequence:** accept ID A; collect A again with a required five-year description, hiding it; collect that same five-year version through a company-scoped query whose aliases do not match the employer.

**Observed:** three real collector invocations end with `seen_jobs.decision='employer_mismatch'` and one pending group containing the old accepted version. Intake overwrites the hard rejection with the query-specific reason. Review deliberately ignores query mismatches, so it no longer sees the job-level rejection.

**Expected:** an employer mismatch may explain why this query does not own a result, but must not erase the independently known fact that the same result violates the hard experience rule.

**Fix direction:** retain job-level and query-level verdicts separately, or preserve a hard rejection when both apply. Verify accepted/rejected/mismatched transitions and rebuild durability. This differs from B28: all observations here refer to the same provider ID.

### B39 - A verified provider upgrade is mislabeled as a different requisition in history detail

**File/function:** `review.py`, `/api/job` identity check.

**Sequence:** apply to JSearch A, then discover the same URL directly as Ashby B. The database retains both scoped identities as aliases of the same current row.

**Observed:** history still shows the applied group, but requesting its detail with the group's ID returns `{description: '', replaced: true}`. Two retained aliases verify that this is the provider-upgrade case, not a later URL reuse.

**Expected:** the endpoint should recognize a retained decided identity alias, or at least not claim the address advertises a different opening.

**Fix direction:** validate the selected scoped identity against authoritative current aliases, including the primary identity. Keep B23's protection when an old alias has actually been removed by replacement.

### B40 - Explicit plaintext descriptions lose C++ template arguments

**File/function:** `review.py`, description extraction and unconditional BeautifulSoup parsing.

**Trigger:** `descriptionPlain` contains `Implement FIFO<T> and std::vector<int> for RTL tooling.`

**Observed:** the real detail endpoint returns `Implement FIFO\nand std::vector\nfor RTL tooling.` Both template arguments disappear, and line breaks are invented.

**Expected:** an explicitly plain-text field preserves literal angle-bracket content.

**Fix direction:** distinguish plain fields from HTML fields before parsing, rather than rendering every chosen field as HTML. Keep HTML stripping for actual HTML inputs and preserve UI textContent escaping. This is not the earlier missing-nested-description finding.

### B41 - A date without a timezone is shifted to the previous day

**File/functions:** `review_static/app.js`, `date`, `postedToday`, `postedLabel`.

**Trigger:** `posted_at='2026-09-20'`, browser timezone America/Los_Angeles, current local day September 20.

**Observed in the unchanged JavaScript:** display is `Sep 19`; `postedToday` is false. A September 20 timestamp representing local noon is correctly marked today.

**Expected:** the provider's calendar date remains September 20. A date-only value has no publication instant to convert from UTC.

**Fix direction:** treat date-only values as calendar dates; apply timezone conversion only to actual timestamps. Test negative-offset and UTC zones without changing the deliberately different quota/billing clocks.

### B42 - An old queue response overwrites a newer refresh

**File/function:** `review_static/app.js`, `refresh`.

**Trigger:** refresh A starts, refresh B starts, B returns newer state, A returns older state afterward.

**Observed:** state revision changes from `new` back to `old`; stale pending items and counters are restored. The existing `detailVersion` guard protects description requests only, and its control passes.

**Fix direction:** give queue refreshes their own generation/abort mechanism and apply only the newest relevant result. Cover both successful and failed overlapping refreshes. The prior O06 optimization suggestion did not establish this concrete wrong-state result; this pass does.

### B43 - A Skip modal can submit a different job than the one it was opened for

**File/functions:** `review_static/app.js`, Skip callback, `render`, `decide`, skip-form submit.

**Trigger:** open Skip for A; an already pending refresh completes with A no longer pending and B now selected; submit the still-open modal.

**Observed:** the modal opened for A sends `/api/decision` with `{id:'B', status:'skipped'}`. No click on B or new Skip action is needed. The test executes the original callbacks with a controlled response, not a reimplementation of their logic.

**Expected:** the dialog remains bound to A, or is cancelled with a changed-item notice. It must not transfer the user's reason and decision to B.

**Fix direction:** capture the dialog target when opening it and validate it on submission. Do not use mutable global selection as the identity of an already-open action. This is distinct from B42: even one correctly ordered refresh can change the selection while the modal is open.

## Reproduction and boundaries

Run from this audit worktree:

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
& 'D:/Operation1million/.venv/Scripts/python.exe' docs/audit-repro-round8-2026-09-20.py
```

Keep the adjacent round-5 script: its synthetic transport harness is reused. Node must be on PATH for the frontend state tests. All generated application data stays in temporary directories. Diagnostic assertions describe current defects; turn them into expected-behavior regressions during fixes.

## Remaining systematic audit sequence

These modules have prior spot findings but have not received the same whole-file function inventory in this pass:

1. `jsearch.py`: configuration, query identity, normalization, filter composition, pagination/cursors and checkpoint boundaries.
2. `collector.py`: every adapter, request policy wiring, completeness, persistence, exception sealing and CLI options.
3. `store.py`: migration, identity transitions, seen snapshots, log/shard operations, export/rebuild and rescore failure recovery.
4. `jsearch_access.py`, `collection_policy.py`, `ledger_guard.py`, `workflow_state.py`: quota, timing, pause and recovery semantics.
5. Validation/catalog/config modules, then every deployment/backup script and its failure path.

This coverage ledger is the continuation point. Do not call those remaining modules fully audited based on the earlier isolated findings.
