> **Startup rule:** Read the newest handoff first. Older handoffs are historical
> evidence, not current instructions or an active backlog.

# Iterative audit and equivalent optimization - 2026-09-20 UTC

Code/test commit: `4c9e3448992026f42760fbbf6f78687c14fe2bae` on
`codex/debug-untimestamped-credit`; ready for review, not merged or deployed.
Last fetched main: `9843350bf98f415a09f42a82c0415a7b5e8fb4d0`.

Four new behavior fixes cover URL-reuse identity/content corruption, one
requisition split across recent/backlog, missing plain-text Review descriptions,
and invalid backup rotation. Three earlier fixes on `codex/deep-debug` commit
`c035df4` cover incomplete validators, sitemap selection, and listed-only
reopening. Its six tests were compared against this branch; the reopening
implementation was imported after its test failed here. Both branches remain.
See `docs/architecture.md` for exact reproducers and before/after evidence.

Two loop optimizations preserve rows and ordering: maintain presentation URLs
incrementally and sort listed-only inventory once. Synthetic equivalence checks
compared 6,500 output rows and 50 inventory batches; results were identical.
No search/filter/ranking policy or output field was changed by optimization.

Validation: 400 tests in 88.503 seconds, exit 0, eight skips, with
`requests.sessions.Session.request` patched to reject external HTTP. Skips are
one real-database audit, one POSIX signal test, and six flock-dependent backup
tests. Git Bash backup/heartbeat tests ran. `git diff --check` and backup shell
syntax checks passed. Tests use this worktree's `src` via PYTHONPATH. Earlier
unguarded suites had hidden robots.txt calls and an unsupported full-pass claim;
this result supersedes those claims. No paid collection or deployment was run.

Residual quota attribution is a same-date-label policy, not recovered event
timing: legacy aggregate dates were UTC. Monthly charges remain unchanged.
Production counters, actual provider coverage and deployed behavior remain
unverified. Full sitemap recovery may fetch more details within existing caps.

The concurrent `codex/lean-cleanup` branch at `ff16baf` was inspected before
publication: it contains a dead-code audit claim only, no overlapping source
change. Leave that work separate; this branch removes repeated loop work.

# Debug follow-up - 2026-09-19 Pacific (2026-09-20 UTC)

Codex's offline audit is on `codex/deep-debug`, based on main `a960195` plus
the collaboration protocol branch. These changes are pending review and are
not deployed. The sections below remain historical snapshots.

Four reproduced defects and their evidence are recorded at the top of the
architecture bug log: reused Review URLs, multi-requisition legacy decisions,
stale relevance after content changes, and missing seen snapshot export outside
the VPS wrapper. New tests exercise ledger replay and fresh-database recovery.
No paid requests or production changes were made.

Validation: `python -m unittest discover -s tests -q` ran 384 tests, with 14
environment-dependent skips and no failures. Tests imported this worktree's
`src`, not the original checkout's editable install. Windows lacks some POSIX
test prerequisites and this worktree has no production database. The new
Actions publication shell tests did execute using Git Bash, covering verified,
dry-run and failed-verification branches. `git diff --check` also passed.

Corrections to the earlier uncertainty list:

- The daily per-query caps total 105 / 90 / 70 / 55 across intern, new_grad,
  early_career and A. Their sum is 320, enforced by plan validation. A tier
  cannot consume the full daily allocation under this fixed plan; a partially
  spent budget, deadline or provider stop can still prevent later tiers.
- Seen deduplication has offline repeated-pass and restore coverage. The new
  collector-level test replaces the database between passes and requires the
  second manifest to report `seen_new=0`, `seen_existing=1`. This does not prove
  production counters; it also does not avoid provider requests or re-scoring.
- New query strings still require a real run. An empty tier alone cannot name
  the cause: distinguish zero pages attempted, successful empty responses,
  filtering, provider errors and budget/deadline stops in the manifest.
