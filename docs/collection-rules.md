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
The validator honors the same cooldowns. Legacy bulk endpoint guessing via
`job-probe-failed-sources` is disabled; its old definitions are historical only.

Defaults are 400 pages, 10,000 records per source, 25 seconds per direct request,
and 90 seconds for JSearch. Caps are limits, not completeness claims. A 400-page
cap accommodates the reported PCSX totals but future boards may exceed it.

## JSearch usage

- Default `--jsearch-budget` is 0. Direct discovery should normally use no paid
  search now that Rambus and Ventana Micro have been removed.
- Use JSearch only when expressly enabled for a discovery task. Start a transport
  test with a budget of 1; document the result before increasing the scope.
- Do not trigger fallback for a page/job cap, some malformed records, a valid
  empty board, or a source paused by the request policy.
- Company-specific discovery starts with the plain employer name and always
  filters returned `employer_name` against reviewed aliases. Search text alone
  does not constrain the employer. Keep `num_pages=1` for bounded tests.
- Keep the 90-second timeout separate from direct-source timeouts. Count every
  dispatch, including timeouts; a timeout does not invalidate unrelated attempts.
- Preserve `.local/jsearch_usage.sqlite`, the 10,000-attempt local cap, and the
  provider's account cap. Never reset a ledger automatically or silently expand
  a testing budget. The previous handoff reported more than 30 test requests;
  repeating that investigation is unnecessary.

## Daily incremental discovery: implementation design

**Status: design only. The current collector still outputs a run snapshot and
does not yet persist jobs across runs or implement a `--new-only` option.**

Keep one job database, `data/db/job_discovery.sqlite`, with additional tables;
there is no need for separate downloaded/filtered/applied databases. Operational
cooldown and quota ledgers remain separate local files.

| Planned table | Purpose and important fields |
| --- | --- |
| jobs | Stable identity, company_key, title, location, URL, first_seen_at, last_seen_at, posted_at, content_hash, raw |
| job_sources | Mapping of source instance + source_job_id (or canonical URL) to jobs; preserve location variants when they are separate application records |
| collection_runs | Run ID, start/end time, status, new/changed/seen counts, request count |
| source_sync_state | Source ID, endpoint/scope fingerprint, last attempt, last successful complete scan, baseline status, optional verified cursor/date watermark |
| run_jobs | Which jobs were first seen, changed, or observed in a run; allows exports to be rebuilt after a crash |

Keep later filter results and application status separate from source records.
Changing a filter or keyword must not require re-downloading jobs already stored.

Implementation sequence:

1. Import retained `jobs.jsonl` for active companies as an initial seen set.
   Label it a historical baseline, not a current inventory. Run each source
   once to establish a current baseline; do not call initial baseline rows
   newly posted jobs. Microsoft and the newly recovered boards may lack a
   usable historical baseline and must be initialized separately.
2. Give each posting a stable identity using company + source job ID, scoped
   to the source when IDs are not globally unique. Use a canonical URL when
   the provider has no reliable ID. Preserve meaningful URL parameters and
   distinguish location variants; do not deduplicate on title alone.
3. On later runs, insert unseen jobs and retain `first_seen_at`. Refresh
   `last_seen_at` for known jobs; record material changes separately. A repost
   with the same ID is an update/reappearance, not automatically a new job.
4. Export `new_jobs.jsonl` and `new_jobs.csv` from the run's durable new-job
   records. Keep changed jobs separate. Never infer a posting date from
   `first_seen_at`; it means first observed by this system.
5. Commit accepted records and the corresponding run/source progress together.
   A failed or capped run may keep collected records but must not advance the
   last-successful-scan watermark or mark unseen jobs closed. Resume after the
   cooldown with deduplication; do not blindly reuse offset cursors on changing
   boards. Regenerate exports from run_jobs if file output fails after commit.

### When this saves network requests

Saving only new jobs always saves repeated processing and output. It does not
guarantee that providers will send only new jobs.

| Provider behavior | Daily strategy |
| --- | --- |
| Verified server-side updated-since/date filter or durable delta cursor | Query from the last successful watermark with at least 72 hours of overlap, then deduplicate |
| Verified newest-first ordering with reliable timestamps and pagination | Read through the overlap window, including all tied timestamps; use a periodic full scan to recover delayed/reordered listings |
| JSON list without a verified incremental filter/order | Fetch list pages at the required pace, compare IDs locally, and process/export only new or changed jobs |
| Board returned in one response, such as the current Greenhouse/Ashby integrations | Fetch once and diff locally; use conditional HTTP requests only if the endpoint supports them |
| Sitemap with trustworthy lastmod | Diff URLs/lastmod and fetch details for new or changed URLs; periodically refresh known URLs with missing/unreliable lastmod |

For AMD the current query uses `sortBy=relevance`. The current PCSX queries do
not establish a newest-first contract. Do not assume that these four boards can
stop after the first old ID, or that only the first page contains new jobs.
Their optimized date/order strategy needs a small, deliberate verification
before implementation. Do not guess filter parameters or silently claim request
savings. A 72-hour overlap and weekly reconciliation are proposed starting
points, not guarantees against arbitrarily delayed indexing.

Run once per day after the baseline, with jitter only to avoid simultaneous
scheduled starts, never to evade detection. An optional weekly full scan can
reconcile missed changes and closures. Mark a missing posting as suspected
closed only after successful full inventory checks; partial/paused runs cannot
establish closure. No schedule or startup item is installed by this change.

## Maintenance and verification

- Keep schema.sql, SQLite, active source lists, and fallback aliases consistent.
  A fresh schema must preserve AMD's `amd_careers` provider and the PCSX routes.
- Current validation CSV rows describe the endpoint and time originally tested;
  older iCIMS/app-shell results must not be relabeled as new API successes.
- Prefer offline response fixtures for parser, pagination, pause, and dedupe
  tests. New integration checks should target one company and one page first.
- Keep malformed records isolated, parse nested location objects recursively,
  and retain the original posting timestamp where the provider supplies one.
- Do not alter historical counts or describe the 2026-09-15 run as today's board.
