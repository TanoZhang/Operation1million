# Continued audit and optimization study - 2026-09-23 UTC

Status: findings and measured prototypes only. Application source, functionality,
database schema, real data, log formats and deployments are unchanged.

Audited source: `b2c9340f84dbe5f7fb020301c2d724af32587424`.
Working base: `a6fd3d6e483fed25134bebf45a40a564b2c4b165`, whose changes are
documentation only. Last synchronization: 2026-09-23 UTC; main remains
`b2c9340`, Claude has no unmerged changes, and Codex holds these audit reports.
No production incidence or complete repository coverage is claimed.

## Four additional reproduced defects

R1-R3 remain documented in [the first report](review-audit-2026-09-23.md).
The new cases use the real store and Review queue with temporary fixture data.

```powershell
python docs/review-audit-repro-round2-2026-09-23.py
```

Expected on the audited code: eight tests, four failures and four passing
controls, exit code 1. These assertions express the intended eligibility policy.
No fix is included in this audit.

### R4 - Negated citizenship requirements hide eligible postings (P2)

Location: `src/jobdisco/jsearch.py:701`, `us_person_required`.

Trigger: `This position does not require US citizenship.` under an RTL title.
Expected: no citizenship rejection and one pending posting.
Actual: `us_person_required` and zero pending postings. The positive control
`This position requires US citizenship.` correctly rejects.

Cause: the configured pattern matches `require US citizenship`, while the
prefix check recognizes conditional words but not negation. Also reproduced
directly with `This role never requires US citizenship.` and `Candidates are
not required to be a US citizen.` The existing `no U.S. citizenship required`
test covers another grammatical shape and does not protect these clauses.

### R5 - A requirements field loses its heading before filtering (P2)

Location: `src/jobdisco/jsearch.py:627` and `:652`, `description_text`.

Trigger: `{"requirements": ["PhD in Electrical Engineering"]}`.
Expected: the explicitly required PhD causes `phd_only` and zero pending jobs.
Actual: the heading disappears, structured text becomes only `PhD in Electrical
Engineering`, and the posting remains pending. Changing only the key to
`required_qualifications` correctly rejects the same requirement.

Cause: both heading checks recognize `required` and `qualifications`, but not
`requirements`. Review's display renderer recognizes the field and labels it
Requirements, so the meaning shown to a person differs from the filter's input.
The defect occurs at both root and nested dictionary traversal checks.

### R6 - An unrelated preference suppresses mandatory experience (P2)

Location: `src/jobdisco/experience.py:174` and `:209`, `evaluate`.

Trigger: `Python preferred.\n5 years of experience.`
Expected: five years, `required_experience_over_2_years`, zero pending postings.
Actual: no recognized experience requirement and one pending posting. Removing
the first sentence produces the intended rejection.

Cause: any short no-digit block containing an optional word opens a preferred
section, even when it is a sentence about a particular skill. Its scope then
suppresses the following experience clause. The architecture bug log records
the analogous degree-parser bug as fixed, but the experience parser still uses
the broad heading heuristic. This is a separate surviving call path.

### R7 - An inline required heading cannot end a preferred section (P2)

Location: `src/jobdisco/degree.py:130` and `:151`, `description_only`.

Trigger: `Preferred qualifications:\nPython\nRequired: PhD in EE`.
Expected: the new Required heading replaces the preferred section and rejects
as `phd_only`. Actual: the posting stays pending. Moving only the degree to the
line after `Required:` correctly rejects.

Cause: `optional` is calculated from the preceding section before the inline
heading is read. The block contains a degree, so it cannot update state through
the standalone-heading path; then the optional guard skips it before the later
inline-required logic runs. The existing inline-heading test starts with no
preferred section and therefore misses this order-dependent case.

## Improvements that preserve behavior and data

The experiments below are private function copies compiled in a separate
namespace by `docs/review-benchmark-2026-09-23.py`. They are not installed into
application files. The existing public return values, sort order, source
records and database formats stay intact. They deliberately do not incorporate
the eligibility fixes above, which would change behavior.

```powershell
python docs/review-benchmark-2026-09-23.py
```

