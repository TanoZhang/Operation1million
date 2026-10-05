# JSearch daily discovery

## Current trial depths - 2026-10-05

After reviewing the latest measured three-page trial, the user raised all 123
current nationwide trial caps from three to ten pages: the fifteen original
title trials and all 108 newly added queries. The other 47 nationwide caps are
unchanged. There are still 170 queries; caps now total 2,365 (970 Intern/Co-op,
615 New Grad, 260 Entry Level and 520 General). Actual spending remains capped
at 400 per Pacific budget day and 9,600 per UTC cycle. Provider cursors, tier
priority, the 3days search window and final-three-days backfill stay unchanged.

The latest completed measurement is October 5, not a run of the new 170-query
plan. Its fifteen nationwide trials used 21 credits, returned 57 appearances,
accepted 23 appearances and covered 17 distinct accepted URLs. Validation Co-op
explicitly stopped at its three-page guard; ASIC Design New Grad used three
pages but did not report a cap stop. More depth has unmeasured incremental yield.
The 108 newly added terms have not run yet. No extra paid pass accompanies this
configuration change; the next scheduled run reads the ten-page caps.

## Nationwide expansion before the depth increase - 2026-10-05

At the user's request, the daily budget is 400 credits and all twenty state
splits are removed. The 62 existing nationwide queries retain their exact
text, tier and cap. Add 108 nationwide VLSI title trials at three pages each:
48 Intern/Co-op, 28 New Grad, 16 Entry Level/Junior and 16 General.

Coverage includes RTL/ASIC/SoC/FPGA design and verification, formal verification,
DFT/design-for-test, physical implementation, STA/timing/place-and-route,
CPU/GPU/IP verification, memory/SRAM, analog and mixed-signal IC design/layout,
and post-silicon validation. Engineer I and Graduate Engineer names supplement
New Grad. These are discovery trials, not measured gains in relevant jobs;
existing JD-based eligibility and hard rejects still decide what is retained.

There are 170 queries, with independent caps totaling 1,504 pages. The 400-credit
Pacific daily guard and 9,600-credit UTC cycle target bind actual spending.
The monthly quota remains 10,000. The search window stays 3days; the existing
last-three-days month-wide backfill and its separate tier depths are unchanged.
For the current cycle, reset is October 16 at 00:00 UTC (October 15 at 17:00
America/Los_Angeles); the automatic sweep dates are October 13-15 UTC.
Raising a daily ceiling does not guarantee all remaining credits will be spent.

Evaluate new accepted URLs against all original queries and retained history.
Manifest jobs_unique is order-dependent attribution, not historical novelty.
On October 5, the withdrawn state trial spent 22 credits and returned 37 rows,
8 accepted appearances and 6 distinct accepted URLs, all previously observed.

## Historical title-synonym trials - 2026-10-04

The user approved fifteen additional title queries at three daily pages each,
added to Claude's 47-query plan without changing any existing query or cap.
Intern gains Hardware Verification, ASIC Design, Silicon Validation, Hardware
Validation, IC Design, Logic Design, Pre-Silicon Verification and Emulation;
Co-op gains Design Verification, Validation, FPGA and RTL. New Grad gains
Hardware Verification, ASIC Design and Silicon Validation.

That revision had 62 queries: Intern/Co-op 30 (406 capped pages), New Grad
17 (314), Entry Level 6 (100), General 9 (360). Caps total 1,180; the daily
RequestGuard limit was 320. The trials added at most 45 daily pages, subject
to provider cursors and the shared budget. Backfill retains separate tier caps.
No paid run was triggered by this configuration change. Measure incremental
coverage against the original queries and direct sources; manifest jobs_unique
is order-dependent run attribution, not exclusive or historical novelty.

## Historical query plan - 2026-10-03

