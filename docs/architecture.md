# How this system is put together

A map of what each file is responsible for, the order things happen in, and the
bugs that have been found and fixed. It exists so a reader -- or another agent
-- can find the part that owns a behaviour without reading everything, and can
tell a decision that was made deliberately from one that nobody has looked at.

**Keep it current.** A change that moves a responsibility between files, adds a
module, or changes the order of the pipeline belongs here in the same commit.
So does a fixed bug: the log at the bottom is the record of what has already
been wrong, and it is the cheapest way to avoid re-introducing it or re-arguing
a decision that has already been settled by evidence.

## The shape of it

One machine does everything. A VPS runs the collection pass on a timer, owns
the job index and the decision log, and serves the review UI on loopback. A
workstation reaches that UI through an SSH tunnel and pulls a disaster-recovery
copy; it never writes. GitHub holds the code and a rolling fourteen days of
collection history, not the working state.

    scheduled pass (04:38 America/Los_Angeles)
      |
      +-- 35 company boards, direct          --> normalize --> store
      +-- 35 JSearch queries, paid           --> normalize --> score/filter --> seen --> store
                                                                          |
    review UI (127.0.0.1:8765)  <-- rank <-- open postings <---------------+
      |
      +-- Apply / Skip --> append-only ledger (never SQLite)

## Modules

### Collection

| File | Owns |
| --- | --- |
| `collector.py` | The pass itself: argument parsing, the 35 direct sources, per-source normalization, and the order everything runs in. `main()` is the whole pass. Commits each source as it finishes rather than holding a run in memory. |
| `collection_policy.py` | How fast a company's board may be asked, and durable cooldowns when one refuses. Reads `Crawl-delay` from robots.txt and never goes below it. |
| `validate_sources.py` | The source catalog: which company has which board, at which endpoint, and whether a configured route still answers. |
| `query_catalog.py` | The search-query catalog and its checks. |
| `job_text.py` | Display titles: strips publisher "Posted ..." suffixes and trailing locations so they do not become part of an identity. |

### Paid discovery

| File | Owns |
| --- | --- |
| `jsearch.py` | The JSearch plan, transport, and everything that decides whether a posting is kept. `load_plan` validates the config; `collect` pages the plan breadth-first within a tier; `rejection_reason` is the filter; `relevance` is the score. `TIER_ORDER` decides which queries get the budget first. |
| `experience.py` | Deterministic required-experience parsing shared by discovery and Review, including explicit entry-level overrides and required versus preferred clauses. |
| `jsearch_access.py` | Money. Reserves a page credit **before** the request leaves, so a crash or a timeout still shows it as spent. Owns the daily allowance, the 30-day cycle, the provider cooldown, and the resumable sweep cursor. `budget_day()` decides which day's allowance is being spent. |
| `ledger_guard.py` | Refuses to start a pass whose local credit ledger is behind the published one, which would spend credits twice. |
| `data/config/jsearch_queries.toml` | The plan and the filter rules, with the reasoning for each in comments. Editing a term list here changes what is collected on the next pass. |

### Storage

| File | Owns |
| --- | --- |
| `store.py` | The derived SQLite index and the append-only gzip log it can be rebuilt from. Job identity, closure inference, the seen table, manifests and their digests, `bootstrap`/`rebuild`, and `rescore`. |
| `prune.py` | The fourteen-day window on `runs/` and `manifests/`. Never touches `operational/`. |
| `workflow_state.py` | Reconciling operational state after a pass that could not publish. |
| `paths.py` | Where everything lives. |
| `data/config/schema.sql`, `migrations/` | The catalog schema and its migrations. `seen_jobs` and `job_identities` are the two that carry identity. |

### Review

| File | Owns |
| --- | --- |
| `applications.py` | The queue and the decision ledger. `decision_key` is what a decision may cover and nothing wider. `queue()` replays the ledger, re-applies the filter to stored rows, and ranks. Decisions are appended to NDJSON under a file lock and fsynced; **no application state lives in SQLite**, so rebuilding the index cannot erase a decision. |
| `ranking.py` | What to read first. Bands, the early-career signal, and the sort key. Ranking only -- it cannot drop a posting. |
| `review.py` | The loopback HTTP server. Binds `127.0.0.1` only, checks the Host header so an SSH tunnel still works, and requires a token for writes. `slim()` projects the queue down to what the page renders. |
| `review_static/` | The page. `app.js` reads only the fields `review.GROUP_FIELDS` and `JOB_FIELDS` send; a contract test enforces that. |

