# JSearch daily discovery

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
| A | 15 |
| B | 13 |
| C | 13 |
| Internships | 11 |
| Total | 52 |

The daily ceiling is 320. No query declares a depth. Every call asks for
`num_pages=1` and the next page is requested only when the last one came back
full, so a query stops where the provider runs out rather than where a guess
said it would. The provider states no total, so any declared allocation was
either waste or truncation: measured over 52 queries, not one filled the pages
it had reserved, and the plan used 43.5% of the capacity it paid for.

A page is therefore the unit of both billing and loss. Four calls asking for 11
to 18 pages once returned HTTP 504 and were charged 61 credits for nothing; the
same failure now costs one credit.

`max_pages_per_query` is a runaway guard, not an allocation. It stops a provider
whose pages never run short -- or that repeats a page instead of advancing --
from spending the whole day on one query. Set it far above any real depth.

Tier A is paged to exhaustion before tier B begins, and within a tier every
query takes one page per round. Spending the budget depth first would leave the
tail of the plan unreached every day, always the same queries.

The plan is rejected before collection if it holds more queries than the daily
budget has credits, because the tail could then never reach a first page.
Allocations are
initial choices, not measured optimal values.

Requests use `/jsearch/search-v2`, `country=us`, `date_posted=3days`, and
`employment_types=FULLTIME,INTERN`. Queries contain positive functional phrases;
there are no city/state expansions or negative search terms.

The quota is 10,000 page credits per billing period. The operating target is
`floor(10000 * 0.96) = 9600`; the configured daily ceiling is 320. On a 31-day
period the monthly guard may stop collection before the daily
allocation is exhausted. `cycle_start` is `2026-09-16` and periods roll every
30 days from that verified anchor. Days use UTC.

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
expand to all 52 keywords or retry paid failures without a new instruction.

```powershell
# One keyword, last week, at most one page/credit. Paid when executed.
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch-only --jsearch-query "Design Verification Engineer" --jsearch-pages 1 --date-posted week --jsearch-budget 1 --no-store

# Add --jsearch-plan to preview the same command without any API call.

# All 52 functional queries over one week, bounded by an explicit budget.
# Direct sources and company fallbacks are skipped by --jsearch-only.
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch-only --date-posted week --jsearch-budget 320
```

## Backfill sweep

Credits do not carry into the next cycle, so the last three days spend what the
daily passes left. `--backfill` looks a month back instead of three days, pages
to `backfill_max_pages_per_query` (200) instead of 40, and is not held to the
daily slice -- that slice only paces a month that is now ending. The monthly
target still binds, and always does.

The sweep is one pass spread over those days, not three passes. A cursor per
query and cycle records where paging stopped, so the next day resumes at the
following page rather than re-buying pages the sweep already holds. A daily run
never reads that cursor.

The budget is what the cycle has left divided by the days that remain -- a third
with three days to go, a half with two, all of it on the last day -- so a sweep
that fails has a later day to recover in.

The cycle rolls every `cycle_days` (30) from `cycle_start`, not on a day of the
month, so the window is computed from the ledger rather than from a cron date.

```powershell
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch-only --backfill
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
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch-plan

# Explicit paid daily run, after reviewing configuration and account usage.
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch
```

Without `--jsearch` or a positive `--jsearch-budget`, paid discovery is off.
A positive budget without `--jsearch` enables configured company fallbacks only.
With `--jsearch`, a lower override must accommodate the entire fixed plan; the
collector never silently truncates it. Use a separate small TOML plan for an
authorized transport test. `--company` limits direct sources, not nationwide
functional discovery.

JSearch runs sequentially with at least 0.25 seconds between dispatches and a
90-second timeout. HTTP 429/503 stops the remaining search queries and persists
at least a 15-minute account pause; honor a longer `Retry-After`. HTTP 401/403
persists at least 24 hours. Other transport failures retain reserved credits and
are recorded without an automatic paid retry.

## Filtering and retained content

Reject obvious unrelated title directions from configured patterns. Keep
ambiguous mixed titles containing verification, RTL, FPGA, digital, formal or
DFT. Employer names are not blacklisted. Missing experience, ordinary Engineer
titles and seniority labels do not cause automatic rejection. No ML ranking is
performed. Rejected rows are counted; accepted rows enter the shared store.

Full descriptions, qualifications, skills, salary, visa/clearance and unknown
fields remain in `raw`. Known logos, reviews, benefits and presentation/debug
noise are removed. Description HTML is removed only when equivalent full plain
text is retained; HTML-only descriptions survive.

## Shared durable history

Direct and JSearch jobs use the same `jobs` table and daily log. Stable JSearch
IDs deduplicate across queries even if apply URLs change. Provider IDs are scoped
for direct sources; missing IDs fall back to normalized URLs. Matching direct
URLs remain authoritative and receive search enrichment. Distinct URLs with no
shared identity cannot always be recognized as the same posting.

`JOBDISCO_STORE` selects the persistent root (default `data/store`):

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
root and run `python -m jobdisco.store --bootstrap`; checksum verification runs
before replay. `--export` is a one-off backfill into an empty log root only.
SQL schema and migrations remain versioned; SQLite and collected data do not
enter the code repository. Transient `runs/<timestamp>/` JSONL/CSV files remain
private snapshots and are not the durable source of truth.

Search results are always query-limited. Their absences never close jobs, even
when every planned page succeeds. `3days` is the requested overlapping discovery
window, not a guarantee against delayed indexing or missed listings. Direct sources
continue to supply independent coverage; no automatic wider-window search or
extra paid pages are added.

The private GitHub Actions workflow runs the fixed plan once daily at 06:17
`America/Los_Angeles`. A bounded live transport test on 2026-09-17 used one
credit and returned 10 raw jobs: 9 accepted, 1 rejected, and 0 malformed or
failed. Manual dispatches keep paid discovery off unless explicitly enabled.
See [GitHub Actions](github-actions.md) for the private state boundary.