- Production backlog behavior and a full-budget pass on the deployed code
  remain unverified by this offline audit.

# Handoff - 2026-09-20

## The first pass that worked end to end

2026-09-20 11:38 UTC, on `9843350`, 42 minutes, exit 0.

| Tier | Pages | Returned | Accepted |
| --- | ---: | ---: | ---: |
| intern | 50 | 453 | 287 |
| new_grad | 50 | 476 | 201 |
| early_career | 6 | 40 | 17 |
| A | 47 | 460 | 139 |

**The internship queries ran for the first time.** Before the tier ordering was
fixed they had never been sent at all -- 144 credits had been spent across the
plan's whole history and every one of them inside tier A.

153 of the 320 page credits were spent and every tier was reached, so nothing
starved anything: the budget was not the binding constraint, the providers
running out of new postings was. `early_career` spent one page per query, which
is what a query that exhausts on its first page looks like. Its 17 accepted
postings are against the 1 that the whole `Early Career` phrasing produced in
the keyword test, so that change earned its credits.

Also: 1,429 postings seen, 644 accepted, 483 hard-rejected, 302 rejected on
their content, 103 newly persisted, 39,894 open. One source failed to read.

**`seen_existing` is still 0.** 1,429 rows, all recorded as new. The query plan
changed completely between this pass and the last one, and `date_posted` is
`3days`, so no overlap is plausible -- but it is not proven, and this is now
the third pass in a row with a zero here. The next pass runs the same plan
against a seen table holding 1,429 of its own rows. If it is still zero then,
the counter or the upsert is wrong, not the data.

Deployed at `e35e78c` as of 2026-09-20 18:05 UTC, which is ahead of the code
this pass ran: it adds the sitemap, ETag and URL-reuse fixes described in the
architecture bug log. Those change what the next pass collects, so its numbers
are not comparable with the table above.

# Handoff - 2026-09-19

Read this section first; everything below it is the state as of 2026-09-18 and
is kept for the reasoning, not for the numbers.

Start with [docs/architecture.md](architecture.md) for what owns what and the
log of bugs already settled, and [docs/agent-protocol.md](agent-protocol.md)
for the work register, because two agents work this repository and neither can
see the other.

## What is deployed right now

| | |
| --- | --- |
| VPS code | `5937594`, installed 2026-09-19 23:05 UTC |
| Review service | restarted at install, serving the new ranking |
| Job index | 41,073 postings rescored under the current rules, 0 unscored |
| Next scheduled pass | 2026-09-20 11:38 UTC |

The live review queue, measured after deployment:

| Band | Groups |
| --- | ---: |
| Intern / New Grad (core and adjacent) | 389 |
| Core VLSI | 2,313 |
| Related Hardware | 2,337 |
| Other | 14,232 |
| **Total pending** | **19,271** |

The first page of 75 is entirely early-career, newest first. One posting
carries the `Adjacent` mark, meaning it was admitted on its description rather
than its title.

## What changed on 2026-09-19

Both agents worked this day and reached several of the same places
independently; `git log` between `0ec4732` and `5937594` is the full record,
and the merge commit `35fcffa` explains which half of each overlap was taken
and why. In summary:

- **The internship queries had never once been sent.** Across every pass the
  plan had run, 144 page credits were spent and all 144 went to tier A. The
  query plan is now 36 queries across four tiers -- intern, new_grad,
  early_career, A -- with 27 of them naming early career explicitly, and the
  early-career tiers are asked first.
- **The daily budget reset at a time nothing observed.** It was a UTC calendar
  day against a pass scheduled at 04:38 Pacific, so anything run on a Pacific
  evening spent the next morning's credits. Measured: a catch-up run took 296
  of 320 and the scheduled pass got 24. The budget day now runs from one pass
  to the next, configured beside the budget and pinned to the timer by a test.