### Operations

| File | Owns |
| --- | --- |
| `deploy/vps/daily-pass.sh` | The production pass: lock, preflight, tests, index, collect, publish, prune, push, heartbeat. |
| `deploy/vps/install.sh` | Deploying a code change to the VPS. **A push to GitHub does not deploy.** |
| `deploy/vps/jobdisco-collect.timer` | The schedule. Its `OnCalendar` and `budget_day_resets_at` in the TOML must say the same thing. |
| `deploy/vps/backup-applications.sh` | Pushes the decision ledger every fifteen minutes, because it is the one file nothing regenerates. |
| `deploy/local/backup-from-vps.sh` | One-way VPS to workstation copy, including a consistent SQLite snapshot. |
| `heartbeat.py`, `deploy/vps/heartbeat.sh` | Healthchecks reporting, so a dead timer is noticed. |

## Rules that are easy to break

- **Hard rejects run before everything and no score overturns them.** A word
  with an ordinary reading in this trade does not belong in that list. See
  `docs/collection-rules.md`.
- **`first_seen` is not a publication date.** The first pass gave forty
  thousand postings the same one.
- **The queue re-applies the filter at read time**, so a row stored under older
  rules is still judged by current ones -- except by its stored `relevance`,
  which only a pass or `job-store --rescore` refreshes.
- **A credit is reserved before the request, not after.** Anything that sends a
  request outside `RequestGuard` is unbilled and invisible.
- **SQLite is derived and disposable; the ledger and `operational/` are not.**
- **Seen records include rejected jobs.** Scoring and filtering compute the
  recorded decision; each page's seen rows are committed before its accepted-job
  checkpoint. The collector exports their recovery snapshot on success and
  handled failure; Actions publishes it alongside verified collection state.
- **A cached score belongs to unchanged content.** A title or retained payload
  change recalculates it without trusting an old score embedded in raw. A rules
  change alone still requires `job-store --rescore` for unchanged postings.

## Bugs found and fixed

Newest first. Each entry is what was wrong, how it showed, and what settled it,
so that a later reader can tell whether a decision was reasoned or measured.

### Iterative offline audit, 2026-09-20 (branch, not deployed)

Reproduced against `e09d9ed` plus the work-claim commit `56cf495`, with remote
main at `9843350`. These fixes are on `codex/debug-untimestamped-credit`.
Remote comparison found ETag and sitemap fixes already present in unmerged
`c035df4` on `codex/deep-debug`; those are independent reproductions, not new
discoveries. Its six tests were imported and run against this implementation.
Five passed; the listed-but-not-fetched reopening test failed. Its reopening
implementation was then imported too; all 68 store tests pass. The remote
branch remains intact. The initial branch inventory had been read without
inspecting that commit's contents, which this final comparison corrects.

- **Incomplete inventories published usable validators.** `record_source`
  saved a new ETag after a partial response. With an older successful pass on
  record, `plan` then selected that ETag, permitting a 304 to hide missing jobs.
  Validators now advance only on a complete inventory; an incomplete last
  status forces a full retry, including for state written by older versions.
  Reproducer: `StoreTests.test_partial_pass_does_not_make_its_etag_a_completed_inventory`.
- **Sitemap skip conditions lost both updates and missing jobs.** Filtering by
  watermark first removed never-stored old URLs; filtering known URLs next
  removed changed existing jobs. Skip now requires an open local row and a
  valid, timezone-aware lastmod no later than the watermark. Closed rows are
  not eligible for skipping when relisted. Ambiguous dates are fetched.
  Reproducer: `EarlyStopTests.test_sitemap_refetches_changed_known_and_missing_old_postings`.
- **A reused URL retained an obsolete requisition alias and description.**
  A then B at one URL, followed by A at a new URL, overwrote B with A. A distinct
  explicit same-provider identity now resets the current URL row and its
  aliases; cross-provider enrichment remains supported. Old versions stay in
  the append-only log. Rebuild applies replacement semantics and authoritative
  identity snapshots too. Reproducer:
  `LogRoundTripTests.test_reused_url_does_not_redirect_old_requisition_over_its_replacement`.