At the user's request the plan is the user's own list of 43 queries, replacing
the 2026-09-27 re-set and the 2026-10-02/03 trials: Intern 14 queries / 270
pages, New Grad 14 / 290, Early Career ("Entry Level") 6 / 100, General 9 / 55.
Caps now total 715 and may exceed the daily budget: most queries end on a short
page far below their cap, and caps held to 320 left about half of each day's
credits unspent (146 to 185 of 320, 2026-09-26 to 10-01). The budget guard stops
the day at 320; tiers are served in priority order, so on a full day General --
a sweep for a new graduate -- gets what is left, or nothing.

Early-career caps follow the 2026-09-19..26 yield: deepest (25-40) where a query
hit its cap on most days with four or more new accepted postings a page; the
queries that end on their first page keep a cap of 15, which costs nothing on a
day they end early. Eight broad early-career phrasings are on trial at 15 pages:
Electrical / Computer Engineering Intern, Validation Intern, Embedded Hardware
Intern, Hardware New College Grad, Electrical Engineer New Grad, Validation New
Grad, Hardware University Graduate. Judge them, and the deeper caps, by new
accepted postings a page after a week. Request-level publisher exclusions gain
the names JSearch actually reports: JobMESH, JobMesh.io, Virginia Commons
Apartments; on 2026-10-02, the first pass with request exclusions, no blocked
publisher came back.

## Execution order

1. Collect configured direct ATS/board sources.
2. With `--jsearch`, execute the nationwide functional plan.
3. Execute only configured company fallbacks whose direct source failed with
   zero records, or whose configuration explicitly sets `mode = "supplement"`.

Functional discovery may find employers outside the curated company catalog.
It does not add or restore company/source rows. Employer alias checks apply only
to company-specific fallback queries. The HTTP client performs no business
filtering; normalization precedes conservative title filtering.

## Configuration and budget

`data/config/jsearch_queries.toml` is the executable functional plan. The legacy
SQLite `search_queries` table is not executed by this collector.

| Group | Queries |
| --- | ---: |
| Internships / Co-op | 78 |
| New Grad | 45 |
| Early Career ("Entry Level") | 22 |
| General | 25 |
| Total | 170 |

The daily ceiling is 400. Each query declares an independent maximum depth:
Intern/Co-op 970 capped pages, New Grad 615, Entry Level 260 and General 520.
The caps total 2,365; they are not credit reservations. The budget guard stops
the day at 400 and the later tiers get what is left. Every call asks for
`num_pages=1`; missing continuation, a repeated page/cursor, deadline or budget
limit ends paging. A short page with a next cursor still continues.

A page is therefore the unit of both billing and loss. Four calls asking for 11
to 18 pages once returned HTTP 504 and were charged 61 credits for nothing; the
same failure now costs one credit.

`max_pages_per_query` is the ceiling no authored daily query cap may exceed.
It bounds unusually deep results along with the page/cursor loop guard.

The priority order is Intern/Co-op, New Grad, Early Career, then General.
The October 5 expansion explicitly adds narrow VLSI title variants alongside
the original broad role families. Shared JD filtering decides eligibility.

Within a tier every query takes one page per round. Spending the budget depth
first would leave the tail of the plan unreached every day, always the same
queries.

Pagination follows `data.cursor`, never a numeric page or a short-page guess.
A backfill stores the ordinal checkpoint together with the opaque token and
resumes that query in the same cycle. Budget and runtime stops do not mean a
query was exhausted. See the cursor repair evidence below.

The plan is rejected before collection if it holds more queries than its
configured daily budget has credits, because the tail could then never reach a
first page during an ordinary daily pass. A deliberately smaller per-run cap is
valid: the request guard stops that run, and a backfill resumes the shallowest
query cursors first so repeated bounded runs rotate through the plan.

Requests use `/jsearch/search-v2`, `country=us`, `date_posted=3days`, and
`employment_types=FULLTIME,INTERN`. Queries contain positive functional phrases
and no negative search terms. The twenty October 4 state splits were withdrawn
on October 5; all current queries are nationwide.

The quota is 10,000 page credits per billing period. The operating target is
`floor(10000 * 0.96) = 9600`; the configured daily ceiling is 400. At sustained
400-credit use the monthly guard can stop the cycle before its last day.
`cycle_start` is `2026-09-16` and periods roll every 30 UTC dates from that
anchor. The daily budget resets at 04:38 `America/Los_Angeles`, following
daylight saving time. Timestamped reservations are counted within that window,
including existing history. Legacy credit residuals belong to their stored
budget-day labels. Daily and monthly clocks remain separate.

