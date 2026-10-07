# Review and filtering performance audit

Baseline: 13a0658. Changes preserve filtering policy, evidence precedence,
source content and durable application records. No paid collection is used.

## Implemented

| Change | Baseline reproduction | Verification |
| --- | --- | --- |
| Cache the two parsed side ledgers per Review server | Ten unchanged queue requests read links and outcomes ten times each. | One read each; append, deletion, same-size/mtime atomic replacement and a writer racing the read invalidate correctly. Only two current parsed values are retained. |
| Reuse resume assessment within one posting evaluation | A supported software JD is parsed twice, at the software and eligibility gates. | Once per evaluation; changed JD/profile is reassessed. Hard requirements still reject first. No cross-posting cache. |
| Limit detail-cache reads to inventory URLs | A local Workday inventory query decoded 10,449 rows for 311 Marvell URLs. | Five-run local median 119.62 ms to 1.79 ms; every requested cached value identical. Provider and requisition proof rules are unchanged; URL batches remain below SQLite parameter limits. |
| Parse preferred sections lazily once in citizenship matching | The same section scan ran once for each of 26 patterns, even without a matching requirement. | One scan when needed, none when no relevant match. Existing preferred/required and conditional exceptions retain their meaning. |

A 300-posting local database sample returned exactly the same rejection reasons.
With the same cProfile harness, evaluation went from 2.687 to 1.184 seconds;
resume section calls fell from 329 to 166. These are local sample measurements
with profiler overhead, not a claim of a 56% production speedup. The side-ledger
read count fell from 21 to one across initial build plus 20 warm requests;
warm queue medians varied around 17-19 ms, so no large latency gain is claimed.

The daily pass also emits `operational/company_alias_audit.json` into the
private data repository. It lists current aliases, unregistered names and
reported employer domains shared by different identities. A domain coincidence
only proposes review; it cannot change aliases or merge employers. The report
is written atomically and failure warns without aborting the collection pass.

## Further measured opportunities

1. **Cache the parsed query plan for Review.** Twenty warm queue calls still
   call `load_plan` 40 times. In the local profile this consumed 0.586 of 0.780
   seconds, including 0.507 seconds parsing TOML. Key by configuration file
   identity and isolate mutable caller copies; changed or invalid rules must
   never use a stale valid plan.
2. **Skip unchanged attachment passes.** The same 20 warm calls spend 0.157
   cumulative seconds traversing groups to attach unchanged links/outcomes.
   Version the queue and side ledgers, invalidating on decisions, reopen,
   manual imports and file replacement. Parsing caches alone do not remove
   these traversals.
3. **Reuse location patterns in title cleaning.** The full fixed-input baseline
   calls `clean_title` 67,217 times, taking 82.691 cumulative seconds of a
   312.750-second profiled queue build. Its location-dependent regexes are
   constructed repeatedly. Benchmark a bounded cache keyed by normalized
   location, preserving punctuation, city boundaries and idempotence. Nested
   regex compilation time is included in that number, not additive.
4. **Reuse the serialized browser payload.** The earlier measurement of slim
   projection and JSON serialization still applies; this patch only caches
   parsed side ledgers. A response cache must include queue mutation version,
   links/outcomes, configuration and the server-local token. See the
   [earlier five opportunities](company-identity-audit-2026-10-07.md).

Private raw inputs, frozen replay data and profiles are ignored under
`.local/performance/`. Other-agent Gmail edits are excluded from this patch.

Full fixed-input replay: the frozen local database and five operational inputs
produce exactly equal queue JSON before and after, all 7,210 groups including
nested jobs and decisions. Profiled builds measured 312.979 and 220.077 seconds;
these local runs overlapped other offline tests and are not isolated production
benchmarks. The first full suite exposed two test-contract issues: importing
another test module violated the dependency audit, and a CSV publication check
assumed it was the last item in the staging loop. Both tests were adjusted and
24 focused checks passed; production logic did not change for these corrections.