- **Relisted rows needed a storage-level reopening path too.** The imported
  `c035df4` implementation reopens listed rows within the same source and logs
  full job events for replay, while leaving other providers and obsolete
  identity aliases closed. Fetching closed rows in the collector alone had
  not protected this storage seam. Reproducer:
  `StoreTests.test_relisted_skipped_job_reopens_and_survives_fresh_replay`.
- **Review split a single requisition across recent and backlog.** A new
  location and a five-day-old location appeared in separate tabs with the same
  decision ID. POST selected the recent group and saved an incomplete snapshot.
  Groups shared across the boundary now live entirely in recent. Reproducer:
  `ApplicationsTests.test_one_requisition_spanning_recent_and_backlog_has_one_complete_group`.
- **Review lost descriptions after storage removed duplicate HTML.** The HTTP
  endpoint did not read `descriptionPlain`, even though storage deliberately
  keeps it when it removes equivalent HTML. It now reads both retained plain
  text and the alternate HTML field. Reproducer:
  `HttpTests.test_description_survives_store_html_deduplication`.
- **Invalid workstation backups still rotated good copies away.** Validation
  set an error flag but only exited after replacing current and previous.
  Equal log/manifest counts also passed with mismatched dates. Validation now
  checks both filename sets and exits before rotation on failure. Synthetic
  SSH tar streams in `tests/test_backup.py` cover missing ledgers, bad SQLite,
  mismatched manifests, and successful rotation. No remote machine is accessed.

Validation infrastructure corrections: Python 3.10 tests now use the existing
tomli fallback and recognize guarded tomllib imports as standard-library use.
Windows heartbeat shell tests select Git Bash explicitly instead of the WSL
launcher and quote paths. The previous session's unqualified full-suite pass
claim was not supported by a captured exit status; its initial rerun here had
327 tests, five failures, one import error and eight skips before these fixes.

The subsequent audit also found real robots.txt requests hidden inside
supposedly offline Collector fixtures. Mocking only the job session did not
cover SourcePolicy construction. Those fixtures now stub robots_delay; final
verification blocks unmocked requests.Session HTTP calls, while Review tests
continue to exercise their local HTTP server. This corrects any assumption
that the earlier unguarded suite made no external requests.

Two equivalent loop optimizations preserve output and ordering: maintain the
presentation URL set as rows are appended instead of rebuilding it per result,
and sort listed-only inventory once rather than once per 400-row batch. A
synthetic comparison executed the old and new presentation loops on 4,000
initial and 6,000 incoming rows: both emitted identical 6,500-row lists,
measured at 2.072227s and 0.001406s. Sorting 20,000 URLs into 50 identical
batches took 0.258879s versus 0.005812s. These are local loop measurements, not
production run-time claims. No search, filtering, ranking or output fields
were changed by these optimizations.

### A test held a SQLite handle open and only Windows noticed

`with sqlite3.connect(path) as db` commits the transaction; it does not close
the connection. A backup fixture written that way left the handle open, and
`TemporaryDirectory` cleanup then failed on Windows with `WinError 32` --
four errors in a suite that passed cleanly on Linux, where an open file can
still be unlinked.

The suite is run on both, so "passes on my machine" is not a property worth
having here. The fixture uses `closing(...)` now, which is what the rest of
the repository already does for exactly this reason.

### Untimestamped credits were counted in two consecutive budget windows

`RequestGuard.daily_used` counts timestamped `credit_events` by their exact
instant, then adds residual `credit_usage` credits that no event explains. The
residual query compared the row's `day` label to UTC dates overlapped by the
04:38 Pacific budget window. A row labelled 2026-09-20 was counted by both the
2026-09-19 and 2026-09-20 budget windows.

The regression test creates that one four-credit residual and evaluates both
windows. Before the fix their usage was `[4, 4]`; now it is `[0, 4]`. Residuals
are attributed once to the budget window with the same date label, while
timestamped events keep their exact instant-range accounting. This is a policy,
not recovery of a missing timestamp: old rows used UTC dates, so the actual
Pacific window cannot be known. Monthly charges remain intact. The old
conservative overlap rule could under-collect; the new rule removes its double
count but cannot guarantee exact historical daily attribution.

### Seen recovery depended on the VPS wrapper