- **Hard rejects were killing postings for one word.** `device`, `software` and
  `RF` are now explicit phrases or evidence-gated rather than bare words.
- **The queue was ordered by relevance alone**, which cannot see an internship
  or a posting's date. `ranking.py` now bands first and dates second.
- **A deterministic required-experience gate** rejects experienced-only
  postings without an LLM, with intern and new-grad titles overriding it.
- **Decisions were scoped too widely**, and seen rows were lost when a query
  did not finish. Both fixed; see the log in `architecture.md`.

## What is not yet known

These are the things a next session should look at, in order.

1. **The new query strings have never been run.** `ASIC New Grad`, `RTL Early
   Career` and the fifteen like them are a reasonable guess about what
   employers write, and nothing more. The 2026-09-20 pass is the first test of
   them. If a tier comes back empty, that is why. `docs/collection-rules.md`
   describes how to test one keyword for a single credit.
2. **Seen deduplication is unproven.** `seen_existing` has been 0 on every pass
   so far, meaning no pass has yet re-seen a posting. Tomorrow's pass is the
   first that could.
3. **The backlog view is untested in production**, because every open posting
   still has a `first_seen` inside the three-day window; the index was
   bootstrapped recently.
4. **No per-tier depth cap remains.** `tier_pages` was removed in favour of
   per-query caps. In the current `date_posted = "3days"` regime queries
   exhaust after a page or two, so nothing binds -- but if a query ever pages
   deeply, one tier can take the day, which is the failure the tier caps used
   to prevent.
5. **A pass has never run with a full budget and the current code.** Every pass
   so far was budget-starved by manual runs earlier the same UTC day.

## Handing off

Before starting: `git fetch origin`, then `git log HEAD..origin/main` **and**
`git ls-remote --heads origin`. Work is routinely parked on a branch and is
invisible to a check of `main` alone. Claim your area in the register in
`docs/agent-protocol.md` before writing code.

Never commit in `/opt/jobdisco/code`. It is the production checkout the
scheduled pass runs from, and committing there once left two commits on a
single disk and broke `install.sh`.

To deploy: push to `main`, then

    ssh <vps> sudo -n bash /opt/jobdisco/code/deploy/vps/install.sh

It prints the installed commit; if that is not what you just pushed, the update
did not happen whatever else it said. A push alone deploys nothing.

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

## The VPS, deployed 2026-09-18

The daily pass now runs on the OVH VPS-1 (2 vCPU, 4 GB, 40 GB, Ubuntu 24.04,
Oregon). `docs/vps-deployment.md` is the operating manual: install, update,
triage, and the three places the pass deliberately differs from the workflow.

**Measured on the box.** 181 offline tests pass. The database builds from the
committed log in 35.6 seconds at a 769 MB peak -- above the 639 MB recorded on
a runner, because the log has grown, and still a fifth of the 3.7 GB available.
That build now happens once: the pass rebuilds only when the file is absent,
because `job-store --bootstrap` always rebuilds from scratch and replaces the
database, so calling it daily would reimpose the cost the move removes.

**The schedule moved into the timer.** `OnCalendar=*-*-* 04:38:00
America/Los_Angeles`, `Persistent=true`, and systemd resolves the zone itself:
the first firing was confirmed as 11:38 UTC. The workflow keeps
`workflow_dispatch` and lost its `schedule`, because two schedules at the same
minute would spend one credit budget twice and race each other's push. The
daylight-saving test followed the schedule into the timer and now also asserts
the workflow schedules nothing.

**Nothing else would notice it dying**, so the pass reports to a Healthchecks.io
check and its silence is the alarm. `/start` when it begins, the bare URL only
after collection, store verification and the push have all succeeded, `/fail`
otherwise -- and then the original exit code is restored, because a monitor that
swallowed the failure would be worse than none. A ping that cannot be delivered
is a warning and never fails the pass. The URL is configuration, not source: it
lives in `/etc/jobdisco/env` at mode 640, and a test walks every tracked file to
keep it out of the tree. A shell without that variable stays silent, which is
what makes a manual diagnostic safe. Set the check to period 1 day, grace 3
hours; a shorter grace pages you about a pass that is running normally.

