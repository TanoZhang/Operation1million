# Handoff - 2026-09-18

State after the hosted baseline and incremental collection were made durable.
Read `README.md` for how the pieces fit; this file records the current operating
facts and remaining limitations.

## Where the data lives

Two private repositories:

- `TanoZhang/Operation1million` — code, config, workflow. No collected data.
- `TanoZhang/Operation1million-data` - one or more gzipped NDJSON shards per
  collection day, a manifest carrying each SHA-256, `source_state.json`, and under
  `operational/` the two ledgers that must outlive a runner: the JSearch credit
  count and the per-source cooldowns.

The job database is derived and gitignored. From nothing:

```
JOBDISCO_STORE=<data repo> job-store --bootstrap
```

The rebuild uses `schema.sql`, migrations and the append-only log. It has been
verified from a fresh checkout, including scores, identities and closures.

## Current numbers

| | |
| --- | --- |
| Open postings | 38,869 (39,635 including closed) |
| Open with an absolute `posted_at` | 28,724 (74%) |
| Open scoring 25 or above | 4,817 |
| Direct sources | 35 companies, 33 collecting completely |
| JSearch credits spent this billing period | 218 of 9,600 (resets 2026-10-16) |

## What works

**Four boards were recovered from paid search.** AMD and the three Eightfold
tenants were on JSearch because the catalog held the wrong endpoints, not
because the boards were unreadable: AMD serves `careers.amd.com/api/jobs`, and
the Eightfold sites serve `/api/pcsx/search` even where `apply-v2` returns 403.

**Incremental strategies, chosen per source from stored state.** A first pass is
always a full download; later passes take the cheapest safe option. On the last
run four Greenhouse boards answered 304 and cost one request each; Eightfold
dropped from 295 requests to 1, Renesas from 909 to 1.

**Relevance scoring on every posting, 0-100.** Trade-exclusive terms outweigh
ordinary English, a title match counts double, nothing is deducted for absence,
and six distinct strong terms score 100 outright. Exclusions — defence
programmes, management titles — are a separate question asked first and score 0.
`job-store --ranked N --min-score M` reads the stored score; `--rescore` after a
term-list edit.

**A search query's depth is discovered, not declared.** Every call asks for
`num_pages=1`, and the next page follows only when the last came back full, so a
query stops where the provider runs out. The provider publishes no result total,
so every declared allocation was a guess that was either waste or truncation:
across 52 live queries not one filled the pages it reserved, and the plan used
43.5% of the capacity it paid for. A page is now the unit of both billing and
loss — the four calls of 11 to 18 pages that returned HTTP 504 were charged 61
credits for nothing, and the same failure now costs one.

`max_pages_per_query` (40) is a runaway guard, not an allocation: it stops a
provider whose pages never run short, or that repeats a page instead of
advancing. Tier A is paged to exhaustion before tier B begins, and within a tier
each query takes one page per round — spending depth first would leave the tail
of the plan unreached every day, always the same queries.

**Politeness.** Per-source intervals, `Crawl-delay` honoured (only AMD declares
one, at 5s), durable pauses on 429/403 that survive a restart, and the ledgers
now checkpointed to the data repository so a hosted runner cannot reset them.
Every path collected is permitted: the Eightfold sites explicitly
`Allow: /api/pcsx`, and Micron whitelists `IndeedJobBot` beside it.

## Known and unfixed

Written down because each of these is invisible until it bites, and none of
them is scheduled.

**A hard kill between sharding and sealing leaves a log with no manifest.**
`shard_daily_log` moves the day's file aside, writes the shard's manifest and
deletes the day's; the active file that replaces it has no manifest until the
run seals it on the way out. Every ordinary exit seals, including a failure,
but a process killed outright -- a runner timeout, a cancelled job -- does not.
`Commit durable state` runs on cancellation, so the unmanifested file can reach
the data repository, and the next run's `--bootstrap --verify` refuses it. The
repair is to reseal that day's manifest by hand, as on 2026-09-18.

**The 38,849 postings logged before the score travelled with them cannot be
given one.** Sealed days are not rewritten. A fresh rebuild ranks them as
irrelevant until `job-store --rescore` runs, which costs 129 seconds.
`job-store` prints the count so an empty ranking is not a mystery.

**The daily schedule has never completed.** Every successful pass so far has
been a manual dispatch. The only scheduled run, on 2026-09-17, failed on
`Bad credentials` before the token was replaced.

**A backfill sweep can spend its whole budget on tier A.** Fifteen tier A
queries at 200 pages each is 3,000, and a sweep's share of the cycle is about
3,127, so tiers B and C may never start. The cursor makes it worse across days:
tier A resumes deeper while the rest stay at page one.

## Current limitations

**Microsoft no longer makes the whole collection single-threaded.** Its source
has a dedicated lock and keeps its 3-second request interval, while the other
companies continue through the configured worker pool. A later hosted pass
collected all 2,382 Microsoft postings while unrelated sources ran concurrently.

