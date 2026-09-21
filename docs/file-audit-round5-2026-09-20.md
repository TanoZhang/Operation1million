# File audit, round 5 - 2026-09-20

Three new findings, tested through `collector.main`, plus one explicit correction. No business code changed. Findings have no priority labels.

## Evidence

Audit source: claim commit `453f1f8`, descended from `d080ed155c62493875f3b0f7cc1b0f89445ab4da`. Application code matches inspected main/claude `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`. The complete diagnostic also passed using `D:/Operation1million/src`, which contains the user's ongoing uncommitted fixes. Source SHA256 fingerprints after that run:

| File | SHA256 |
| --- | --- |
| collector.py | 50B8EB29AF87F12C0B25E6C37B5F20A9B266296A32D6F4098EEEBA74945A9F37 |
| jsearch.py | 89002AB0BB35F7AC14AAA3E9BFE098AC190D5743FDE89298A72D83983BA040B7 |
| store.py | F714066475DF2E494054344A5B47A9159ED2DD257C8826804BD47331D4A0550C |

All databases, logs, ledgers and reports are temporary synthetic data. HTTP transport and robots lookup are replaced with fixtures; there are no external requests or paid charges. Real normalization, filtering, persistence, completion handling, manifests and queue replay execute. The full test suite was not rerun for this audit-only change. Provider behavior in production is not claimed.

## Correction: B20 is not a production-path bug

The round-4 fixture bypassed `main.direct`, which already converts results with rejected records to `partial` before persistence. The same scenario through `collector.main` gives exit code 2, status partial and zero closed postings. B20 is retracted, its misleading standalone reproducer removed, and the previous report corrected. Do not spend implementation work on B20.

## B24: A newly rejected version leaves the old accepted version in Review

Locations: `jsearch.py:639`, `collect.take`, especially the rejection `continue` at line 673; collector seen/checkpoint callbacks; `applications.queue`.

Trigger: the same JSearch job ID and URL are collected twice. First its RTL Engineer description says only "Design RTL hardware." Later its description says "5 years experience required."

Observed through two complete `collector.main` invocations:

- The second paid result is correctly classified `required_experience_over_2_years`.
- `seen_jobs` records that current rejection.
- The accepted `jobs` row still contains the old description.
- Review still returns one pending group, because it evaluates the stale accepted row and never reconciles the newer rejection in `seen_jobs`.

Expected: a fresh hard rejection for the same scoped identity must affect the current reviewable version. Recording the rejection only in discovery history must not leave the old version eligible indefinitely.

Suggested direction: reconcile rejected updates with previously accepted rows, using scoped identity and preserving append-only application decisions. Distinguish global hard rejections from query-specific employer mismatches. Any current-state change must survive rebuild; simply changing SQLite would repeat the durable-state defect found earlier. Regression coverage should include accepted-to-rejected-to-accepted transitions and an already-applied decision.

## B25: TI's adapter changes the job provider but not the source used for closure

Locations: `collector.py:519`, TI adapter replacement; `main.direct` return at line 787; `store.record_source` company/provider closure predicate.

Trigger: the TI shell points to an Oracle jobs API. The first complete pass returns five postings; the next complete pass returns four, with one genuinely absent.

Actual: the adapter sets `self.source.provider_key` to `oracle_cloud`, and normalized jobs use that provider. The outer wrapper returns the original `ti_careers` Source to persistence. Thus `jobs.provider_key` is `oracle_cloud`, while `source_state.provider_key` and the closure query use `ti_careers`.

Result: second pass exits 0 and reports complete with four returned jobs, but all five database jobs remain open. The fixture is below the closure fuse threshold (one of five), so the fuse does not explain the result. The same mismatch also means `touch_source` cannot find these jobs when called with the original TI source.

Expected: adapter transport choice must not disconnect stored postings from the inventory that owns their lifecycle.

Suggested direction: define one stable provider identity for storage and apply it consistently to rows, source state and closure/touch operations. Consider existing Oracle-keyed TI jobs and application decision keys when choosing a migration. Test consecutive full passes through the real entry point, not just adapter output.

## B26: An ETag from the TI page shell is used to certify the jobs API

Locations: `collector.py:272`, `Collector.fetch` validator capture; conditional probe in `Collector.run`; TI shell-to-API adapter.

Trigger: TI's HTML shell sends an ETag, while its jobs API can change independently. The shell remains unchanged and answers the next conditional request with HTTP 304. This is a synthetic response scenario; live TI ETag availability has not been checked.

Actual: the first pass captures the shell ETag before requesting the jobs API and stores it as the completed source validator. On the next run, `request_for` for the original TI source targets the shell. A 304 immediately returns `unchanged`; the jobs API is never queried. The fixture supplies a changed API response as the next possible response, but only one request occurs and the original single job remains held.

Expected: a validator may establish freshness only for the resource whose content it validates. An unchanged HTML application shell does not establish an unchanged jobs inventory behind that shell.

Suggested direction: bind validators to the actual inventory request, including endpoint and request shape; avoid retaining shell/detail validators as board validators. Keep the B25 provider-identity concern separate: even correct closure ownership does not make shell ETags certify API content. Regression coverage should exercise an unchanged shell with changed API jobs, and a genuine inventory 304.

## Reproduction

```powershell
$env:PYTHONPATH='D:/Operation1million-file-audit/src'
& 'D:/Operation1million/.venv/Scripts/python.exe' docs/audit-repro-round5-2026-09-20.py
```

Use `D:/Operation1million/src` to select the user's working source. The script prints its imported collector path. B24-B26 assertions describe current defects; the B20 assertion describes the existing protection that invalidated the earlier finding.