**Secrets are three lines** in `/etc/jobdisco/env`, root-owned and group-readable
by the service account. The GitHub token is handed to git by a credential helper
that reads it from the environment, so it never reaches `.git/config` or a remote
URL. One honest compromise: a fine-grained PAT applies one permission set to
every repository it selects, so the token carries write on the code repository
although the pass only ever reads it.

**Local log retention was decided and then not implemented**, on purpose.
Deleting old files inside the data checkout stages a deletion that the next
commit publishes, removing them from the authoritative copy -- the opposite of
the intent. The safe equivalents are machinery for a problem this disk does not
have: at 20 MB a day, tree and history together fill 36 GB in about two and a
half years, and the ~5 GB GitHub guidance forces a repository reset long before
that. What is implemented is a 5 GiB floor that refuses to start, because a full
disk fails exactly where the store is least able to survive it.

**Still to watch: the fixed address.** Runners rotated through Azure ranges; this
machine does not. Collection is polite and a predictable polite caller is usually
treated better than an unpredictable one, but this is the one thing that could
behave differently after the move. Watch per-source outcomes for a fortnight.

## Production audit, 2026-09-18

Everything below was measured against the live store or exercised as a test,
not read off the code.

**Holds.** The budget bounds concurrent passes rather than their timing: six
guards racing forty credits spend forty, because the reservation is taken
inside the transaction that reads the balance. Every dispatch is charged once
whatever it returns -- 200, 504, 500, a timeout, a connection reset -- so the
count never falls below the provider's. The cycle is thirty days from a date
and drifts off the calendar correctly, with the sweep on its last three days.
04:38 Pacific is eleven hours from a UTC date change in both offsets, so
daylight saving cannot move a pass onto another cycle day. Hard exclusions are
checked before the keep list, so nothing skips them: a director of silicon
verification is excluded, while Senior, Staff, Firmware, Embedded, Product,
Test and Applications engineers are all kept when the posting talks about the
trade. The ledgers the workflow copies are in `delete` journal mode, so one
file carries every committed write. A run's log is 93 to 129 KB; paging prints
nothing per page.

**Fixed here.** An empty page no longer ends a query for the cycle, nor steps
the cursor past itself -- a provider's bad minute looked exactly like the end
of the results and skipped the page for good. A cursor is now kept under the
search it belongs to, so changing the window or the country cannot hand a later
run a page number from a search that no longer exists. A description is
measured by its prose rather than its markup. Renesas's requisition is read out
of the URL that hides it, so its 899 postings -- the only ones with no identity
of their own -- survive being retitled or relocated.

## Verified state, 2026-09-18

The last check before the first scheduled pass under this code. Everything
below was measured, not assumed.

| | |
| --- | --- |
| Offline tests | 181 pass (132 at the time of the audit below) |
| Store rebuilds from the data repository | 9.9s, three manifests verify |
| Open / total / unscored | 38,893 / 39,694 / 0 |
| Scoring 25 or above | 4,845 |
| Postings with no identity row | 899, all Renesas, which publishes no id |
| Identities claimed by two open URLs | 0 |
| Daily plan cap | 456 pages, deliberately above the 320-credit ceiling |
| First full pass | 128 pages bought, 1,165 postings, 9 of 15 tier A queries still capped |
| A page costs | 11.7 seconds, which is what bounds a pass, not the credits |
| Request rate | 4 a second against the plan's limit of 5 |
| Monthly guard | stops at 9,600 of the 10,000 the plan includes |
| Actions minutes | 269 of 2,000 spent, nearly all of it on debugging |