`.local/jsearch_usage.sqlite` reserves one page before each request.
Reservations survive errors, timeouts and restarts. `jsearch_pages_used` reports
these conservative reservations. When present, `X-RapidAPI-Billing` records the
provider-reported charge for comparison; no automatic refunds occur.
The manifest also includes raw/unique/rejected/malformed counts and per-query
details. Unique counts are within this run, not newly inserted jobs; store deltas
separately track new records across days.

Existing undated legacy usage is conservatively imported into the current
period/day. Calls from dashboards or other clients are not visible to this
ledger; reconcile account usage before relying on its remaining balance.
Never delete the ledger to bypass a ceiling or cooldown.

## Commands

### Temporary windows and single-keyword tests

`--date-posted` accepts `all`, `today`, `3days`, `week`, and `month`.
"Pull one week" means a temporary `week` search window, not seven repeated
daily searches and not a permanent edit to the configured `3days` default.
For a one-keyword test, default to one page and one reserved credit. Do not
expand to the whole catalog or retry paid failures without a new instruction.

```powershell
# One keyword, last week, at most one page/credit. Paid when executed.
.\.venv\Scripts\python.exe -m operation1million.collector --jsearch-only --jsearch-query "Design Verification Engineer" --jsearch-pages 1 --date-posted week --jsearch-budget 1 --no-store

# Add --jsearch-plan to preview the same command without any API call.

# All configured functional queries over one week, bounded by an explicit budget.
# Direct sources and company fallbacks are skipped by --jsearch-only.
.\.venv\Scripts\python.exe -m operation1million.collector --jsearch-only --date-posted week --jsearch-budget 400
```

## Backfill sweep

Credits do not carry into the next cycle, so the last three days spend what the
daily passes left. `--backfill` looks a month back instead of three days, pages
to `backfill_max_pages_per_query` (200) instead of 40, and is not held to the
daily slice -- that slice only paces a month that is now ending. The monthly
target still binds, and always does.

`[backfill_tier_pages]` lets the same four priority tiers page deeper during a
sweep: 60, 50, 40 and 30 pages per query respectively.

The sweep is one pass spread over those days, not three passes. A cursor per
query and cycle records where paging stopped, so the next day resumes at the
following page rather than re-buying pages the sweep already holds. A daily run
never reads that cursor.

A cursor is kept under the query *and* the shape of the search it belongs to --
the window, the country and the employment types, all of which decide the
result set. A page number means nothing once any of them changes, so such a
cursor simply does not match and the sweep starts again at page one. `Query.key`
cannot carry this itself: it is also the stored source id of every posting the
query has found. When a bounded sweep cannot touch every query, the next
run starts with the shallowest cursors instead of repeatedly favoring the first
queries in the file.

The budget is what the cycle has left divided by the days that remain -- a third
with three days to go, a half with two, all of it on the last day -- so a sweep
that fails has a later day to recover in.

The cycle rolls every `cycle_days` (30) from `cycle_start`, not on a day of the
month, so the window is computed from the ledger rather than from a cron date.

```powershell
.\.venv\Scripts\python.exe -m operation1million.collector --jsearch-only --backfill
```

`--jsearch-query` replaces the functional catalog for this invocation; its page
default is 1. `--jsearch-pages` is valid only with that single-query option.
`--jsearch-only` explicitly skips direct sources and company fallbacks.
Without it, the normal direct-first execution order still applies.
`--no-store` writes the usual private JSONL/CSV and manifest under a timestamped
`runs/` directory, without changing or sealing daily job history. The shared
quota ledger still records paid attempts. These diagnostic rows do not become
part of the durable job baseline. Do not use this flag for normal daily storage.

