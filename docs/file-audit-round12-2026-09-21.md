# File audit, round 12: quota, pacing and recovery

## Scope and evidence

Read every function in `jsearch_access.py`, `collection_policy.py`,
`ledger_guard.py` and `workflow_state.py`. Traced their callers in paid paging,
direct collection, the manual backup workflow and VPS publication/startup.
Five new findings are B63-B67. No business-code changes, priorities, provider
requests, production-state access or real credit spending.

The user checkout is based on main commit
`ca501dc41640a09c0650d92bcb12ddddbf2025ca`. During this audit it also contained
pending round-11 fixes in store, collector, JSearch and tests. The four modules
audited here and `deploy/vps/daily-pass.sh` were unchanged from that commit.
The pending changes were inspected for overlap and preserved. Reproduction
imports are explicitly from `D:/Operation1million/src`; the separate audit
worktree holds only this report, script and claim changes.

Reproducer: `docs/audit-repro-round12-2026-09-21.py`.

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round12-2026-09-21.py
```

All five cases pass their assertions against current defective behavior. Tests
use real temporary quota/cursor/pause databases. HTTP responses and sleeps are
mocked. B63-B64 inject a billing-cycle clock boundary. B67 simulates the shell's
copy/restore steps with real files and Python functions; the VPS shell script
itself was read, not executed on Windows or on the VPS.

Existing relevant tests also pass, 121 total, all exit 0 and no skips:

| Module | Tests | Time |
| --- | ---: | ---: |
| `test_jsearch.py` | 97 | 53.361 s |
| `test_ledger_guard.py` | 8 | 0.372 s |
| `test_workflow_state.py` | 3 | 0.135 s |
| `test_collection_policy.py` | 13 | 0.264 s |

Expected usage/refusal messages from negative CLI tests are not production
failures. These passing suites do not cover the new counterexamples.

## B63: An old-cycle response finishes the new cycle's backfill cursor

Locations: `jsearch_access.py:225` (`resume_page`), `jsearch_access.py:233`
(`advance`), and `jsearch.py:734`/`:902` in `collect`.

Cursor resume and advancement each independently default their period to
whatever cycle is current at that moment. The paging state does not retain the
period from which its page number came.

Executed the real client, guard and paging loop with a mocked response:

1. At `2026-10-15T23:59:59Z`, the September 16 cycle has a saved next page of 5.
2. Page 5 is reserved and dispatched in that old cycle.
3. Its short successful response completes two seconds later, in the October 16
   cycle. The checkpoint callback succeeds.
4. `advance` writes `(page=6, exhausted=True)` under the new period.
5. Another collection in the new period issues zero requests for that query.

The temporary credit event correctly remains in period `2026-09-16`; the
incorrect cursor is in period `2026-10-16`. A new cycle's sweep is skipped
because an old cycle's page finished late. This is distinct from B62's UTC log
manifest issue: this case crosses the 30-day billing boundary and affects paid
query progress.

Suggested correction: bind paging progress to an explicit captured billing
period, and detect a period transition before reusing old page numbers. Never
advance a new period's cursor from a response requested for the prior sweep.
Keep the deliberate daily/billing clock distinction intact.

## B64: Ledger comparison misses daily spend spanning the billing boundary

Locations: `ledger_guard.py:22`/`:44`, `jsearch_access.py:183` and `:241`.

`ledger_guard.compare` compares only the current billing period's totals. A
Pacific budget day can still contain credits from the previous UTC billing
period, so an empty restored local ledger can pass this check while losing
charges that still constrain the current daily budget.

Tested with the shipped 320-credit daily budget:

- Just before the UTC billing reset, the published ledger reserves all 320
  credits, using mocked calls.
- Two seconds later the billing period is new, but the Pacific budget day is
  unchanged. A schema-only local ledger is compared with that published ledger.
- Both current-period totals are zero, so `compare` returns `(0, 0, True)`.
- The published ledger reports `day_used=320` and refuses another request.
  The local ledger reports `day_used=0` and permits one.

The normal guard counts cross-period daily events correctly when it has them.
The defect is the startup comparison accepting a local ledger that lost those
events. It can let collection exceed the intended daily allocation even though
the monthly comparison says the local history is safe.

Suggested correction: compare the active daily window as well as current-period
spend, including events from the prior period that still belong to that window.
Do not solve this by making the two clocks identical. Preserve the existing
legitimate case where local state is ahead after an unsuccessful push.

## B65: Another crawler's Crawl-delay is applied to this crawler

Location: `collection_policy.py:26` (`robots_delay`), especially its global
regular-expression scan; used by `request_interval` at line 54.

The parser takes the largest Crawl-delay anywhere in the file, without reading
the User-agent groups. Its own docstring promises the delay declared for this
collector.

The synthetic robots response explicitly distinguishes the agents:

```text
User-agent: JobSourceCollector
Crawl-delay: 2

