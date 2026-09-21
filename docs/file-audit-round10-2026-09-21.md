# File audit, round 10: collector

## Scope and evidence

Inspected all of `src/jobdisco/collector.py`, including the provider branches
and nested functions in `main`, before moving to another module. New root causes
are B50-B57. B45 has a remaining direct-intake instance and is not counted again.
No business-code changes, priority labels, external collection or paid requests.

Tested clean source: `D:/Operation1million`, commit
`79fe1690dee09a7c8d4afc11e1679eb7ae24a6cd`. Both `origin/main` and
`origin/claude` pointed there during inspection. The audit worktree was
fast-forwarded to that commit before writing artifacts. The newest handoff
reports B44-B49 fixed; this report uses that fixed tree, not the previous one.

Every numbered case below runs `collector.main` against synthetic HTTP responses
and real temporary SQLite/log state. B57 also builds the real Review queue.
No claim is made about live provider responses or production incidence.

Reproducer: `docs/audit-repro-round10-2026-09-21.py`, using the reusable `run`
helper from round 5 without executing that older script's defect assertions.

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round10-2026-09-21.py
```

It passes all eight new cases, the B45 follow-up, nine positive JSON
normalization controls and ten positive HTML extractor controls. A preliminary
Workday control used an incorrect expectation for an underscore-free path;
the final control uses the supported `/job/RTL_A` shape. This was a fixture
correction, not a reported product defect.

Existing offline tests also pass, 119 total, no skips:

| Module | Tests | Measured time |
| --- | ---: | ---: |
| `test_collect_sql_sources.py` | 23 | 0.358 s |
| `test_store.py` | 83 | 4.652 s |
| `test_collection_policy.py` | 13 | 0.197 s |

All three commands exited 0. The store suite intentionally prints a synthetic
`MISMATCH` for its checksum-negative test; that is not a production verification
result. Existing passing tests do not cover the new counterexamples.

## B50: HiBob preprocesses the whole batch before item-level fault isolation

Location: `collector.py:582`, especially the loop at `collector.py:589`.

`Collector.add` catches malformed records individually, but the HiBob branch
first rewrites URLs and locations for the entire response outside that boundary.
One item missing `id` raises before any item reaches `add`.

Tested a `jobAdDetails` list containing a valid RTL job followed by a record
without an ID. The complete pass returns exit 2, source status `failed`, reason
`KeyError: 'id'`, and zero stored jobs. The valid sibling is lost too.

Suggested correction: move adapter preprocessing into the per-item protected
path. Record the malformed item, save valid siblings and return `partial`.
Merely broadening the exception handler around the whole adapter still loses
the valid batch. This is distinct from the previously repaired exception types
inside `add`: this failure happens before `add` is called.

## B51: Eightfold's collection-time cutoff skips unseen older postings and edits

Locations: `collector.py:407`; selection of the cutoff in `store.py:168`.

After one successful full pass, `store.plan` selects `since` with
`last_success_at`. The collector only admits records whose `postedTs` is later
than that collection timestamp. It does not check whether an older record is
already known before excluding it, and never refreshes its description/title.

The synthetic listing remains correctly sorted newest-first:

1. Initial full pass stores A, published yesterday.
2. The next response contains previously unseen B, also published yesterday but
   newer than A, followed by A with an edited title.
3. Two consecutive passes both report `complete`; only A remains stored, with
   its original title. B is never stored.

A late appearance in the index or a publisher retaining its original posting
date is sufficient to trigger the defect. Sorted pagination alone does not
guarantee that every newly visible or edited record has a newly assigned
publication timestamp. This is an input-contract counterexample, not evidence
that a particular live Eightfold board produced it during this audit.

Suggested correction: separate publication time from observation/update
checkpoints. Preserve useful incremental collection with an overlap window and
periodic full reconciliation; compare identities for already returned rows.
The tested failure persists on repeated successful `since` passes. Manual/full
recovery can still rediscover it; global irrecoverability is not claimed.

## B52: A page-scoped ETag is treated as a validator for the whole board

Locations: `collector.py:308`, `collector.py:567`.

The first response ETag is saved as source state. A later conditional 304 ends
the entire source, even when the original inventory required multiple pages.
An ETag for the first page does not establish that later pages are unchanged.

Tested a SmartRecruiters-shaped board whose configured URL explicitly contains
`offset=0&limit=100`, so the probe targets exactly the same first-page URL:

- First pass reads A on page 1 and B on page 2; page 1 supplies an ETag.
- In the next synthetic scenario page 1 is unchanged, but page 2 would supply C.
- The second pass performs only the conditional request, reports `unchanged`
  and leaves A/B in the store. The queued page-2 response is never requested.

This test models a valid page-scoped validator. It does not assert that the
live SmartRecruiters endpoint currently sends that ETag. Related to B26's TI
shell issue, but the missing boundary here is between pages of the same API;
discarding TI shell validators does not fix it.

Suggested correction: use conditional whole-source completion only with a
validated collection-wide resource. Otherwise validate each page or retain a
full/incremental listing strategy that examines the rest of the inventory.

## B53: Missing requisition IDs become fabricated valid URLs

Locations: `collector.py:129`, with related construction at lines 134, 137 and
139 and Workday's path construction at line 124.

Oracle normalization stringifies a missing ID into `/job/None`. Because that
string has a public HTTP shape, the malformed record is accepted. Similar
unguarded URL synthesis exists in other adapters; only Oracle's persistence
effect is asserted by this reproducer.

Tested two passes: first five valid Oracle requisitions, then four valid ones
plus a title-bearing record with its ID missing. The second pass reports
`complete`, stores `https://example.test/job/None`, and closes the original
requisition 5. The pass inferred a withdrawal from a record it could not
identify, rather than marking its inventory incomplete.