The collector committed seen rows to disposable SQLite but did not export the
recovery snapshot. Only the VPS publication script did; manual collection and
the Actions fallback could finish with new rejections absent from durable state.
Actions also did not stage the snapshot. This does not establish a failure of
the VPS path, which already exported it.

An offline two-pass test against `a960195` returned one identical rejected job
per pass, replacing the database with a fresh replay in between. Both reports
said one new and zero existing. Exporting at successful and handled-failure
sealing changes the second report to zero new and one existing. A separate
checkpoint-failure test recovers the rejected row on a fresh database. Actions
now stages the snapshot only with verified, non-dry-run collection state.

### Changed postings retained their first score forever

`record_source` calculated relevance only for new URLs and preferred the old
column on every update. A changed title or description therefore retained a
score for content no longer present. Review's evidence gate uses that column.

Offline fixtures on `a960195` showed a retitled Senior RTL role stuck at zero
and an RF description changed to antenna work still scored 99. Both failed
before the fix. Changed content now recalculates without trusting embedded raw
scores; unchanged rows keep the cache. The updated score is logged, and a fresh
database replay reproduces the corrected zero in the RF fixture.

### Old decision snapshots retained only their first requisition identity

Migration from company/title grouping re-keyed only the first job in each
snapshot. The rest depended on URL matching: changing a later job's URL made
an applied requisition pending again, and reopening the historical group could
reopen several different requisitions together.

An offline legacy snapshot containing two requisitions reproduced both failures
on `a960195`. Replay now splits snapshots by each scoped requisition identity.
Tests verify both identities remain decided after URL changes, reopening one
leaves the other skipped, and the original ledger bytes remain untouched.

### A reused URL inherited another requisition's decision

Review checked URL decisions even when the ledger already supplied a scoped
requisition identity. Skipping one requisition and replacing its database row
with a new requisition at the same URL hid the new opening.

The synthetic replacement fixture reproduced the missing pending row on
`a960195`. Snapshot decisions now apply only through their identity; URL-only
legacy events keep their fallback, with append order resolving later decisions.
Tests cover replacement visibility, legacy reopen, and independent history.

### A whole query tier was searching for a phrase employers do not write

The plan asked seven queries of the form `<role> Early Career`. Nobody had ever
sent one: the tier had never been reached under the old ordering, and after the
ordering was fixed it was due to run for the first time on 2026-09-20.

Measured first, one page and one credit each, `--no-store`, window `week`:

| Query | Returned | Survived the filter |
| --- | ---: | ---: |
| `Hardware Early Career` | 6 | 1 |
| `ASIC Early Career` | 3 | 0 |
| `FPGA Early Career` | 3 | 0 |
| `Design Verification Early Career` | 2 | 0 |
| `Silicon Early Career` | 1 | 0 |
| `RTL Early Career` | 0 | 0 |
| `Digital Design Early Career` | 0 | 0 |

Seven credits a pass for one usable posting. The same roles asked as `Entry
Level` return a near-full page each: `Design Verification Entry Level` 10 and
four survivors, `FPGA Entry Level` 9 and two, `ASIC Entry Level` 8 and three.
For comparison `ASIC Intern` returns 10 of 10 and `ASIC New Grad` 10 of 7, so
the provider matches these phrases against posting text and "Early Career" is
simply not what employers write.

The tier now asks `Entry Level`. `RTL` is dropped from it, being the one role
that returns nothing under either phrasing -- it is already asked as an intern
and as a new grad -- and its eleven page credits went to the three queries that
measured best, keeping the plan's caps at exactly the daily budget.

What this does not establish: the window tested was `week` and the pass runs
`3days`, so these counts are an upper bound on what a pass will see. It is a
lower bound on nothing -- a query returning zero over a week returns zero over
three days.

### A literal date in a test was a fuse that stopped the whole pass

A log day seals as soon as the clock passes it, so a hardcoded date in a test
that writes a log row runs green until that day ends and fails forever after.
Because `daily-pass.sh` runs the suite before collecting, and runs it under
`set -e`, a failing test does not just fail: it stops the pass from collecting
anything at all.

It has now fired twice. First on 2026-09-19 at 00:42 UTC, thirty-eight tests at
once, which was fixed by deriving `STAMP` from the current day. The fix missed
two literals inside a single test that needed successive days, and those fired
on 2026-09-20 at 00:00 UTC for the same reason -- found by chance, several
hours before the pass would have died on it.

