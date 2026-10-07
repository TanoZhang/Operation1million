# Company identity and ten-bug audit, 2026-10-07

Base: 587a639. Owner: codex. No paid collection, application submissions,
ledger rewrites, source-record deletion, or private profile publication.

## Reported company-name defect

Collector normalization, Review namesake matching and display used different
rules. Three supplied Marvell names produced three matching identities.
The live index also held the full legal-entity label with a US suffix and a
plural Technologies alias. The latter was confirmed against the official
posting's requisition identity, not guessed with fuzzy matching.

`employers.py` now owns exact aliases and legal-suffix matching. Review,
application namesakes, paid-listing signatures, discovery company lookup and
CSV/XLSX labels share it. Marvell variants display as Marvell. Unknown brand
punctuation is preserved; a staffing firm merely containing Marvell does not
match. Raw provider names, direct company keys, requisition decision keys and
append-only application snapshots are unchanged. Historical labels normalize
on read. New unknown-employer discovery keys use normalized identity, so legal
suffixes no longer mint separate company keys.

The integration regression reads a synthetic database with three aliases,
unifies its postings, exports one label, replays an old application snapshot,
and verifies that replay has not changed the ledger bytes.

## Ten additional reproduced bugs

All ten failed before repair. The initial 11-test run (company defect plus ten
bugs) produced 10 assertion failures and two malformed-cache subcase errors.
Public tests contain synthetic local records; no invented external API fixture
or actual job record was added.

| ID | Trigger and old result | Repair and regression |
| --- | --- | --- |
| B01 | Required qualifications or responsibilities followed by a colon and content on the same line lost the content. A mandatory skill gap passed. | Preserve text after the recognized heading. `test_b01_inline_heading_keeps_required_content`. |
| B02 | Preferred text inside the qualifications field was appended as required. A supported job was rejected. | Apply section parsing to qualification strings, lists and nested objects. `test_b02_preferred_inside_qualification_field_is_optional`; list-boundary regression. |
| B03 | An explicit unsupported mandatory qualification with no duties returned unknown before examining the qualification. | Evaluate evidenced mandatory gaps before the missing-duties fallback. `test_b03_explicit_required_gap_survives_missing_duties`. |
| B04 | A JD supplied through job_highlights Responsibilities/Qualifications was ignored. Known duties and skill gaps became unknown. | Read recognized structured sections, excluding preferred/benefits metadata. `test_b04_structured_highlights_are_actual_jd_evidence`. |
| B05 | Valid JSON containing a list instead of a cached object, or list-valued proof metadata, raised AttributeError and aborted the source's detail pass. | Treat malformed cache entries as misses and fetch current evidence. `test_b05_bad_cached_payload_cannot_abort_detail_pass`. |
| B06 | A URL reused for another requisition with the same title/date inherited the previous requisition's fresh JD. | Bind verified cache proof to source_job_id as well as title/date. `test_b06_reused_url_does_not_reuse_old_requisition_jd`. |
| B07 | Springfield, IL and Springfield, MA were one city for application suppression and paid/early-career merging. | Include normalized state in named-place identity; explicitly different states stay apart. `test_b07_same_city_different_states_are_separate`. |
| B08 | A paid listing in York, PA matched a company posting in New York, NY through substring search. | Compare parsed city/state, never arbitrary substrings. `test_b08_city_substring_cannot_join_different_postings`. |
| B09 | A paid copy stating 3 Locations failed to join the single named-city copy because one merge path treated the summary as a city. | Use the shared vague-place predicate at that merge boundary. `test_b09_multilocation_summary_is_not_a_city`. |
| B10 | A matching queue cache containing jobs with no URL was accepted and served instead of rebuilding, leaving unusable action targets. | Validate required group and job fields and discard the cache on failure. `test_b10_damaged_snapshot_job_cannot_replace_working_queue`; Review restart boundary regression. |

Missing JD alone remains unknown. B03 differs: the mandatory qualification is
present evidence. Preferred qualifications never supply a mandatory gap.
Application/skip scope and city ambiguity rules otherwise remain unchanged.

## Five optimization opportunities

These are identified opportunities, not claims of implemented speedups.
Measurements use a private queue snapshot and read-only production SQL;
absolute local timings do not predict VPS timings.

| # | Evidence | Candidate change | Verification needed |
| --- | --- | --- | --- |
| 1 | One supported software listing calls resume section parsing twice: software admission then eligibility. | Compute one assessment per row and pass it through both gates. | Identical outcomes, rejection precedence and private-profile invalidation. |
| 2 | The detail cache query reads every row for a provider. The live Workday index has 10,746 rows, while Marvell has 325. | Restrict cached rows to the current source or requested candidate URLs. | Same cache hits and misses, bounded query batches, no loss of cross-provider evidence. |
| 3 | One local dedup replay called `_place_key` 7,599 times and application `_plain` 29,345 times; cumulative time was about 0.11 seconds each. | Cache normalized places/names within a queue build. | Exact group membership and application coverage, bounded memory; nested times must not be added. |
| 4 | EXPLAIN QUERY PLAN for the recent open queue scans jobs_relevance and uses a temporary B-tree; julianday(first_seen) is not an indexed range. | Benchmark an expression/composite index for open date windows and ordering. | Offset-aware timestamp equivalence, insertion overhead, old-schema migration and query-plan change. |
| 5 | Projecting and JSON-encoding the 7,257-group snapshot took a local median 99.52 ms over ten iterations. | Cache the slim response per queue version, invalidating after decisions, links, outcomes and input changes. | Byte-equivalent payload apart from intentional transient fields; no stale actions or leaked tokens. |

Implementation, test commit and production verification are recorded in the
newest handoff entry when complete. Private evidence: `.local/company-audit/`.