Suggested correction: require the provider fields used to construct the link
before synthesizing it. Missing IDs/paths are malformed unless an independent
valid per-job link can safely identify the record. Do not substitute literal
`None`, a board root or another shared placeholder.

## B54: A page with no accepted rows is mistaken for a repeated page

Location: `collector.py:412` through `collector.py:423`.

Pagination uses `added == 0` to infer that the provider ignored pagination.
That counter measures accepted, deduplicated rows, not whether raw page
identities repeated. A page containing only malformed records also yields zero.

Tested a Workday-shaped response with total 2: the first page has one malformed
record, and a prepared second page has a valid role. The collector makes one
request, never reads the valid page, saves no jobs, and reports:

`1 malformed records rejected. Repeated page; provider ignored pagination`

The result is correctly partial, so this case does not falsely authorize
closure. Its defect is avoidable loss of subsequent valid pages and an
incorrect diagnosis of the provider.

Suggested correction: detect repeated pages from source-page identities or a
raw-page fingerprint, separately from accepted-job counts. Advance a bounded
page containing rejected items while retaining the partial status and caps.

## B55: `--no-store` creates a missing job database

Location: `collector.py:782` through `collector.py:785`.

The missing-database branch calls `store.bootstrap(args.db)` before honoring
`args.store`. That rebuilds the persistent job index even though the option's
help promises to leave the job store untouched.

Tested with a nonexistent temporary DB, `--no-store`, an empty source list and
no network. The run exits 0 but creates the database with 35 catalog companies.
This uses the real bootstrap implementation, not a simulated file write.

Suggested correction: load the catalog through a temporary database, as the
plan-preview path already does, when a no-store run has no existing catalog.
Keep collection outputs in the explicitly requested run directory.

## B56: Partial JSON-LD suppresses a complete HTML inventory

Locations: `collector.py:241` and `collector.py:242`; completion at the end of
`collect_html`, `collector.py:475`.

Finding any structured JobPosting causes `html_items` to return immediately,
without examining job links. A page may publish structured metadata for only a
subset of the jobs it visibly lists. The presence of JSON-LD is not a count or
a completeness declaration.

Tested an Achronix-shaped page listing five valid job links. The first pass
stores all five. The second page still lists all five but also includes
JSON-LD for the first four. The collector extracts four, reports `complete`,
and closes the fifth job despite its link still being present in the HTML.
The real store closure fuse does not trigger for this one-of-five reduction.

Suggested correction: reconcile structured entries and supported HTML links
by per-job identity/URL, or require an explicit completeness signal before
allowing a subset to replace the inventory. Avoid returning early solely
because at least one structured record exists.

## B57: Sitemap detail fallback discards already downloaded job requirements

Locations: `collector.py:520` through `collector.py:527`.

When a detail page has no JobPosting JSON-LD, the fallback keeps only the H1
title and URL. The complete fetched HTML and its visible description are both
discarded. Downstream filtering cannot recover requirements that were read
from the provider but never retained.

Tested an Akeana-shaped sitemap linking to a page containing:

```html
<h1>RTL Engineer</h1>
<section>5 years of experience required.</section>
```

The pass reports `complete`; persisted raw contains only title and URL. The
real Review queue has one pending group because the experience requirement
has disappeared. No additional request would be needed to retain this evidence.

