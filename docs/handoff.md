# Handoff — 2026-09-17

State of the collector after the first full baseline and two incremental passes.
Read `README.md` first for how the pieces fit; this is what is true right now.

## Where the data lives

Two repositories, both private:

- `TanoZhang/Operation1million` — code, config, workflow. No collected data.
- `TanoZhang/Operation1million-data` — one gzipped NDJSON file per collection
  day, a manifest with a SHA-256 for each, and `source_state.json`.

The SQLite database is derived and gitignored. From an empty machine:

```
JOBDISCO_STORE=<data repo> job-store --bootstrap
```

That rebuilds 38,000-odd postings in about two seconds from `schema.sql`, the
migrations and the log. Verified to reproduce every row field for field.

## What works

**35 direct company boards, 33 collecting completely.** Four providers were
rebuilt during this work: AMD and Microsoft/Micron/Qualcomm were on paid search
because the endpoints in the catalog were the wrong ones, not because the boards
were unreadable. AMD serves `careers.amd.com/api/jobs`; the Eightfold tenants
serve `/api/pcsx/search` even though `apply-v2` returns 403 for them.

**Incremental strategies, chosen per source from stored state.** A first pass is
always a full download. Later passes use the cheapest safe option: `conditional`
where the board returns an ETag (four Greenhouse boards answered 304 on the last
run, one request each), `since` where the listing is strictly newest-first
(Eightfold: 295 requests became 1), `lastmod` where a sitemap carries it
(Renesas: 909 became 1), and `full` everywhere else.

**Relevance scoring, 0-100, on every posting.** Trade-exclusive terms weigh more
than ordinary English, a title match counts double, and nothing is deducted for
absence. Six distinct strong terms score 100 outright. 37,584 open postings
reduce to 4,836 at or above the keep bar. Exclusions — defence programmes,
management titles — are a separate question asked first, and score 0.

**Politeness.** Per-source intervals, `Crawl-delay` honoured from robots.txt
(only AMD declares one, at 5s), durable pauses on 429/403 that survive a restart.
Every path collected is permitted: the three Eightfold sites explicitly
`Allow: /api/pcsx`, and Micron whitelists `IndeedJobBot` alongside it.

## What is not done

**Collection is single-threaded whenever Microsoft is in the source list.**
`collector.py` drops `--workers` to 1 for the whole run because Microsoft
throttles by IP. That is the main cost of the 57-minute run: 34 other companies
wait while one slow board is fetched. The fix is a lock on the Microsoft source
alone, leaving the rest concurrent — an estimated 13 minutes instead of 57.

**The JSearch plan has no headroom.** 310 pages planned against a 316-page daily
budget. Any manual testing earlier in the same UTC day, or a few failures, pushes
the tail of the plan past the budget: the last run completed 36 of 52 queries and
skipped 11 after `QuotaExhausted`. Failed requests are charged, by design, since
the provider counts them. Sizing the plan near 280 would absorb that.

**Two companies have no direct route.** Rambus answers 405 on every path under
`careers-rambus.icims.com`, including `/sitemap.xml`; `ventanamicro.com` does not
accept connections at all. Whether to reach them through paid search is an open
decision — coverage of both is thin.

**Amazon is capped by its own search.** It returns its 10,000-result ceiling, so
its board is collected but not proven complete. Partitioning the search would
settle it.

**Rivos is a third-party listing.** Its source is an aggregator profile page, not
the company's board; 15 postings, completeness unverifiable.

**The workflow has never run.** `.github/workflows/collect.yml` is committed and
`DATA_REPO_TOKEN` is set, but no scheduled or manual run has happened yet. A
`workflow_dispatch` with `dry_run=true` would prove the runner path before the
first real one.

## Bugs found and fixed, worth not reintroducing

**A board row's identity is its requisition, not its URL slug.** Apple
advertises one role at many stores, so forty postings share `.../us-manager` and
differ only in the requisition before it. Taking the trailing path segment made
them one identity; the identity table remapped them onto a single URL, a pass
that fetched 4,513 postings recorded 2,358, and the 2,155 that appeared unseen
were retired — 48% of Apple's board in one pass, while every other company moved
by about 1%.

**Only a pass that enumerated a whole board may retire a posting.** An
early-stop pass reads the newest slice and stops; on a quiet day it returns
nothing and would otherwise have closed everything. A blank first page is also
what a board looks like mid-deploy, so it is trusted only when the board states a
count of zero.

**Paid search was querying the wrong thing.** `"AMD electrical engineer"` returns
electrical-engineer roles at RTX and Bechtel, all correctly rejected by the
employer filter, which read as a broken filter. JSearch treats the employer as a
plain search term; querying the employer name alone returns 10/10.

**Scores are stored, not recomputed.** Scoring 37,584 postings against 134
patterns per read did not return within two minutes.

## Open questions for whoever picks this up

- Same role at many locations: the store keeps all of them, which is right —
  a posting in San Jose is not one in Austin. The ranked view should group them
  (`Design Verification Engineer (13 locations)`) rather than the store merging
  them. Not implemented.
- `posted_at` exists on 73% of postings. Workday states only relative text
  (`Posted 7 Days Ago`), kept verbatim in `posted_relative` and never converted.
  Anything reporting "new today" must key off `first_seen`.
- JSearch overlaps direct boards by roughly half. Whether a LinkedIn link to a
  Qualcomm job is worth storing beside the ATS record is undecided; the URLs
  never match, so they do not merge.
