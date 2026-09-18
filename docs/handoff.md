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

## Next: move the daily pass to a VPS

An OVH VPS-1 has been bought for this — 2 vCPU, 4 GB, about $4.50 a month.
Nothing has been deployed to it yet. This is the next piece of work, and it is
worth doing before anything else because three of the constraints the code
currently works around stop existing on a machine that keeps its disk.

**Why, in measured terms.** A rebuild from the committed log allocates 639 MB
at its peak and takes 21.5 seconds, and it happens on every hosted run because
an Actions runner starts with an empty disk. The collector only bootstraps when
the database is absent (`collector.py`, `if not args.db.exists()`), so on a
machine that persists, that cost is paid once and never again. The 2,000 free
Actions minutes a month stop being an accounting problem — a full-depth pass is
about 110 minutes a day, which is 3,300 a month and would cost roughly $7.80 in
overage. The 120-minute job timeout stops bounding how deep a search may go.

**What the VPS needs to hold.** Only the working set: the derived SQLite at
about 198 MB, the last few days of logs, and a checkout of the data repository.
Older logs can be pruned locally because GitHub holds the authoritative copy,
so the VPS stays under a gigabyte rather than following the ~20 MB a day the
history grows by.

**What to build.** A systemd service and timer at 04:38 local, an
`EnvironmentFile` with mode 600 for `JSEARCH_API_KEY` and the data repository
token, a one-shot install script, and `docs/vps-deployment.md` covering install,
update and triage. Four things need deciding as part of it rather than after:

- *Nothing will tell you it died.* Actions emails on a failed run; a systemd
  timer that stops, a disk that fills or a process the kernel kills are all
  silent. A `OnFailure=` unit, or a heartbeat the run writes and something
  checks, is not optional here.
- *Secrets become files.* They are encrypted secrets on Actions and plain text
  on a box. Mode 600, outside the repository, never in shell history.
- *Disk.* Under a gigabyte if old logs are pruned; several gigabytes a year if
  they are not. Decide the prune and put it in the timer, because a full disk
  fails exactly where the store is least able to survive it.
- *A fixed IP against 35 boards.* Actions runners rotate through Azure ranges;
  a VPS does not. Collection is polite -- per-source intervals, `Crawl-delay`
  honoured, cooldowns persisted -- and a predictable polite caller is usually
  treated better than an unpredictable one, but this is the one thing that
  could behave differently and it is worth watching for a fortnight.

**Keep the workflow.** Drop its `schedule` and leave `workflow_dispatch`, so
there is a clean-room way to run a pass when the VPS is being changed or is
suspect. It costs nothing once it no longer fires on its own.

**Do not follow the cloud product tree.** Container Apps, Lambda, scheduled VM
start/stop and burstable CPU credits were all considered and are all more
moving parts than this workload has problems. Azure's student tier was the
closest call and fails on one number: B1s, B2pts v2 and B2ats v2 all have 1 GiB
of memory against a 639 MB peak that grows with the log, and the failure mode
is an OOM kill partway through a pass.

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
| Offline tests | 132 pass |
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
at most ninety minutes. A late manual run still can. `run_stamp` is fixed when
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
months. The answer when it does is a state snapshot -- every open posting with
its true `first_seen`, so a rebuild can start there instead of at the
beginning -- after which old logs really can be dropped. The compact `score`
event is the same shape and a working precedent. Not urgent, and better sized
against a real growth curve than guessed at now.

**The daily schedule has never completed.** Every successful pass so far has
been a manual dispatch. The only scheduled run, on 2026-09-17, failed on
`Bad credentials` before the token was replaced.

## Current limitations

**Every tier is reachable, because depth is set per tier.** Priority runs
A, intern, B, C, and one depth for all of them made that an exclusion rather
than a preference: fifteen tier A queries at forty pages can ask for six
hundred against a budget of three hundred and twenty, so measured on the real
plan, tier A alone spent all 320 and the other 37 queries -- every internship
among them -- were never reached. The depths now step down the priority order
and the whole plan fits even if every page comes back full: 10, 6, 4, 3 for a
day (307 of 320) and 100, 60, 40, 30 for a sweep (3,070 of about 3,127).


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