User-agent: OtherBot
Crawl-delay: 600
```

`request_interval` chooses 600 seconds instead of the collector's 2 seconds.
The returned interval is then cached and used for subsequent page waits. No
600-second wait was actually performed; the measured result is the computed
interval, and the resulting slowdown follows from the caller's sleep path.

Suggested correction: parse User-agent groups and select the directives
applicable to the actual User-Agent before combining them with configured
minimums. Preserve provider minimums and applicable declared delays.

## B66: A robots request can be throttled without pausing the source

Locations: `collection_policy.py:26`/`:35` and `SourcePolicy.interval`; its
consumer is `Collector.fetch`.

The robots helper performs an independent request and only acts on HTTP 200.
A 429 response, including Retry-After, becomes a cached missing delay. It never
enters the source's pause handling, so the next board request still leaves.

Executed `Collector.run` on a two-page synthetic Workday board. The board and
robots requests use the same configured host. Recorded order:

```text
board page 1 -> robots.txt HTTP 429 (Retry-After: 3600) -> board page 2
```

The source returns `complete`, both jobs are collected, and the real temporary
`source_pauses` table has zero rows. This violates the repository's explicit
rule to stop the source on 429 and persist at least the stated retry delay.
No live site was contacted or throttled during the audit.

Suggested correction: route robots response statuses through source-level stop
and cooldown handling. Fallback to configured minimums for unavailable pacing
data must not turn an explicit server throttle into permission to continue.
This is separate from B06: that earlier fix prevented fetching robots during
an already known cooldown; this case fails to create a cooldown from the
robots response itself.

## B67: VPS recovery rewinds the published ledger, but not the runtime ledger

Locations: `workflow_state.py:8`; caller paths in
`deploy/vps/daily-pass.sh:54` (`publish_state`), `:81` (cursor restore), and
`:160`/`:176` (next startup).

When history fails verification, the VPS script first copies local operational
state into the data checkout, then runs `restore_cursors` only on that published
copy. Its persistent runtime ledger under `$CODE/.local` keeps the unpublished
cursor progress. The next startup preserves any existing nonempty local ledger
and only compares credit totals, which are equal by design.

The reproducer follows those copy/restore operations with real temporary files:

| State | Cursor | Recorded credits |
| --- | --- | ---: |
| Pre-pass baseline | page 2, not exhausted | 0 |
| Local after the unpublished pass | page 9, exhausted | 1 |
| Published copy after `restore_cursors` | page 2, not exhausted | 1 |
| Local used by the next pass | page 9, exhausted | 1 |

`ledger_guard.compare(local, published)` returns `(1, 1, True)`. Thus the next
local sweep still considers the query exhausted even though the corresponding
results were not published. Rebuilding the derived job index does not rewind
the separate local quota ledger.

The Python restore function itself works: a positive control applies it to the
actual local ledger and gets page 2 again while retaining its spent credit and
account pause. The defect is the VPS caller's target selection. The filesystem
simulation is executed evidence; the script-to-next-run link is traced source,
not a claim that an actual VPS failed in this way.

Suggested correction: rewind unpublished cursor progress in both the published
copy and the runtime ledger before the latter is reused. Keep credits, credit
events and cooldowns; do not replace the whole ledger with the older baseline.

## Function coverage ledger

All functions in the four scoped Python files were read through their callers.
The table distinguishes executed tests from source inspection; it does not
claim exhaustive operating-system or provider validation.

| Module / functions | Coverage |
| --- | --- |
| `jsearch_access.connect`, `RequestGuard.__init__` | Read transaction lifetime, schema migration and legacy usage initialization; exercised by all quota fixtures and existing tests |
| `_cycle`, `budget_day`, `period`, `days_until_reset`, `daily_window` | Read both independent clocks; existing cycle/DST/reset tests pass; B63-B64 cross a billing boundary |
| `daily_used`, `balance`, `used`, `baseline` | Read timestamped usage, legacy residuals, monthly baselines and billing drift; B64 and existing budget tests |
| `pause`, `get`, `_get_locked`, `settle` | Read serialization, pre-dispatch reservation, interval, run/day/month limits, cooldown and post-response accounting; existing concurrent guard, timeout and billing tests pass |
| `resume_page`, `advance` | Read cycle keys and upsert behavior; B63 and recovery cases |
| `collection_policy.robots_delay`, `request_interval` | Read fetching, caching, parsing and minima; B65-B66 plus existing source-minimum tests |
| `retry_after_seconds` | Read seconds/date/nonfinite handling; existing delay-format tests pass |
| `SourcePolicy.__init__`, `interval`, `connect`, `check`, `pause` | Read lazy pacing and durable pause checks; B66 plus existing 429/503/challenge/cooldown tests |
| `ledger_guard.credits_recorded`, `compare`, `main` | Read current-period comparison, missing-file handling and CLI outcomes; all eight existing tests pass; B64 |
| `workflow_state.restore_cursors`, `main` | Read baseline import, transactional cursor replacement and CLI; existing tests and B67 positive/negative target controls |

Caller inspection included both workflow publication branches. The dry-run
backfill condition already explicitly blocks a sweep during a dry run, so the
hypothesis that dry-run sweeps publish discarded progress was rejected, not
reported as a bug. The full deployment-script audit remains the next module
group; this round traced only the quota/recovery interfaces needed here.

## Source fingerprints

SHA-256 of the unchanged scoped modules and VPS caller:

```text
jsearch_access.py
1AA7A9C7893CB9592892670BA87DACB6C6A8EDD3C75E12EA1273F1B8B361E4CC
collection_policy.py
C7AA61340BAC1DB8906D0DD2EDABF3B245CA562B799FEA56B7CCC35A249CE295
ledger_guard.py
0F5E90A15BF4D11061BF10E2FE9409FB6AADC72F161E2ECB253C7819C0EB0F2A
workflow_state.py
F09C4A1B66F24564F2327ADF7A24831F37F4DB130C661BC67CFDE48700FF616B
deploy/vps/daily-pass.sh
DDEE20DEBDC3A581BEFB5EF6266CB79FA2CE11BC6BA55802DD4BE3673EBCFE58
```