Run caps apply to the planned pages for this invocation; the separate daily
and monthly ledger caps include earlier attempts. Window and request defaults
are included in each query's manifest entry. Report raw, accepted, unique,
rejected, malformed, reserved-credit counts and the private result path.
One page is a sample, not proof of complete weekly coverage.

### Normal daily collection

```powershell
# Offline preview: no credentials or API requests required.
.\.venv\Scripts\python.exe -m operation1million.collector --jsearch-plan

# Explicit paid daily run, after reviewing configuration and account usage.
.\.venv\Scripts\python.exe -m operation1million.collector --jsearch
```

Without `--jsearch` or a positive `--jsearch-budget`, paid discovery is off.
A positive budget without `--jsearch` enables configured company fallbacks only.
With `--jsearch`, a lower override deliberately caps that invocation. The fixed
plan is still validated against its configured daily budget, while the request
guard stops before the override is exceeded. `--company` limits direct sources,
not nationwide functional discovery.

JSearch runs sequentially with at least 0.25 seconds between dispatches and a
90-second timeout. HTTP 429/503 stops the remaining search queries and persists
at least a 15-minute account pause; honor a longer `Retry-After`. HTTP 401/403
persists at least 24 hours. Other transport failures retain reserved credits and
are recorded without an automatic paid retry.

`--jsearch-max-seconds` is a graceful paging deadline. It is checked before a
new paid page, so reaching it spends no extra credit and leaves backfill cursors
ready for the next run. Hosted daily discovery uses 1,500 seconds and the
end-of-cycle sweep uses 3,000 seconds, leaving time to seal and push durable
state before the 120-minute job limit.

## Filtering and retained content

Reject obvious unrelated title directions from configured patterns. Keep
ambiguous mixed titles containing verification, RTL, FPGA, digital, formal or
DFT. Configured defense-contractor exclusions are matched against employer names
before scoring and title keep rules. The review queue reapplies these exclusions
to existing stored records without deleting historical evidence. Missing experience, ordinary Engineer
titles and seniority labels do not cause automatic rejection. No ML ranking is
performed. Rejected rows are counted; accepted rows enter the shared store.

Full descriptions, qualifications, skills, salary, visa/clearance and unknown
fields remain in `raw`. Known logos, reviews, benefits and presentation/debug
noise are removed. Description HTML is removed only when equivalent full plain
text is retained; HTML-only descriptions survive.

### Required experience hard pass

The deterministic experience gate runs before title keeps, and Review reapplies
it to existing pending and backlog records without deleting history. It uses
only supplied JD text, not an LLM or an inferred degree credit. Missing or
unrecognized experience is retained. HR and human-resources titles are also
hard excluded; an HR contact in an engineering description is not.

An explicit intern, internship, new grad/graduate, new college grad/graduate or
university graduate signal in the title or JD bypasses only this experience
gate. Early career, entry level, junior and associate do not bypass it.
Required experience above two years is rejected; ranges use their lower bound.
Preferred, desired, nice-to-have, plus, bonus and ideally clauses/sections do
not contribute. Roadmaps, degree durations and program durations are not work
experience. Explicit BS/MS alternatives use the stated MS path; otherwise
separate mandatory requirements use their maximum lower bound.

Debug fields are `entry_override`, `required_experience_years` (the maximum
unadjusted lower bound), `effective_experience_years` (after explicit MS
alternatives), `matched_text`, and `hard_pass_reason`. Unknown bounds are null.
Accepted JSearch raw records retain `experience_filter`; each collector run
also writes `experience_debug.jsonl` alongside its manifest, including rejected
results. Existing Review rows expose the same debug dictionary through the
Python queue API, while the browser payload stays slim. Rejected stored rows
can be inspected with `jsearch.experience_debug` without mutating the database.

## Shared durable history

Direct and JSearch jobs use the same `jobs` table and daily log. Stable JSearch
IDs deduplicate across queries even if apply URLs change. Provider IDs are scoped
for direct sources; missing IDs fall back to normalized URLs. Matching direct
URLs remain authoritative and receive search enrichment. Distinct URLs with no
shared identity cannot always be recognized as the same posting.

`OPERATION1MILLION_STORE` selects the persistent root (default `data/store`):

