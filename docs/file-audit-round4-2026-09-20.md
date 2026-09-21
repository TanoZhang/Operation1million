# File audit, round 4 - 2026-09-20

Correction in round 5: B20 is retracted. Three findings remain (B21-B23). No priority labels are assigned. No application code was changed.

## Evidence and scope

Reproduced at audit claim commit `6525262ac09c8b49c1141d0c24e6613ea9a92ec8`, whose application source matches main/claude `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`. All four cases also reproduced with imports from the user's uncommitted source tree, `D:/Operation1million/src`. Its first-round fixes were inspected and left untouched.

This round traced collector normalization and rejection handling, full-pass closure inference, export and replay, and application-history detail retrieval. It also inspected workflow cursor restoration, pruning, ranking, and ledger comparison without claiming those files are bug-free.

All fixtures are synthetic, with temporary databases and ledgers. External requests are blocked; the Review test makes one loopback HTTP request. No provider collection, paid request, deployment, or production-incidence verification occurred. The diagnostic script passed on both source trees. The full suite was not rerun because business code did not change.

Working-source SHA256 fingerprints recorded after reproduction:

| File | SHA256 |
| --- | --- |
| collector.py | A5E6D24B48A06149D590266DC1A8938F2DE983F1F077FB7C4F4F0CBEADA39814 |
| store.py | 3C589FBF6338DDA08074ACC4F7A0EE7BC455D95F737135C0E70888D0EF4134D6 |
| review.py | A231FB79C09F334AB6597A6971B883419429031F27ABE83B12C70B520184963F |

## B20: Retracted - the production entry point prevents this closure

The original fixture called `Collector.run` and then `store.record_source` directly, bypassing `main.direct`. The production wrapper at `collector.py:780` already changes the status to `partial` when `c.rejected` is nonempty. Therefore the reported closure is not a production-path bug and needs no fix. Round 5 runs the same five-posting scenario through `collector.main`: exit code 2, status partial, zero closures, on both inspected source trees. The misleading standalone fixture has been removed. Line numbers for the remaining findings refer to committed audit source.

## B21: The historical export command rejects historical dates

Location: `store.py:1026`, `main --export`, and `append_log` / `sealed`.

Trigger: an existing index contains a posting first seen yesterday, and `JOBDISCO_STORE` is empty, satisfying the export command's explicit precondition.

Actual: export groups jobs by historical `first_seen` day and calls the ordinary append function for that day. The function immediately raises `FileExistsError: Daily log is sealed; refusing to change a day that is over`. The fixture needs only one historical row; no existing history or conflicting file is needed.

Expected: the advertised one-off backfill can export held historical postings into an empty store while preserving their original timestamps.

Suggested fix: provide a narrowly scoped empty-store export path that does not weaken normal daily immutability, or write an export snapshot using an allowed current log date while retaining historical job fields. Verify historical closures and source state as well as open jobs, and round-trip the result through a fresh rebuild. Do not broadly disable sealing for ordinary collection.

## B22: Missing Eightfold position paths collapse different jobs onto the board URL

Location: `collector.py:103`, `normalize`, Eightfold branch; `Collector.add` URL deduplication; `collect_json` count completion.

Trigger: two Eightfold records have distinct IDs and generic `url` fields, but no `positionUrl`. The fixture represents a missing provider field; it does not assert that current live responses have this shape.

Actual: normalization initially reads each generic URL, then overwrites it with `urljoin(source.access_url, '')`. Both jobs now point to the board itself. Deduplication silently drops the second. Since the raw item count reaches the stated total of two, collection reports `complete`, with one accepted job and zero rejected records.

Expected: preserve a valid supported job URL, or explicitly reject an unusable record and prevent it from certifying full inventory. Never manufacture a job identity from the board's own address simply because a field is absent.

Suggested fix: validate the provider-specific path before overriding the generic URL; define supported fallback URL fields explicitly. Add adapter tests for absent, null and empty paths, multiple distinct IDs, and completeness after normalization losses. B20 addresses rejected records; this case is different because the malformed result is accepted and silently deduplicated.

## B23: Applied-history details show the replacement requisition's description

Locations: `review.py:79`, `/api/job`; `review_static/app.js:105`, detail request; application decision snapshots.

Trigger: requisition A is marked applied, then the provider reuses A's URL for a different requisition B. Store replacement handling correctly keeps B pending and A in applied history.

Actual: the applied group still has identity A, but the detail request contains only its URL. `/api/job` reads the current SQLite row at that URL and returns B's description. The loopback fixture returns `New requisition B: verify FPGA.` for the URL displayed under applied A.

Expected: history must not attribute another requisition's description to the applied job. If A's text cannot be recovered, show that it is unavailable rather than showing B's text.

Suggested fix: make detail lookup aware of the selected scoped requisition and check it against current identity before returning content. If historical prose is needed, recover it from appropriate durable evidence or deliberately snapshot it; do not assume URL equality establishes identity. Test history and pending detail side by side after URL reuse. This differs from B10: the queue's decision separation works in this fixture; the wrong content appears in detail rendering.

## Reproduction

From the audit worktree in PowerShell:

```powershell
$env:PYTHONPATH='D:/Operation1million-file-audit/src'
& 'D:/Operation1million/.venv/Scripts/python.exe' docs/audit-repro-round4-2026-09-20.py
```

Select `D:/Operation1million/src` instead to inspect the working-tree fixes. The script prints its imported source path. Assertions describe observed defects; after a fix, replace the relevant assertion with desired behavior when promoting it into the test suite.