**JSearch uses an overlapping 3-day window.** A `today` window loses a day
permanently whenever a run fails, which has already happened; three days of
overlap mean the next run recovers it, and duplicates cost nothing because the
identity is the provider's `job_id`. The daily ceiling is 320 credits. Note that
320 across 30 days is exactly the 9,600 monthly target, and the billing anchor
is day 16 because that is when the provider resets.

**Credit accounting is per page and durable.** The credit is committed to the
ledger before the request leaves, so a timeout or a crash still shows it as
spent; the outcome is written afterwards and never refunds it. `credit_events`
therefore separates credits that returned jobs from credits a 504 consumed, and
`RequestGuard.balance()` answers used/remaining from durable state at any moment
rather than at the end of a run.

The provider states what a call cost, not what is left:
`X-RapidAPI-Billing: Queries=1; Requests=1`. That is recorded per page, so
`provider_drift` is nonzero the moment a charge differs from the credit
reserved -- the only way that would ever be visible. Measured live on
2026-09-18: one page asked, one charged.

`credit_baseline` holds credits the provider counted that this ledger never saw.
It currently carries 218 for the period beginning 2026-10-16's predecessor: the
ledger was rebuilt and had drifted to 4 against the provider's 218.

**Legacy scores are repaired through compact events.** New job events carry
their score directly. Historical jobs are covered by append-only score events,
so a clean runner restores all 39,635 scores without rewriting large source
records or recomputing them every day.

**Amazon is capped by its own search** at 10,000 results, so its board is
collected but not proven complete. **Rivos** is an aggregator profile, not the
company's board: 15 postings, completeness unverifiable.

**The current UTC day may have multiple files.** A day rolls to a numbered shard
before the active gzip file would exceed 90 MB. Every shard has its own checksum
manifest and replays before the active same-day file.

## The hosted workflow

Committed and scheduled daily at 06:17 America/Los_Angeles. Hosted collection
has checked out both private repositories, rebuilt from scratch, collected,
sealed the log and pushed the resulting data commit. The current credentials
have therefore been exercised successfully; secret values remain unreadable.

Scheduled runs enable the fixed paid JSearch plan. Manual dispatches default to
no paid calls and expose an explicit `enable_jsearch` toggle. A bounded live test
used one credit for `Design Verification Engineer` over one week and returned 10
raw jobs: 9 accepted, 1 rejected, and no malformed records or failures. A dry run
checkpoints the operational ledgers but not collected postings.
Collector exit code 2 is reported as a warning rather than making every daily
run red; unexpected failures still fail the workflow.
Dry runs now print the new, closed, and seen counts they discard and explicitly
restore/remove durable collection paths before committing only safety ledgers.
Paid paging stops cleanly before the job timeout: 25 minutes for daily discovery
and 50 minutes for the end-of-cycle sweep, leaving time to seal and push state.

## Lessons worth not relearning

**A board row's identity is its requisition, not the words in its URL.** Apple
advertises one role at many stores, so forty postings share `.../us-manager` and
differ only in the requisition before it. Taking the trailing path segment made
them one identity, a pass that fetched 4,513 postings recorded 2,358, and the
2,155 that appeared unseen were retired — 48% of Apple's board in one pass,
while every other company moved by about 1%. Nothing errored; the pass reported
`complete`. The reason it was caught at all was that 48% against 1% is not
churn.

**Only a pass that enumerated a whole board may retire a posting.** An
early-stop pass reads the newest slice and stops; on a quiet day it returns
nothing and would otherwise close everything. A blank first page is also what a
board looks like mid-deploy, so it counts only when the board states a count of
zero.

**A board's own zero count is not sufficient protection.** A complete pass that
would close more than 25% of the existing company/provider inventory is now
downgraded to partial. The store keeps all candidate closures open, preserves
the prior success watermark, and reports the blocked count and ratio.

**Paid search was querying the wrong thing.** `"AMD electrical engineer"` returns
electrical-engineer roles at other employers, all correctly rejected, which read
as a broken filter. JSearch treats the employer as a plain search term;
the employer name alone returns 10 of 10.

**Failures are charged, so the widest asks are the most expensive to lose.**
Four tier-A queries timed out and spent a fifth of the day's budget returning
nothing.

**Score on write, not on read.** Scoring 37,584 postings against 134 patterns
per read did not return within two minutes.

## Open questions

- One role at many locations: the store keeps all of them, which is right — San
  Jose is not Austin. The ranked view should group them
  (`Design Verification Engineer (13 locations)`). Not implemented.
- `posted_at` covers 74% of open jobs. Workday states only relative text, kept verbatim in
  `posted_relative` and never converted, so anything reporting "new today" must
  key off `first_seen`.
- JSearch overlaps direct boards by roughly half, and the URLs never match, so
  the two records never merge. Whether a LinkedIn link to a Qualcomm role is
  worth storing beside the ATS record is undecided.