```text
runs/YYYY-MM-DD.ndjson.gz
manifests/YYYY-MM-DD.json
source_state.json
```

New and changed job records, compact seen/closed events, identity mappings, and
source checkpoints are appended to the open UTC day's gzip stream. Finalization
writes an atomic checksum manifest for its current content. Additional passes on
the same UTC day may append and rewrite that manifest; a day becomes immutable
when the UTC date changes. Handled failures reseal the current day. Overlapping
writers are unsupported.

SQLite is a disposable local index. On a fresh runner, restore the private log
root and run `python -m operation1million.store --bootstrap`; checksum verification runs
before replay. `--export` is a one-off backfill into an empty log root only.
SQL schema and migrations remain versioned; SQLite and collected data do not
enter the code repository. Transient `runs/<timestamp>/` JSONL/CSV files remain
private snapshots and are not the durable source of truth.

Search results are always query-limited. Their absences never close jobs, even
when every planned page succeeds. `3days` is the requested overlapping discovery
window, not a guarantee against delayed indexing or missed listings. Direct sources
continue to supply independent coverage; no automatic wider-window search or
extra paid pages are added.

The private GitHub Actions workflow runs the fixed plan once daily at 04:38
`America/Los_Angeles`. A bounded live transport test on 2026-09-17 used one
credit and returned 10 raw jobs: 9 accepted, 1 rejected, and 0 malformed or
failed. Manual dispatches keep paid discovery off unless explicitly enabled.
See [GitHub Actions](github-actions.md) for the private state boundary.

## Rate limits and overage

The Pro plan the monthly quota matches allows **5 requests per second**, and
10,000 requests a month with overage charged at $0.003 each beyond it. Both
limits are held structurally rather than by hoping:

- `RequestGuard.interval` has a floor of 0.25 seconds, taken under the same
  lock that reserves the credit, so requests leave at most 4 a second however
  many workers a run uses -- 20% under the provider's limit. One page per call
  raised a daily pass from about 30 requests to as many as 320, which is 80
  seconds of throttle and no closer to the limit.
- `monthly_target` stops the guard at 9,600 of the 10,000 the plan includes, so
  no request is ever the one that starts being charged. The provider's own FAQ
  names "automated retries" as the usual cause of an overage bill; a failed page
  here is charged once and never retried.

A 429 or 503 pauses the account for 15 minutes and a 401 or 403 for 24 hours,
both persisted, so a cooldown outlives the runner that earned it. Either one
stops the rest of the pass and exits nonzero: an account-level refusal is not
something a run should carry on through quietly.

## Query yield, measured 2026-09-27

From the data repository's nine daily manifests (2026-09-18 to 2026-09-27) and
the index's paid listings, read against today's filters. "Useful" is a listing
that passes every current rule, is in bands 0-3, and so reaches the review
page; "useful only here" is one no other query found.

**Listings, not records.** 10,867 paid records were 1,491 listings: JSearch
gives a listing a new `job_id` nearly every time it returns it (one Qualcomm
internship under 113 ids). A day buys 1,000-1,800 records, 220-330 distinct
listings, of which 115-205 are new -- about 0.75-1.9 new listings per credit.
Of the 1,291 paid listings stored, 286 (22%) are useful today. Counts in
manifests before 3b38d81 (`jsearch_jobs_unique`, `seen_new`, `seen_existing`)
counted ids and are inflated; they now count listings.

**Spend.** Days used 110-185 of the 320 credits. Most intern, entry-level and
narrow new-grad queries end after one or two pages, while every general query
hit its cap every day with results left. An HTTP 504 ended a query for the day
(15 of 35 queries on 2026-09-24); a server error is now retried once.

