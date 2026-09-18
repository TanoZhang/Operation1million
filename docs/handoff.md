# Handoff — 2026-09-17

State after the first full baseline, three collection passes, and the first
hosted attempts. Read `README.md` for how the pieces fit; this is what is true
right now, including what is broken.

## Where the data lives

Two private repositories:

- `TanoZhang/Operation1million` — code, config, workflow. No collected data.
- `TanoZhang/Operation1million-data` — one gzipped NDJSON file per collection
  day, a manifest carrying its SHA-256, `source_state.json`, and under
  `operational/` the two ledgers that must outlive a runner: the JSearch credit
  count and the per-source cooldowns.

The job database is derived and gitignored. From nothing:

```
JOBDISCO_STORE=<data repo> job-store --bootstrap
```

Roughly two seconds for 38,000 postings, from `schema.sql`, the migrations and
the log. Verified to reproduce every row field for field.

## Current numbers

| | |
| --- | --- |
| Open postings | 38,193 (38,302 including closed) |
| With an absolute `posted_at` | 28,074 (74%) |
| Scoring 25 or above | 5,383 |
| Direct sources | 35 companies, 33 collecting completely |
| JSearch credits spent this billing period | 314 of 9,500 |

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

**Wide search queries are split across calls.** Every call of 10 pages or fewer
succeeded across 52 live queries, while 4 of the 7 asking for 11 to 18 returned
HTTP 504 and took 61 credits with them. `max_pages_per_call` is configurable; 1
means one call per page.

**Politeness.** Per-source intervals, `Crawl-delay` honoured (only AMD declares
one, at 5s), durable pauses on 429/403 that survive a restart, and the ledgers
now checkpointed to the data repository so a hosted runner cannot reset them.
Every path collected is permitted: the Eightfold sites explicitly
`Allow: /api/pcsx`, and Micron whitelists `IndeedJobBot` beside it.

## What is broken or unfinished

**The local store has diverged from the data repository.** Local holds 66,780 log
lines; the data repository has 37,622, from the initial backfill. The full run's
699 new postings and the Apple repair are on this machine only. A hosted run
bootstraps from the data repository, so until this is pushed it will rebuild
from a stale baseline and rediscover known postings as new. Push before the next
non-dry hosted run.

**Microsoft no longer makes the whole collection single-threaded.** Its source
has a dedicated lock and keeps its 3-second request interval, while the other
companies continue through the configured worker pool. A hosted dry run reduced
the collection step from 45 minutes 48 seconds to 13 minutes 3 seconds. Microsoft
received an immediate 429 in the faster run and stopped under the cooldown rule,
so a future normal pass still needs to confirm full Microsoft pagination.

**The JSearch plan leaves no headroom.** 310 pages against a 316-page daily
budget, and the daily budget is a fixed slice of the month. Any manual testing
earlier in the same UTC day eats the scheduled run: on 2026-09-17, 29 credits of
testing left 287 for a 310-page plan, and 11 queries were skipped after
`QuotaExhausted`. Two fixes, neither applied: size the plan near 280, and make
the daily allowance the month's remainder divided by the days left rather than a
fixed slice.

**Two companies have no direct route.** Rambus answers 405 on every path under
`careers-rambus.icims.com`, including `/sitemap.xml`; `ventanamicro.com` does not
accept connections. Whether to reach them through paid search is undecided.

**Amazon is capped by its own search** at 10,000 results, so its board is
collected but not proven complete. **Rivos** is an aggregator profile, not the
company's board: 15 postings, completeness unverifiable.

**The manifest carries per-item detail.** 29 KB, of which `jsearch_queries` is
18 KB and `jsearch_confidence` 4 KB — 883 bare numbers with no keys, unusable
away from the postings they came from. A distribution summary would say the same
in five fields. Per-query yield is worth keeping; it is how the plan gets tuned.

## The hosted workflow

Committed, scheduled daily at 06:17 America/Los_Angeles, and it has run.

- The first scheduled attempt (2026-09-17 17:39Z) failed in 48 seconds at
  `Check out the data repository`: **`Bad credentials`**. The
  `DATA_REPO_TOKEN` secret existed but its value was not a usable token.
- A dispatch at 23:07Z failed the same way.
- A dispatch at 23:09Z passed that step and ran on, so the secret has since been
  replaced with a working token.

A secret's value cannot be read back — `gh secret` has no `get` — so the only
proof a token works is a run that gets past checkout.

Scheduled runs enable the fixed paid JSearch plan. Manual dispatches default to
no paid calls and expose an explicit `enable_jsearch` toggle. A bounded live test
used one credit for `Design Verification Engineer` over one week and returned 10
raw jobs: 9 accepted, 1 rejected, and no malformed records or failures. A dry run
checkpoints the operational ledgers but not collected postings.

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
- `posted_at` covers 74%. Workday states only relative text, kept verbatim in
  `posted_relative` and never converted, so anything reporting "new today" must
  key off `first_seen`.
- JSearch overlaps direct boards by roughly half, and the URLs never match, so
  the two records never merge. Whether a LinkedIn link to a Qualcomm role is
  worth storing beside the ATS record is undecided.
