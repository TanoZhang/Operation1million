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

## Rules with no exceptions

- Run one collector process at a time. Microsoft keeps its dedicated lock and
  minimum three-second interval without shrinking the other worker pool.
- Stop at CAPTCHA, human verification, or access challenges. Never rotate
  identity, address, or endpoint to evade them, and never disable TLS checks.
- JSearch is off by default and costs money. Direct caps, malformed records, or
  valid empty boards never trigger it. Diagnostics start at one explicit credit
  and stop when the stated question is answered.

## Request pacing and stop conditions

| Source or response | Required behavior |
| --- | --- |
| Microsoft | At least 3 seconds between requests; dedicated source lock; no overlapping collector/diagnostic process |
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

The collector enforces these intervals even if `--delay` is smaller. Microsoft
is serialized by its own source lock while unrelated companies continue through
the configured worker pool. The default remains one worker for manual runs;
hosted collection explicitly requests three.
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

The functional plan contains 35 broad queries, each with a maximum page cap.
Internships run first (105 pages), then New Grad (90), Early Career (70), and
General (55). Each asks for one page at a time and stops when the provider
returns a short page, so actual use may be below its cap. The daily cap is 320
page credits and the monthly operating target is 9,600 of the 10,000 quota,
which is exactly 320 a day for thirty days.
Each HTTP call reserves one page credit immediately before sending, including
failures. A full page may advance within the query's runaway guard; a short page
ends that query. Preserve `.local/jsearch_usage.sqlite` across runners and
configure the actual billing anchor.

## Daily incremental discovery

Implemented storage uses one derived SQLite database with `jobs`,
`job_identities`, `source_state`, and `collection_runs`. Persistent evidence is
stored under `JOBDISCO_STORE` (default `data/store`) as daily `.ndjson.gz` files,
size-bounded same-day shards, checksum manifests and `source_state.json`. SQLite
is not committed to Git.

New and changed jobs share the same event stream across direct and JSearch
sources. Compact seen events preserve `last_seen`; `first_seen` means observed
by this collector, not necessarily posted today. Finalized daily files and
shards are immutable. The active UTC day rolls to a numbered shard before an
append would exceed 90 MB, keeping every Git blob below GitHub's 100 MB hard
limit. Rebuild the derived database from the restored private log with
`python -m jobdisco.store --bootstrap` on a fresh runner.

A first source pass is full. Later passes may use conditional HTTP, a configured
newest-first watermark, sitemap lastmod, or a full list scan. Only full inventory
coverage may establish closure: query-limited searches, since-window scans,
capped, paused or failed passes cannot retire unseen jobs. A direct scan also
must not close unrelated search-only records for the same company.

An incomplete last pass forces a full retry, and only complete inventories
advance HTTP validators. A sitemap detail can be skipped only when its URL is
already open locally and its timezone-aware lastmod proves it unchanged.
Unknown URLs, relisted closed jobs, changed pages and ambiguous dates are read.
This can require more detail requests than the former unconditional known-URL
skip; configured pacing, caps and cooldowns continue to apply.

Even a pass labeled complete may expose a broken upstream count or empty board.
Before applying closures, the store compares candidate closures with the open
inventory for that company/provider. More than 25% trips a fuse: no jobs close,
the source becomes partial, its success watermark does not advance, and the
report records the blocked count and ratio. Exactly 25% remains permitted.

Local deduplication saves repeated storage and processing. It does not guarantee
fewer provider requests. Never extend a newest-first optimization to another
endpoint without evidence of its order/date behavior. A posting absent from a
`date_posted=3days` search may still be old or indexed late; search absence is
not evidence of closure. Broader reconciliation is not automatically scheduled.

The authorized VPS systemd timer runs daily at 04:38
`America/Los_Angeles`. Collection preserves private event history and operational
ledgers. GitHub Actions is a manual fallback, not a second daily schedule;
manual workflow dispatches keep JSearch off unless the paid-search input is
explicitly enabled. No local startup item is installed.

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

## What the title filter may and may not decide

The rules live in `[filter]` in `data/config/jsearch_queries.toml`, and
`jsearch.rejection_reason` applies them in this order:

| Stage | Question | On a match |
| --- | --- | --- |
| `exclude_employer_patterns` | An employer never to apply to | rejected |
| `exclude_title_patterns` | A title that settles it against the posting | rejected |
| `evidence_title_patterns` | A title trusted in neither direction | scored; kept only at or above `min_confidence` |
| `keep_title_patterns` | A title that names the trade outright | kept, unscored |
| `reject_title_patterns` | A title that names another trade | rejected |
| relevance score | What the posting's own text says | kept at or above `min_confidence` |

**A hard reject is for a title that alone settles it.** It runs before every
keep and no description can overturn it, so a word with any ordinary reading in
this trade does not belong in it. `device`, `process`, `test`, `validation`,
`verification`, `silicon`, `hardware`, `software`, `digital`, `IC`, `memory`,
`embedded` and `firmware` are all such words, and none of them appears in the
list on its own: `Device Validation Engineer`, `Silicon Test Engineer` and
`Embedded Software Engineer` are postings worth seeing. The list holds phrases
-- `device integration`, `process engineer`, `thin film` -- and the seniority
and function words that are unambiguous alone: `senior`, `manager`, `director`,
`sales`, `marketing`, `technician`. `Staff` and `Principal` are deliberately
not among them.

**A hard keep is equally narrow**, because it skips scoring entirely. It holds
`RTL`, `ASIC`, `FPGA`, `SoC`, `VLSI`, `DFT` and the named verification and
design disciplines -- never a bare `silicon`, `hardware`, `validation` or
`verification`, which every adjacent industry prints too.

**Evidence titles are the middle case.** `RF Engineer` is not this trade and
`RFIC Digital Verification Engineer` plainly is, so the name decides neither
and the title and posting's own text provide relevance evidence. A posting with
no readable description is retained; location and employment metadata do not
count as description evidence. Whatever survives is marked in the review queue,
because it got in on its text and not on its name.

When in doubt, keep the posting and let `jobdisco/ranking.py` sort it downward.
A posting ranked too low is one scroll away; a hard-rejected one leaves no row
in `jobs` at all, and only `seen_jobs` remembers it was ever offered.

## Board row identity

A board row's identity is its requisition, not the words in its URL. Apple
advertises one role at many stores, so postings share a slug and differ only in
the requisition before it; taking the slug made forty of them one identity and
retired thirty-nine. Renesas publishes no id of its own and puts the number at
the end of the slug instead -- `/job/-in-hitachinaka-ibaraki-japan-jid-6866` --
so all 899 of its postings were identified by a URL built from their title and
location, and a retitled or relocated one read as a withdrawal beside an
arrival. Both are read out of the URL now.

Identity and content are separate questions. The same requisition retitled,
relocated, rewritten and reslugged leaves one posting, current in every field,
with nothing new and nothing closed.