The benchmark first checks exact description tuples and rendered text on 13
fixtures, including entities, literal type names, nested qualifications,
teasers and paid provenance. It runs 43 existing description and ranking tests
with the prototypes, then checks exact sorting output and unchanged inputs.
All pass. The additional unchanged experience suite has 32 passing tests.

Timings below are medians of five alternating baseline/prototype rounds on this
Windows workstation. They are synthetic operation measurements, not a whole
queue, browser or production speedup.

### 1. Reuse parsed description text - Strong

Files: `src/jobdisco/job_text.py:139`, `:76`, `src/jobdisco/review.py:221`.

The selection step parses provider HTML to check whether it is readable; the
qualification combiner parses that same selected value again. Keep the first
plain rendering for the remainder of that operation. Preserve the raw return
when there are no extra sections, and preserve the generated HTML and `kind`
when there are. No persistent cache or new module is needed.

| Synthetic detail workload, 100 renders | Current | Prototype | Ratio |
| --- | ---: | ---: | ---: |
| HTML with qualification fields | 507.310 ms | 267.410 ms | 1.897x faster |
| HTML without qualification fields | 491.718 ms | 485.751 ms | 1.012x, essentially unchanged |

The first workload makes three HTML-parser calls per detail today; the prototype
makes two. This provides measured leverage within the existing description
module and keeps text selection and assembly local. The deletion test says to
remove repeated work inside the module, not introduce a new parser abstraction.

This is the first recommendation: a small internal change with exact-output
checks and a directly measured benefit. It reduces work, not database size.

### 2. Cache repeated ranking values within one sort - Worth exploring

Files: `src/jobdisco/ranking.py:181` (`rank`) and `:209` (`order`).

Ranking repeatedly classifies the same titles and parses repeated publication
and observation timestamps. The prototype retains the original rank calculation
but uses three operation-local caches, each bounded to 4,096 strings. Non-string
values use the original helper directly, preserving existing handling of values
such as arrays in date fields. Caches are discarded after the sort.

| Synthetic workload, 2,002 groups | Current | Prototype | Ratio |
| --- | ---: | ---: | ---: |
| 25 repeating titles, repeating timestamps | 14.565 ms | 4.207 ms | 3.462x faster |
| Unique titles, repeating timestamps | 14.923 ms | 8.507 ms | 1.754x faster |
| Unique titles and timestamps | 14.541 ms | 16.064 ms | 10.5% slower |

Both versions remain O(n log n) due to sorting; this reduces repeated key
computation. It adds temporary memory and code, and loses when reuse is absent.
Profile representative queue inputs before applying it. Do not use a global
cache or trust a stored bucket: current classification must still be recomputed.

### 3. Concentrate decision matching - Worth exploring

Files: `src/jobdisco/applications.py:104`, `:150`, `src/jobdisco/review.py:212`.

The `queue` function spans 332 source lines including comments and combines
decision replay, alias lookup, eligibility, grouping and history projection.
Its nested matching logic and the 27-line `describes_decision` separately carry
the same facts about provider changes, title agreement and identity aliases.

Keep the existing queue and detail interfaces, but concentrate decision matching
in one cohesive internal module so both consumers use the same identity rules.
That improves locality and gives tests leverage over both callers. Preserve
legacy URL fallback, replay order, reused-URL protection and missing-alias
behavior exactly. No schema or ledger migration is required for that design.

The deletion test protects the identity logic: deleting it would spread its
requirements across both callers. The opportunity is consolidating that logic,
not deleting checks or creating a collection of pass-through functions. A lower
total line count is not yet measured, and this structural idea has not been
prototyped. Verify queue/detail agreement on the existing provider-change and
URL-reuse fixtures before any implementation.

## Recommendations excluded

- Do not remove the two storage merge stages based on appearance: batch URL
  and identity transitions can make their inputs different.
- Do not slim more payload fields, remove HTML variants, compress/rewrite logs,
  change schemas or alter databases to obtain savings.
- Do not merge the PhD and experience policy heuristics during a behavior-
  preserving cleanup; today's differences include both deliberate policy and
  the independently reproduced defects above.

An HTML architecture report with before/after diagrams is also provided in the
workstation OS temp directory, outside the repository.