Suggested correction: preserve the fetched detail page or extracted description
in raw alongside the fallback title. Feed that retained evidence through the
same experience/relevance extraction as other provider records.

## B45 follow-up: the direct path still lacks post-cleaning validation

Locations: `collector.py:157`, `collector.py:159`, `collector.py:338`.

Round 9's correction validates cleaned fields in paid intake. Direct intake
still returns a whitespace title as an empty normalized title. `add` sees no
exception, so the failure occurs later in SQLite outside per-item isolation.

Tested a Greenhouse page containing one valid title and one whitespace title.
`collector.main` raises `IntegrityError: CHECK constraint failed:
length(trim(title)) > 0`; zero jobs are stored, including the valid sibling.
This is the same normalized-record contract as B45 and is not a ninth new bug.
Move shared validation to the common boundary so both intake paths benefit.

## Function coverage ledger

All functions below were read through their calling paths. Runtime coverage
means the specific synthetic cases or existing tests, not exhaustive input or
live-provider validation. Every provider selector in `html_items` has a positive
extraction control; every member of `JSON_PROVIDERS` has a positive normalization
control. Those controls do not establish live endpoint compatibility.

| Functions / branches | Evidence and result |
| --- | --- |
| `source_lock` | Read lock scope; existing Microsoft versus other-company concurrency test passed |
| `config`, `load_sources` | Read configuration and both source-table queries; schema and no-store/bootstrap tests passed |
| `query_url`, `clean`, `location_text`, `posted_from_text` | Read query rebuilding, plain/HTML cleaning and date/location conversions; existing normalization tests passed |
| `normalize` | All nine JSON provider controls; B53 and remaining B45 validated |
| `jsonld` / nested `walk`, `html_job_id`, `html_items` | Read recursion, fallback IDs, all link selectors; ten HTML controls; B56 validated |
| `reported_total` | Read all provider count paths; existing stated-zero and contradictory-empty-page tests passed |
| `Collector.__init__` | Read session, strategy, validators, policy and known/listed state initialization |
| `Collector.fetch` | Read pacing, status/retry/challenge handling and validators; 13 policy tests passed; B52 validated |
| `Collector.add` | Read rejection, deduplication and caps; B53, B54 and B45 follow-up |
| `Collector.collect_json` | Traced all paging branches: Workday, Phenom, Oracle, SmartRecruiters, Amazon, Eightfold, AMD, Greenhouse, Ashby; B51/B54 plus existing cap/count/repetition tests |
| `Collector.collect_html` | Read total-pages, next-link, jobs2web offsets and Apple/Google terminal handling; B56 plus existing terminal and cap tests |
| `Collector.collect_sitemap` / nested `unchanged` | Read listed versus fetched sets, lastmod filtering, detail failures and cap accounting; B57 plus existing sitemap tests |
| `Collector.run`, `Collector.collect` | Read cap override, conditional probe, HiBob, TI effective provider, dispatch, exceptions and cleanup; B50/B52 plus existing TI tests |
| `employer_normalize`, `employer_matches`, `fallback` | Read alias normalization, legacy fallback client, budget/error handling; existing employer/no-key/fallback tests passed; no new legacy-helper defect reported |
| `summary_block`, `write_csv` | Read totals and serialization; exercised by complete main runs, no additional formatting defect asserted |
| `main`, `main_cli` | Read arguments, plan preview, source selection, run guard, collection, reports and exit status; B55 and all end-to-end fixtures |
| Nested `sweep_depth`, `direct`, `persist`, `seal` | Read depth, worker results, malformed handling, log-before-commit and failure seal; existing rollback and completed-source persistence tests passed |
| Nested `query_source`, `checkpoint_query`, `persist_query`, `record_seen` | Read paid integration and callback persistence; no paid-provider calls in this audit; detailed JSearch audit is round 9 |

## Continuation

The collector function inventory is complete for this pass. The next planned
module is the full `store.py` lifecycle; this round only followed the storage
paths necessary to validate collector effects. The store test run is not being
represented as a completed manual audit of that whole module.

## Source fingerprints

SHA-256, measured on the tested tree:

```text
collector.py        C43C898A7288550AA403440E2BBF0B041E793984A0BF7D03AB2F9D0CAF592387
validate_sources.py F14847714F85B55D4E7C356E11B100D834A2638E42AB289427DE178C30701B25
store.py            47E10FF21CAFB5CD54372EF370DD9B13C9C81E4518B3E9BDCE4C6C3BFFDFD8D9
```