Days after today are never sealed whatever day today is, so the successive days
are relative too, and they live beside `STAMP` rather than inline. Any date
used as a log stamp belongs there. Dates passed to a stubbed clock or to an
explicit `today=` are a different thing and are fine as literals: those are
deterministic replays, and most of the dates in the suite are exactly that.

### Experienced-only postings were reaching the queue

Nothing read the years of experience a posting asked for, so roles requiring
five years sat beside internships. `experience.py` parses required experience
deterministically -- no model, no API -- and hard-passes anything above two
years. It reads only required experience, ignores preferred and nice-to-have,
takes the minimum of a range, follows the Master's path where a posting states
a degree equivalency, and refuses to be fooled by "5-year roadmap". An explicit
intern or new-grad title overrides it entirely; `early career`, `entry level`,
`junior` and `associate` deliberately do not.

### The query plan asked for roles, not for the early career

Separate from the tier ordering below: the plan itself was 52 narrow role
queries of which only 11 named an internship. It is now 36 across four tiers
-- intern, new_grad, early_career, A -- with 27 naming early career explicitly
and broader A-tier phrases covering more ground per credit. The query strings
themselves are still unverified; see the handoff.

### The daily budget reset at a time nothing observed

The page-credit day was a UTC calendar day, while the pass is scheduled at
04:38 `America/Los_Angeles`. UTC turns over at 17:00 Pacific, eleven hours
before the pass the daily allowance exists to fund, so anything run on a
Pacific evening spent the next morning's credits.

Measured on the real ledger for 2026-09-19: a catch-up run at 18:05 and 20:10
Pacific took 296 of 320 credits, and the scheduled pass eleven hours later got
24 and reached fifteen of its fifty-two queries.

The budget day now runs from one scheduled pass to the next, in the schedule's
own timezone (`budget_timezone`, `budget_day_resets_at`). The 30-day **cycle**
was deliberately left on UTC dates: it stands in for the provider's monthly
quota, and 04:38 Pacific is eleven hours clear of a UTC date change in both
offsets, which is what stops a pass landing on a different cycle day twice a
year. `tzdata` became a dependency because Windows ships no zone database, and
a missing zone raises rather than falling back to UTC -- UTC being precisely
the wrong answer here.

### The internship queries had never been sent

`TIER_ORDER` asked tier A before `intern`. A is fifteen queries twelve pages
deep, so it asks for 180 of a 320-credit day before the internships are reached
at all, and any day opening with less than that in hand reached none of them.

Measured across every pass the plan had run: 144 page credits spent, all 144
inside tier A, and the eleven internship queries never once sent -- while the
review queue ranks internships first. Internships are now asked first.

### Hard rejects were killing postings for one word

`device` took `Device Validation`, `Embedded Device`, `PCIe Device` and `Device
Driver` to reach eighteen fab postings. `software` took 231 titles including
`Embedded Software Engineer`. `RF` took `RFIC Digital Verification Engineer`
alongside the analogue-only roles it was aimed at.

The first two are now explicit phrases rather than bare words. RF became
`evidence_title_patterns`: the title is admitted only if the description
carries the trade's vocabulary, and a posting with no readable description
carries none. Of 56 RF rows the index held, three qualify.

### The queue was ordered by relevance alone

Relevance says nothing about whether a posting is open to someone who has not
graduated, and rates a staff opening exactly as it rates one a new graduate can
take. Seven of the first hundred positions were internships, out of 363 held.
`ranking.py` now bands first and dates second; relevance breaks ties inside a
band.

### A decision could answer for a requisition it had never seen

`decision_key` was company plus title, so one Skip could bury every posting
sharing them -- measured at 48 Apple requisitions behind one. It is now the
provider's requisition id, scoped by company for direct sources because two
boards can both number a requisition `12345`.

### Seen rows were lost when a query did not finish

`jsearch.collect` recorded a query's seen rows only after it finished paging,
so anything that ended the run in between discarded the record of every page
already bought. Recorded per page now, before the checkpoint that can fail.

### A board's size was reported as what the pass fetched

`store.record_source` counted `seen` as postings fetched, but a pass skips
fetching what it already holds. A board listing nine and read for one recorded
one, in the delta and in `source_state.job_count`. It counts what the board
listed.