**The full shape has now run once**, on 2026-09-18: 725 new postings, 243
closed, 30,767 seen, 1,165 of them from paid search, exit 0 and committed. It
found the thing the offline tests could not: a page takes 11.7 seconds, so the
runtime limit bought 128 pages of the 307 the credits allowed, tier A took all
of them, and tiers B and C were reached with nothing left. The depths and the
limit were resized afterwards and **that configuration has not run yet**.

The first scheduled pass, earlier the same day, failed before collecting
anything: a test imported PyYAML, which is installed on the machine it was
written on and declared nowhere, so the runner could not load the suite. Tests
run before collection so a broken build cannot reach the boards, and that is
what happened, to a build broken by a test. Every import under `src` and
`tests` is now checked against the declared dependencies.

## Current numbers

| | |
| --- | --- |
| Open postings | 38,869 (39,635 including closed) |
| Open with an absolute `posted_at` | 28,724 (74%) |
| Open scoring 25 or above | 4,817 |
| Direct sources | 35 companies, 33 collecting completely |
| JSearch credits spent this billing period | 218 of 9,600 (resets 2026-10-16) |

## What works

**A review queue decides once per position, not once per URL.** `job-review`
serves a local page over the loopback interface listing open postings first seen
in the last 72 hours, grouped by company and normalized title, ordered by stored
score. Apple advertises one role at eleven listings in five locations, and
answering the same question eleven times is how a queue stops being used, so a
decision covers the group and any location that appears under it later.

Decisions live in `operational/applications.ndjson`, beside the credit count and
the cooldowns and for the same reason: the store answers what is open, and
`job-store --bootstrap` rebuilds it from the log, but a decision has no source to
be rebuilt from. The ledger is append-only and replayed on every read, an undo is
another event rather than a rewrite, writes take an OS file lock and fsync before
reporting success, and a malformed line stops both replay and writing while
naming its line number. The server never collects, submits, buys a credit or
commits anything. `docs/application-review.md` is the detail.

Measured against the live store: 28,916 positions pending, `/api/queue` answers
in 0.42s with 19.4 MB. The count is that high only because most of the board was
first seen when the store was bootstrapped; in steady state a day adds a few
hundred.

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
`Commit durable state` runs on cancellation, so the unmanifested file could
reach the data repository and the next run's `--bootstrap --verify` would
refuse it. That step now verifies the store before adding the collected
postings and commits only the operational ledgers when it does not hold, so a
killed pass is lost rather than published. The window itself is still there;
what changed is that it no longer leaves the repository unable to rebuild. A
day already in that state is repaired by resealing its manifest, as on
2026-09-18.

**A run that crosses UTC midnight seals itself out.** The scheduled pass
cannot reach it: 04:38 Pacific is 11:38 UTC in daylight time and 12:38 in
standard time, eleven hours from a UTC date change either way, and a pass runs
at most ninety minutes. A late manual run still can, and on 2026-09-18 one was
started at 22:31 UTC and stopped again once it was noticed -- a full pass from
there would have lost the ability to write at 00:00, partway through, and
reported it as corruption. `sealed()` is literally `stamp[:10] < now()[:10]`.
Anyone running a pass by hand should check the UTC clock first; this is the
sharpest edge left in the system. `run_stamp` is fixed when
the pass begins, and `sealed()` asks whether that day is over, so from midnight
every `append_log` raises `Daily log is sealed` and the seal on the way out is
refused for the same reason. The pass is lost entirely, and the message reads
as corruption rather than a clock. A pass takes up to ninety minutes with a
sweep, and the one scheduled run so far started four hours and twenty-two
minutes late, so the window is narrow but not closed. Either the day's stamp
should roll forward when it is overtaken, or a day should seal only once no run
still holds it.

