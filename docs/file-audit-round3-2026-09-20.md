# File audit, round 3 - 2026-09-20

Three additional defects were reproduced offline. No application code was changed.
This supplements the previous two reports; it does not repeat B01-B16.

## Scope and evidence

- Audit lineage: `c5db61a3f86592c16a79fbdc851fd30188a95504`; reproduction at claim commit `6cbef142ff0c44c35dbc0139c69215e715fd9496`.
- Inspected application source and remote main/claude: `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`.
- Traced collector normalization, sitemap collection, persistence and exception sealing; store batch preparation, identity replacement and raw merging; application queue filtering and history recovery.
- All three assertions also passed with imports from `D:/Operation1million/src`, including the user's uncommitted first-round fixes. Those changes were read, not modified.
- Tests used temporary databases and synthetic provider payloads. External requests were blocked. These results do not establish production incidence or live provider payload coverage.
- The full suite was not repeated for this documentation-only round. The previous round's 405-test result is not a new validation result.

Working-tree SHA256 fingerprints recorded after reproduction:

| File | SHA256 |
| --- | --- |
| collector.py | A5E6D24B48A06149D590266DC1A8938F2DE983F1F077FB7C4F4F0CBEADA39814 |
| store.py | 3C589FBF6338DDA08074ACC4F7A0EE7BC455D95F737135C0E70888D0EF4134D6 |
| applications.py | AE5CB43CE8FEA2FCEADFB52BA9D1A028FD8083F714B942AFF578C85FB3BDC772 |

## B17 - P1: Failure sealing commits rows whose history append failed

Location: `src/jobdisco/collector.py`, `main.persist` (line 796), `main.seal` (line 826), and the outer exception handler (line 978). Line numbers refer to committed audit source.

Trigger: a source updates SQLite successfully, but `store.append_log` raises before appending its records. The reproducer injects an `OSError` at this boundary.

Expected: preserve earlier committed sources, roll back the failed source, and seal only the state backed by durable history.

Actual: the exception handler calls `seal` without rolling back. It exports the failed source's advanced state and commits its pending SQLite changes. The synthetic run leaves one live job, zero jobs after rebuilding a fresh index, and a restored `since` strategy with a watermark. Every history verification result is still `ok`.

Impact: index recovery silently loses the posting, and the advanced checkpoint can prevent a subsequent incremental fetch from recovering it. This differs from the earlier pruning/bootstrap finding: no pruning is needed.

Suggested fix: establish a failed-source rollback boundary before exporting or sealing state. Preserve previously committed sources. Also reason through partially appended logs; rolling back SQLite alone does not make an interrupted multi-record append atomic.

Regression coverage: injected append failure before any bytes, a partial append failure, and a failure after an earlier source was durably committed. Compare live state, rebuilt state, and the next collection plan.

## B18 - P2: Same-batch URL reuse blends two requisitions and hides the newer one

Location: `src/jobdisco/store.py`, `record_source` preparation (line 275 onward) and insertion-time `merge_raw` (line 329).

Trigger: a paid result batch contains different job IDs with the same application URL. Replacement detection checks database state during preparation, before either prepared row has been inserted. The later write merges the first row's raw data into the second without repeating requisition replacement detection.

Reproducer: A is an RTL Intern with a description requiring five years; B is an RTL Engineer with no description. Both independently pass the paid intake filter. They share a URL but have distinct IDs.

| Outcome | Two separate record_source calls | One batch containing A and B |
| --- | --- | --- |
| Current identity | B | B |
| Retained identity aliases | B | A and B |
| Description inherited from A | None | Five-year requirement |
| Pending Review groups | 1 | 0 |

Expected: splitting or combining the batch must not transfer another requisition's description or identity. Actual contamination makes the Review experience gate exclude B.

Suggested fix: evaluate replacement against the evolving state within the batch, including identity aliases, before merging raw data. Add a batch-partition equivalence regression covering different IDs at the same URL. Direct collector URL deduplication does not protect the paid persistence path tested here.

## B19 - P2: Sitemap collection bypasses the stable Renesas ID extractor

Location: `src/jobdisco/collector.py`, `normalize` (line 103), `html_job_id` (line 185), and `collect_sitemap` (line 428).

Trigger: a Renesas sitemap detail page exposes a JSON-LD JobPosting without one of the simple ID fields recognized by normalization. The URL contains a stable `-jid-6866` suffix. A later pass changes the title slug while preserving this suffix.

Expected: both URLs normalize to source job ID `6866`, allowing existing identity mapping to preserve one requisition.

Actual: the stable-ID helper returns `6866` when called directly, but the sitemap path never calls it. Both collected rows have a null source job ID. Two synthetic complete passes leave two open rows after the slug changes; the one-row fixture also activates the existing closure fuse. The essential defect is the missing identity, independent of the closure fuse threshold.

Impact: URL changes can duplicate the same requisition and break continuity for decisions keyed by its former URL. This is an adapter-wiring defect, not evidence that a particular live page changed its slug.

Suggested fix: wire provider-specific stable ID extraction into normalization or sitemap detail ingestion while preserving original raw evidence. Test the full sitemap-to-storage path, including a slug change, rather than testing the ID helper alone.

## Reproduction

Run from the audit worktree in PowerShell:

```powershell
$env:PYTHONPATH='D:/Operation1million-file-audit/src'
& 'D:/Operation1million/.venv/Scripts/python.exe' docs/audit-repro-round3-2026-09-20.py
```

To inspect the user's working version, select `D:/Operation1million/src` instead. The script prints the imported source path and uses temporary data only. Its assertions capture the defects, so a successful fix may intentionally make an assertion fail; these are diagnostic reproductions, not desired-behavior regression tests.
