# SQL Job Source Collection

## Run on Windows

Use Python 3.10 or newer. No startup task, scheduled task, or service is installed.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m jobdisco.collector
```

The new computer has a working project-local `.venv`; run its Python executable directly.
The Windows Store `python` alias is not a usable interpreter on this machine.

The collector reads enabled sources from SQLite in read-only mode. It does not
execute `schema.sql` or change company/source data. The schema can rebuild the
52-company source catalog in a fresh database. Existing richer company metadata
in the supplied SQLite file is preserved.

## Outputs

The retained, verified 2026-09-15 snapshot is in `runs/20260915T190602Z`.
New runs default to `runs/<UTC timestamp>`. `runs/latest.json` points to the
latest verified run; failed or exploratory runs remain separate timestamped
directories.

- `jobs.jsonl`: one job per line, with the original record in `raw`.
- `jobs.csv`: the same nine columns; `raw` contains serialized JSON.
- `company_results.csv`: source counts, request counts, direct status, failure
  reason, fallback status, and remaining work.
- `manifest.json`: UTC collection time, limits, and aggregate counts.
- `<company>_rejected.json`: malformed records isolated from valid results.

Fields: `company_key, company_name, provider_key, title, location, url,
source_job_id, posted_at, raw`.

Missing values stay null/empty. Relative Workday dates remain in `raw`; they are
not converted into invented posting timestamps. HTML records retain the relevant
row markup. Sitemap records are enriched from public detail pages. URLs are
normalized to public job pages. Records are deduplicated by URL within a source,
so location-specific variants of a requisition can remain distinct.

The source board determines geographic scope. Most ATS boards are worldwide;
Apple's configured source is US-only. JSearch uses US role queries and a three-day
posting window. These are discovery results, not a guarantee of every open role.

## Coverage

JSON connectors: Workday, Greenhouse, Ashby, Oracle Cloud, SmartRecruiters,
Cisco Phenom, Amazon search, and HiBob public job ads. Texas Instruments' Oracle
API origin is read from the public career-page base tag.

HTML connectors: Achronix, Apple, Google, TalentBrew (Arm and the current
Synopsys site), Jobs2Web (Celestica and Teradyne), Jobvite, TSMC/Avature, and
Uplers company job cards. JSON-LD JobPosting extraction is shared.

Sitemaps: Akeana and Renesas, with public detail-page enrichment. A source with
an extractor can still fail when the remote site blocks access or redirects to
a product homepage. Such failures are reported rather than counted as zero jobs.

The nine configured company fallbacks skip direct challenge pages. New direct
failures and incomplete sources also attempt JSearch. No challenge solving,
browser impersonation, disabled TLS verification, or CAPTCHA bypass is used.

## Limits and status

Default limits are 100 pages and 10,000 jobs per source, four companies in
parallel, and 0.15 seconds between requests within a company. Use `--max-pages`
and `--max-jobs` to change limits. Requests have a 25-second timeout. Sitemap
collection stops after three detail failures. A malformed record is quarantined
and does not stop later valid records.

```powershell
.\.venv\Scripts\python.exe -m jobdisco.collector --company arm --company synopsys --output runs/selected-run
.\.venv\Scripts\python.exe -m jobdisco.collector --max-pages 600 --max-jobs 20000
```

`complete` means the public API's reported total or an observed end of pagination
was reached. It does not establish that an upstream search index has no hidden
limit. `partial` indicates a cap, malformed record, page repetition, detail
failure, or unverified HTML pagination. `failed` means no jobs were collected.
Exit code 0 means every selected direct source completed; code 2 means the
artifacts were written but at least one source remains incomplete or uses fallback.
Each invocation replaces the files in its output directory; use a different
`--output` to retain previous runs.

## JSearch

Supply `JSEARCH_API_KEY` in the process environment or the ignored `.env.local` file. The collector uses OpenWeb Ninja directly with `X-API-Key`. Never put
keys in source files, reports, or the handoff archive. With no key, the collector
records `missing_credentials` and makes no JSearch request.

The endpoint and headers come from `data/config/sources_search.toml`; fallback
aliases come from `data/config/discovery_queries.toml`, and enabled discovery
queries come from the SQLite `search_queries` table. Employer names must equal a
configured alias or company name after punctuation, case, and trailing legal
suffix normalization. Substring matches such as `AMD Staffing` are rejected.
This conservative filter can miss legitimate subsidiaries; add explicitly
reviewed subsidiary aliases to the configuration rather than weakening matching.

The default is the first page of one role query per fallback company. Increase
`--fallback-queries` for more configured roles. `--jsearch-budget` defaults to 30
and is capped at 30 per invocation. This is not a shared daily budget.

A persistent SQLite ledger in `.local/jsearch_usage.sqlite` reserves each attempt
before dispatch, including failures and timeouts. Across cooperating processes,
requests are serialized and spaced at least 250 ms apart. The local hard limit
is 10,000 attempts. Preserve the ledger when upgrading or restarting. No automatic
reset occurs: reconcile the provider billing cycle and any external usage before
a manual reset. Calls made outside this collector are not visible to the ledger.
The provider dashboard controls account-wide caps; this code does not change them.
Authentication and rate-limit errors stop further calls in the current run.

Fallback results are always marked `query_limited`; they do not prove board
completeness. Search-v2 uses cursor pagination; this collector intentionally only
fetches the first page. No scheduled task or startup item is installed.

## Source corrections and attribution

On 2026-09-15, four missing tuple-opening parentheses in `schema.sql` were fixed.
The schema rebuild and idempotent rerun pass SQLite foreign-key checks.
MatX migrated from Greenhouse to Ashby; its own `https://matx.com/jobs` page embeds
`https://api.ashbyhq.com/posting-api/job-board/matx`. Both SQL and SQLite now use
that endpoint. The removed five companies remain absent.