| Query | Pages (9 days) | Useful only here | Old cap | New cap |
| --- | ---: | ---: | ---: | ---: |
| Design Verification Engineer | 70 | 18 | 10 | 36 |
| Silicon Intern | 72 | 17 | 10 | 20 |
| ASIC Engineer | 60 | 11 | 9 | 22 |
| Verification New Grad | 50 | 9 | 12 | 16 |
| FPGA Engineer | 61 | 8 | 7 | 16 |
| Hardware Engineer | 48 | 7 | 6 | 14 |
| RTL Engineer | 64 | 7 | 9 | 18 |
| Hardware Engineering Intern | 33 | 7 | 9 | 9 |
| Hardware Entry Level | 14 | 7 | 9 | 9 |
| Physical Design Engineer | 9 | 6 | 1 | 24 |
| Hardware New Grad | 43 | 6 | 8 | 12 |
| Physical Design New Grad | 28 | 5 | 5 | 10 |
| Digital Design New Grad | 72 | 1 | 10 | 3 |
| Digital Design Intern | 49 | 1 | 12 | 3 |
| ASIC Intern, RTL New Grad, DFT New Grad, ASIC/FPGA/Digital Design Entry Level | 7-8 each | 0 | 4-15 | 2 |

The full per-query table and the scripts that produced it are described in the
bug log entry of the same date. What this does not measure: how many more
useful listings the deeper general pages will find, since those pages were
never bought. Re-measure after a week of runs with the new caps; the manifests
now count listings, so that is a direct read.

## Adjacent-query trials - 2026-10-02

Bulk applications now include analog/board design and compiler software. Add
ten two-page trials: analog/board/firmware/compiler intern and new-grad searches,
plus field applications and hardware test entry-level searches. Total caps remain
320; tiers sum to 59 intern, 77 new grad, 30 entry level and 154 general.
Reallocate Silicon Intern 20 -> 10, Verification New Grad 16 -> 10,
Hardware New Grad 12 -> 8. This is a limited allocation trial, not a proven yield
improvement. Historical measurements above are unchanged; current trial yield
must come from future manifests. No paid requests during the keyword audit.
See architecture's record-driven expansion for score/filter evidence and limits.

## Corrected VLSI scope - 2026-10-02

The user clarified that higher application volume means equivalent VLSI names,
not additional disciplines. The d4a7986 compiler/analog/board/FAE/quality expansion
is withdrawn. The briefly proposed blanket software/firmware title ban was never
deployed and is withdrawn too. Restore filter/scoring and ranking exactly to
e456c97: relevant embedded, firmware, driver and silicon/EDA software still pass
through the original title/JD evidence policy; ordinary software stays excluded.

Audit of actual JDs confirms silicon validation uses Embedded C/BIOS to exercise
SoC/IP; STA describes netlists, timing closure, PnR and signoff; DFT describes
scan/BIST/ATPG. Existing rules already recognize these jobs. Only discovery needs
additional names: Logic Design Intern, Formal Verification Intern, Design for
Test New Grad, Physical Implementation New Grad, Static Timing Analysis Entry
Level, Silicon Validation Entry Level. One page each, with two pages reassigned
within each early-career tier. 41 queries, 320 pages, original tier totals intact.
No increase to paid budget and no manual paid collection. Relevant embedded
postings and existing applied/skipped history must not be deleted.


## search-v2 pagination correction (2026-10-04)

The provider's [OpenAPI specification](https://openwebninja.s3.us-east-1.amazonaws.com/portal/openapi/jsearch.yaml)
and [documentation](https://www.openwebninja.com/api/jsearch) define
`data.cursor`, passed as the next request's `cursor`. `page` is not a v2
pagination parameter. Five returned jobs can have another page: a one-credit
production probe of Design Verification Intern on October 4 proved this.
The former `len(jobs) < 10` stop and ordinal API page parameter under-collected
results; October 3's 49 and October 4's 48 pages are not evidence of exhaustion.

The client follows opaque cursors, still one guarded credit per request.
Backfill saves the token and ordinal checkpoint in one transaction after rows
are durable, and versions the search fingerprint so old falsely exhausted
numeric cursors cannot suppress new searches. Repeated cursors stop the run
without marking the backfill permanently exhausted. Daily queries, filters,
3-day window, priority tiers, authored caps and 320-credit daily limit remain
unchanged. Caps are maxima, not a reason to buy nonexistent/repeated pages.
