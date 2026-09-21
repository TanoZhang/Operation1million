# Debug report, round 6 - 2026-09-20 Pacific

Four boundary defects reproduced in the user's pending fixes. These are follow-up findings on uncommitted implementation, not assertions about the current remote main. No business code was changed and no priority labels are assigned.

## Inspected version and validation

The audit worktree starts at `ba2cf0f5c8bd3ccddc193c19c0c642141d27b73c`; claim commit `7ef9397`. Remote main and claude remain `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`. Tests explicitly import `D:/Operation1million/src`, including the pending fixes described by the latest handoff, "Fourth review round, and one withdrawal - 2026-09-21 UTC".

Working source SHA256 fingerprints recorded after reproduction:

| File | SHA256 |
| --- | --- |
| applications.py | 7CF665B559B4EF868F7EAB26A4F9D27B8FBE76A021B428457D428EC275922490 |
| store.py | F714066475DF2E494054344A5B47A9159ED2DD257C8826804BD47331D4A0550C |
| collector.py | F3A0468F4291BEC8258F0BE43298B8CC9102DE9DD4851345D157B27773F13BD8 |
| jsearch.py | 89002AB0BB35F7AC14AAA3E9BFE098AC190D5743FDE89298A72D83983BA040B7 |

All four diagnostic cases passed. B28 runs two complete `collector.main` invocations; B27 exercises store updates, decision append and queue replay; B29 runs the export CLI function and rebuild; B30 injects a log failure into the actual rescore function, retries it, then rebuilds. State is synthetic and temporary. External transport is blocked or replaced by synthetic responses. No paid calls, deployments, live-data edits or full-suite validation were performed. The handoff's 447-test result is another reviewer's result, not a claim of this audit.

Line numbers below refer to the inspected working version, not the older source in the audit worktree.

## B27: Cross-provider decision fallback survives a later requisition replacement

Location: `src/jobdisco/applications.py:146` and `:158`, `moved_states` population and lookup.

Sequence:

1. JSearch A at URL U is marked applied.
2. The same opening is discovered directly as Ashby B at U. The new cross-provider decision fallback correctly keeps it out of pending.
3. The board reuses U for a genuinely different Ashby C. Store replacement handling removes A/B aliases and leaves only `(ashby, C)`.

Actual: C is still absent from pending. The applied snapshot is A. `moved_states` matches solely on URL and unequal provider, so the old JSearch decision continues to apply to every future direct requisition using U, even after the store has removed the corresponding identity alias.

Expected: a proven provider upgrade can inherit a decision; a later unrelated requisition must be independently reviewable.

Suggested direction: require evidence that the decided scoped identity remains an alias of the current opening. URL equality plus a different provider is not sufficient. Preserve legacy handling separately. Add the three-step sequence above, not only a two-step provider-upgrade test. This follows up the B10 fix; it is not a repeat of the original lost-decision symptom.

## B28: A rejection for another job ID hides the accepted job at the same URL

Location: `src/jobdisco/applications.py:194`, the `superseded` subquery added for B24.

Sequence through the collector entry point:

1. Paid ID B at U is accepted with an RTL description; Review shows one pending group.
2. A later paid result has ID A at the same U and requires five years of experience. A is rejected and recorded in `seen_jobs`. The held job remains B, as expected.

Actual: Review now returns zero pending groups. The subquery matches URL and provider but does not compare `source_job_id`, so A's later rejection suppresses B.

Expected: a rejection must supersede the same opening's accepted version. A shared application URL does not establish that identity.

Suggested direction: match the scoped requisition identity, with an explicit conservative fallback only when IDs are absent. Consider supported aliases where relevant. Keep the existing timestamp and query-specific-rejection protections. Regression coverage needs both different-ID/same-URL and same-ID updates. This is an over-broad match introduced by the B24 fix, not B24's stale accepted-description case.

## B29: Export omits manifests for closure-only dates

Location: `src/jobdisco/store.py:1072`, `main --export`, especially the manifest loop at `:1092`.

Trigger: export a held posting first seen two days ago and closed yesterday into an empty history directory.

Actual: after the B21 fix, export now completes. It writes a job log for the discovery date and a closure log for the later date. However, manifests are created only for keys in `by_day`, which contains first-seen dates, not closure dates. Verification returns `missing-manifest` for the closure date, and a fresh rebuild raises `Daily log integrity check failed`.

Expected: successful export produces a self-contained, verifiable recovery history for both open and closed jobs.

Suggested direction: seal every date/file actually written during export, including closure-only dates and any shards, or avoid redundant closure events if the full exported snapshot already captures the required closed state. Verify and rebuild the completed export in its regression test. This was previously masked by B21's immediate refusal to export historical rows.

## B30: Rescore retry cannot publish corrections after the first append fails

Location: `src/jobdisco/store.py:1137`, `rescore`, commit at `:1165` and publication at `:1170`.

Sequence:

1. Durable history and SQLite both contain score 99.
2. Rescore computes 10 and commits SQLite; an injected `OSError` makes `append_scores` fail before writing.
3. Rescore is run again with the same scoring result.

Actual: the retry compares against already-corrected SQLite and finds no changed rows, so `append_scores` is never called. The live score is 10, the fresh rebuilt score is 99, and history verification still returns only `ok`.

Expected: retrying a failed publication must complete the durable correction, or the failure must leave enough recovery state to retry it explicitly.

Suggested direction: order the durable correction and SQLite commit so a failed append remains recoverable, or retain an explicit unpublished-correction record. Do not use equality with the already-committed derived score as proof that the log contains it. Test an append failure, retry and fresh rebuild; also consider interruption between batches. This follows up B11: the new happy path publishes scores, but its failure path still permanently loses the correction.

## Run the diagnostic

From the audit worktree:

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
& 'D:/Operation1million/.venv/Scripts/python.exe' docs/audit-repro-round6-2026-09-20.py
```

The script uses the round-5 transport harness beside it, so retain both scripts. It targets the pending fixes and is not expected to pass against older main, which lacks those fixes. Assertions describe defects; convert them to desired-behavior regressions when implementing corrections.
