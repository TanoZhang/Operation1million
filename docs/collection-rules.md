# Collection Rules and Daily Discovery Design

These rules apply to agents, manual diagnostics, and automated collection.
They prioritize low request volume and truthful coverage reporting.

## Current source decisions

The active catalog contains 35 companies after removing Rambus and Ventana
Micro. Their company rows, source rows, and JSearch fallback entries are removed.
Historical run artifacts remain evidence of their original collection dates.

The September 16 handoff reported working direct routes for all 35 remaining
companies. This is a route-availability result, not proof that all 35 boards
were downloaded completely. Rivos uses a third-party Uplers company page;
15 records were observed and completeness remains unverified.

The following counts were reported in that handoff. They change over time and
were not re-fetched while documenting these rules.

| Company | Public list endpoint | Observed total | Observed page size | Estimated list requests |
| --- | --- | ---: | ---: | ---: |
| AMD | careers.amd.com/api/jobs | 1,231 | 10 | 124 |
| Micron | careers.micron.com/api/pcsx/search | 2,941 | 10 | 295 |
| Microsoft | apply.careers.microsoft.com/api/pcsx/search | 2,346 | 10 | 235 |
| Qualcomm | careers.qualcomm.com/api/pcsx/search | 1,981 | 10 | 199 |

Eightfold returns `data.positions` and `data.count`. Positions include `name`,
`locations`, `positionUrl`, and `postedTs`; pagination uses `start` and `num=10`.
AMD returns `jobs` with fields inside each item's `data` object and reports
`totalCount`; pagination uses `page=1,2,...`. Keep raw records alongside the
normalized title, location, URL, ID, and posting timestamp.

Use the configured public list endpoints instead of fetching thousands of
detail pages through a sitemap when the list already contains the needed fields.
An inaccessible apply-v2 or iCIMS route does not prove that every official
public route is unavailable. Discover alternatives from the public site itself;
stop at verification challenges rather than attempting to evade them.

## Request pacing and stop conditions

| Source or response | Required behavior |
| --- | --- |
| Microsoft | At least 3 seconds between requests; one worker; no overlapping collector/diagnostic process |
| Micron and Qualcomm | At least 2.5 seconds between requests; sequential pages |
| AMD and other sources | At least 1 second between requests; sequential pages |
| HTTP 429 | Stop the source immediately for this run; no retry loop; persist a cooldown of at least 15 minutes or Retry-After, whichever is longer |
| HTTP 503 | Up to three retries, waiting at least 5, 10, then 20 seconds; honor a longer Retry-After |
| Retry-After greater than 60 seconds on 503 | Defer the source with a persisted cooldown instead of blocking or retrying early |
| Exhausted 503 retries | Stop the source and persist a cooldown of at least 15 minutes |
| HTTP 401/403/405 or a detected human verification page | Stop the source, record the cause, and persist at least a 24-hour pause; review the cause before retrying |

Intervals are conservative project policy, not published provider rate limits.
Receiving HTTP 200 after a pause does not prove the cause was IP-based or that
the next request will succeed. Repeated 429s require a longer pause and review.
Do not delete cooldown state, change identity/IP, or switch to blocked endpoints
to keep collecting during a pause. Parse both seconds and HTTP-date forms of
Retry-After; never truncate the provider's requested delay.

The collector enforces these intervals even if `--delay` is smaller. Its default
worker count is one, and selecting Microsoft forces one worker for the run.
Cooldowns live in `.local/source_access.sqlite` and survive restarts; this is
operational state, separate from the job catalog. This file does not coordinate
in-flight requests between independent processes, so do not overlap processes.
The validator honors the same cooldowns. Obsolete bulk endpoint guessing is not
part of the project.

Defaults are 400 pages, 10,000 records per source, 25 seconds per direct request,
and 90 seconds for JSearch. Caps are limits, not completeness claims. A 400-page
cap accommodates the reported PCSX totals but future boards may exceed it.

## JSearch usage

See [JSearch daily discovery](jsearch.md) for the fixed plan, title filtering,
page-credit accounting, query manifests, and paid transport stop conditions.
Direct ATS collection runs first. Explicit `--jsearch` then runs nationwide
functional discovery; configured company fallback runs last. Company fallback
alone requires reviewed employer aliases; functional discovery has no employer
blacklist. No paid calls are made by offline tests.

The functional plan contains 52 queries and 310 pages. The daily cap is 316
page credits and the monthly operating target is 9,500 of the 10,000 quota.
Each query reserves its fixed page count before sending, including failures.
Preserve `.local/jsearch_usage.sqlite` across runners and configure the actual
billing anchor. Never increase pages because a result is full.

## Daily incremental discovery

Implemented storage uses one derived SQLite database with `jobs`,
`job_identities`, `source_state`, and `collection_runs`. Persistent evidence is
stored under `JOBDISCO_STORE` (default `data/store`) as daily `.ndjson.gz` files,
checksum manifests and `source_state.json`. SQLite is not committed to Git.

New and changed jobs share the same event stream across direct and JSearch
sources. Compact seen events preserve `last_seen`; `first_seen` means observed
by this collector, not necessarily posted today. Finalized daily files are
immutable. Rebuild the derived database from the restored private log with
`python -m jobdisco.store --bootstrap` on a fresh runner.

A first source pass is full. Later passes may use conditional HTTP, a configured
newest-first watermark, sitemap lastmod, or a full list scan. Only full inventory
coverage may establish closure: query-limited searches, since-window scans,
capped, paused or failed passes cannot retire unseen jobs. A direct scan also
must not close unrelated search-only records for the same company.

Local deduplication saves repeated storage and processing. It does not guarantee
fewer provider requests. Never extend a newest-first optimization to another
endpoint without evidence of its order/date behavior. A posting absent from a
`date_posted=today` search may simply be old or indexed late; search absence is
not evidence of closure. Broader reconciliation is not automatically scheduled.

No schedule or startup item is installed. Hosted execution must restore the
private event history and operational ledgers before collection.

## Maintenance and verification

- Keep schema.sql, migrations, derived SQLite, and fallback aliases consistent.
  A fresh schema must preserve AMD's `amd_careers` provider and the PCSX routes.
- Current validation CSV rows describe the endpoint and time originally tested;
  older iCIMS/app-shell results must not be relabeled as new API successes.
- Prefer offline response fixtures for parser, pagination, pause, and dedupe
  tests. New integration checks should target one company and one page first.
- Keep malformed records isolated, parse nested location objects recursively,
  and retain the original posting timestamp where the provider supplies one.
- Do not alter historical counts or describe the 2026-09-15 run as today's board.
