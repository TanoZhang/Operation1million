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

| Group | Queries | Page credits |
| --- | ---: | ---: |
| A | 15 | 146 |
| B | 13 | 65 |
| C | 13 | 39 |
| Internships | 11 | 22 |
| Total | 52 | 272 |

The daily ceiling is 280, leaving 8 credits for explicit company fallbacks.
The catalog currently configures none. Each query has a fixed allocation of
1..20 pages. A batch requests `num_pages` once; a full result or returned cursor
never expands the plan. The plan is rejected before collection if all configured
functional and company allocations would exceed the ceiling. Allocations are
initial choices, not measured optimal values.

Requests use `/jsearch/search-v2`, `country=us`, `date_posted=3days`, and
`employment_types=FULLTIME,INTERN`. Queries contain positive functional phrases;
there are no city/state expansions or negative search terms.

The quota is 10,000 page credits per billing period. The operating target is
`floor(10000 * 0.95) = 9500`; the configured daily ceiling is 280. On a 31-day
period the monthly guard may stop collection before the daily
allocation is exhausted. `billing_cycle_start_day` is 17, matching the current
subscription billing anchor. Days use UTC.

`.local/jsearch_usage.sqlite` reserves the requested page count before sending.
Reservations survive errors, timeouts and restarts. `jsearch_pages_used` reports
these conservative reservations, not independently verified provider billing;
an empty/failed batch may have a lower actual charge. No automatic refunds occur.
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
daily searches and not a permanent edit to the configured `today` default.
For a one-keyword test, default to one page and one reserved credit. Do not
expand to all 52 keywords or retry paid failures without a new instruction.

```powershell
# One keyword, last week, at most one page/credit. Paid when executed.
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch-only --jsearch-query "Design Verification Engineer" --jsearch-pages 1 --date-posted week --jsearch-budget 1 --no-store

# Add --jsearch-plan to preview the same command without any API call.

# All 52 functional queries over one week: up to 272 reserved credits.
# Direct sources and company fallbacks are skipped by --jsearch-only.
.\.venv\Scripts\python.exe -m jobdisco.collector --jsearch-only --date-posted week --jsearch-budget 272
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
source checkpoints are appended to the open day's gzip stream. Finalization
writes an atomic checksum manifest and seals the day. A second persistent run
on that UTC date is refused. Interrupted, unsealed days require inspection before
retry; no automatic repair or overlapping writers are supported. API failures
are recorded without discarding earlier successful source checkpoints.

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