**The data repository grows about 20 MB a day and git does not forget.**
History already holds 168 MB against a 123 MB working tree, because appending
to a gzip file writes a whole new object each time. Deleting old logs in a new
commit does not shrink a clone; only rewriting history would, and that is
destructive. At this rate GitHub's 5 GB guidance arrives in roughly eight
months.

The owner has decided this is not worth a snapshot design: the point of the
thing is to apply to what is open today, postings close within weeks anyway,
and a posting lost from deep history is a posting that would have closed. So
the intended answer is a rolling window -- keep the last N days of log, let a
rebuild reach back only that far, and accept that `first_seen` for anything
older would be wrong if the store ever had to be rebuilt from nothing. On a
machine that keeps its disk this only matters after a total loss, because the
live SQLite is the working state and the log is a backup rather than the daily
mechanism.

Two things do not fall under that. `operational/applications.ndjson` is a
record of decisions, not of the world: nothing regenerates what has been
applied for, and it must be kept whatever else is pruned. And the pruning has
to be a fresh repository or a history rewrite to actually reclaim anything,
which is a deliberate act, not a `git rm`.

**The daily schedule has never completed.** Every successful pass so far has
been a manual dispatch. The only scheduled run, on 2026-09-17, failed on
`Bad credentials` before the token was replaced.

## Current limitations

**Every tier is reachable, because depth is set per tier.** Priority runs
A, intern, B, C, and one depth for all of them made that an exclusion rather
than a preference: fifteen tier A queries at forty pages can ask for six
hundred against a budget of three hundred and twenty, so measured on the real
plan, tier A alone spent all 320 and the other 37 queries -- every internship
among them -- were never reached. The depths now step down the priority order:
15, 8, 6, 5 for a day and 100, 60, 40, 30 for a sweep. Tier A was raised back
from ten after measurement, because nine of its fifteen queries reached the cap,
so ten was not the end of those searches.

That makes a day's ceiling 456 pages against a 320-credit budget, and the two
are not meant to match. Depth is discovered rather than declared, so a declared
sum has nothing left to guarantee: `validate_budget` now only asks that every
query can reach a first page -- 52 queries against 320 credits -- and 456 is a
cap no plan is expected to reach. The budget is what binds, and tier A is paged
to exhaustion first, so a day whose wide queries keep returning full pages can
still leave the tail unreached. That is the same failure the per-tier depths
were introduced to fix, now bounded rather than eliminated.


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

**Every posting in a rebuild carries its score.** A runner replays the log and
never rescores, and recomputing costs 129 seconds for 39,635 postings. The
score travels two ways: written beside a posting as it is logged, and, for the
postings logged before that, as a compact `score` event carrying only a URL and
a number. A fresh rebuild reports `unscored: 0`, which `job-store` prints so
that an empty ranking would never be a mystery.

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

No longer scheduled: the daily pass runs on the VPS and this workflow keeps
only `workflow_dispatch`, as the clean-room way to run a pass while that
machine is being changed or is suspect. A runner starts from the committed log
and needs nothing the VPS holds. Hosted collection
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

**A ledger that is present and non-empty may still have forgotten everything.**
Reading the credit balance through `RequestGuard` on the new machine created a
schema-only ledger at the local path, which then shadowed the published one
holding 133 credit events, a baseline and five backfill cursors. `[ -s ]`
accepted it: it was several kilobytes of valid SQLite. The invariant is
directional and had never been written down -- the local ledger may be ahead of
the published copy, because a pass whose push failed leaves exactly that, but it
may never be behind, since behind means charges the provider has already counted
have been lost. `jobdisco.ledger_guard` now compares the two before collecting
and refuses, naming the repair. The diagnostic that caused it was stopped in its
test phase, before a credit was spent.

**Tests run before collection, and they caught a config change.** Raising
`daily_budget` to 600 on the box to let a full-plan test run failed two tests
that assert it is 320, and the pass aborted before touching a board. The number
is an invariant, not a default: 320 across 30 days is exactly the 9,600 monthly
target.

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