HiBob's public JavaScript specifies `/api/job-ad` and a `companyIdentifier`
header containing the public tenant subdomain. No private account or login is used.
The implementation was written locally from provider response shapes and public
page markup; no third-party scraper source code was copied.

`research/recover_hard_sources.py` is historical research for removed companies.
It is not called by the active collection pipeline.

## Repository layout

`src/jobdisco/` is the installable package and `tests/` contains its tests.
`data/config/` contains source configuration and schema, `data/raw/` contains
research inputs and validation reports, and `data/db/` contains the SQLite
catalog. Generated run directories live under `runs/`; the large run files are
ignored by Git. Research captures and the historical handoff are outside the
active data path.

## Direct API integration check - 2026-09-16

The direct OpenWeb Ninja key is saved only in ignored local configuration.
Twelve offline tests pass, including persistent cap and concurrent reservation
tests. Three real attempts were reserved: the collector rejected an unexpected
response, a diagnostic request timed out, and the last request returned HTTP 504.
No successful job extraction from the direct API has been verified yet. Do not
interpret these failures as zero available jobs. The local ledger records all
three attempts conservatively; provider billing may count differently.

## Search-v2 response correction - 2026-09-16

Official reference: https://www.openwebninja.com/api/jsearch/docs

Search-v2 returns jobs under `data.jobs` and the next cursor under `data.cursor`.
The collector previously expected `data` to be a list, matching the job-details
response instead of search-v2. The parser and configuration now use the correct
nested job list, and a regression test covers employer filtering on that shape.

The documentation charges one request credit per returned search page. Requests
now explicitly set `num_pages=1`, so the local attempt counter conservatively
covers this search path. Batch job-details calls would need per-ID accounting
before being added; they are not implemented here.

All 13 offline tests pass. One live request completed successfully with ten
results; all ten failed the strict AMD employer-alias filter, leaving zero accepted
jobs. This verifies authentication, transport, and search-v2 parsing, not query
coverage or the absence of AMD vacancies. The run is query_limited and stored in
`runs/20260916T190916Z`. The local ledger now includes four
attempts in total. Earlier timeout/504 results remain historical failures.
