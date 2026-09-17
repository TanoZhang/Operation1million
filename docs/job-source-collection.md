# SQL Job Source Collection

Read [Collection Rules](collection-rules.md) before running network collection.
That document records the September 16 direct API discoveries, request pacing,
stop conditions, and the proposed daily incremental design.

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
35-company source catalog in a fresh database. Existing richer company metadata
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
Apple's configured source is US-only. JSearch functional discovery uses
nationwide US queries and the configured `today` posting window. These are discovery results, not a guarantee of every open role.

## Coverage

JSON connectors: Workday, Greenhouse, Ashby, Oracle Cloud, SmartRecruiters,
Cisco Phenom, Amazon search, HiBob public job ads, AMD Careers, and Eightfold
PCSX (Micron, Microsoft, Qualcomm). Texas Instruments' Oracle
API origin is read from the public career-page base tag.

HTML connectors: Apple, Google, TalentBrew (Arm and the current
Synopsys site), Jobs2Web (Teradyne), Avature, and
Uplers company job cards. JSON-LD JobPosting extraction is shared.
Rivos is a third-party Uplers profile with unverified coverage, not an official board.

Sitemaps: Renesas, with public detail-page enrichment. A source with
an extractor can still fail when the remote site blocks access or redirects to
a product homepage. Such failures are reported rather than counted as zero jobs.

There are no configured company fallbacks after removing Rambus and Ventana
Micro. Paid search is disabled by default. When explicitly enabled, it can be
used for nationwide functional discovery and explicitly configured company
fallbacks. Caps, valid empty boards, and paused sources do not trigger fallback. No challenge solving,
browser impersonation, disabled TLS verification, or CAPTCHA bypass is used.

## Limits and status

Default limits are 400 pages and 10,000 jobs per source, one worker, and at
least 1 second between requests within a company. Eightfold uses at least
2.5 seconds and Microsoft 3 seconds. Microsoft forces one worker for the run.
Use `--max-pages` and `--max-jobs` to change caps. Direct requests have a
25-second timeout. A 429 pauses the source immediately; 503 retries are bounded
and honor Retry-After. Cooldowns persist in `.local/source_access.sqlite`.
Sitemap
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
`paused` means the request policy stopped the source; any rows collected before
the pause are retained. Do not treat a paused or partial run as a complete board.
Exit code 0 means all selected direct sources completed or were unchanged and
all enabled search queries completed their fixed batches. Code 2 means at least
one source/query failed, was skipped or remains incomplete. Successful searches
are `query_limited`, never complete inventories.
Each invocation replaces the files in its output directory; use a different
`--output` to retain previous runs.

## JSearch

See [JSearch daily discovery](jsearch.md) for the executable 52-query functional
plan, 310-page allocation, 316-credit daily ceiling and 9,500-credit monthly
target. JSearch remains opt-in. The shared store deduplicates stable IDs across
queries and preserves full descriptions, salary and useful unknown fields.

Supply JSEARCH_API_KEY through the environment or ignored `.env.local`. Missing
credentials are reported without dispatching a request. `--jsearch-plan` previews
the entire configured plan without credentials or network requests. Company
fallbacks use reviewed exact employer aliases; functional discovery does not
blacklist employers. No actual API request is required by the offline tests.

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

The old hard-source recovery script and its attribution notes were deleted after
the company list was finalized. They are not part of the active collection
pipeline.

## Repository layout

`src/jobdisco/` is the installable package and `tests/` contains its tests.
`data/config/` contains source configuration and schema, `data/raw/` contains
source validation reports, and `data/db/` contains the SQLite catalog. Generated
run directories live under `runs/`; the large run files are ignored by Git.
Historical company-selection and endpoint experiments were removed from the
active tree after the company list was finalized.

## Direct API integration check - 2026-09-16

Historical early diagnostic results; superseded by the later successful
integration summarized in [Collection Rules](collection-rules.md).

The direct OpenWeb Ninja key is saved only in ignored local configuration.
Twelve offline tests pass, including persistent cap and concurrent reservation
tests. Three real attempts were reserved: the collector rejected an unexpected
response, a diagnostic request timed out, and the last request returned HTTP 504.
No successful job extraction from the direct API has been verified yet. Do not
interpret these failures as zero available jobs. The local ledger records all
three attempts conservatively; provider billing may count differently.

## Search-v2 response correction - 2026-09-16

Historical early query test. Later employer-name queries and the direct-source
recoveries are recorded in [Collection Rules](collection-rules.md).

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
