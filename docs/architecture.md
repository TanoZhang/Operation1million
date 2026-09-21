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
- **An HTTP validator is a completion checkpoint.** Partial or failed inventory
  must not install a new ETag or Last-Modified value; retry it with a full pass.
- **Sitemap age is not identity.** Skip details only for known, unchanged rows
  on a lastmod board. Compare timestamp instants, not their ISO strings. A listed
  closed row reopens within its source, unless it is an alias of another identity.

## Protected decisions

These choices can look wrong when read in isolation. Change one only with a
reproducer and update its evidence below.

- **Daily quota uses Pacific time; the billing period uses UTC. Do not unify
  them.** The daily allowance starts with the scheduled 04:38 Pacific pass. The
  30-day provider cycle must not move with daylight saving time.
- **`first_seen` is observation time, not publication time.** It is a fallback
  only; the first collection assigned the same value to about forty thousand
  postings.
- **Ranking chooses the band before relevance.** Relevance cannot identify an
  internship or publication date.
- **Hard rejects precede every keep and score and cannot be overturned.** Only
  titles that settle the decision belong there; ambiguous trade words do not.
- **Evidence titles require evidence in supplied prose.** Missing prose does not
  satisfy an evidence gate.
- **Legacy credit residuals belong to their stored budget-day label.** Matching
  them to overlapping UTC dates counts one residual in two Pacific windows.
- **Log-stamp dates are computed, never literal.** A past literal date seals and
  can stop the production pass through its preflight test suite.
- **Scores cache unchanged content, not unchanged rules.** Content changes
  recalculate; rule changes require `job-store --rescore`.

## Bugs found and fixed

Newest first. Each entry is what was wrong, how it showed, and what settled it,
so that a later reader can tell whether a decision was reasoned or measured.

### A bug check of the review path and the store CLI, 2026-09-21 UTC (not deployed)

Three defects, each reproduced before it was fixed and each with a test that is
red against the code as it stood. One is the outstanding instance of B27 from
Codex's sixth round; the other two are new. The three browser-only fixes from
the round below were also run in a JavaScript runtime for the first time.

- **A replacement requisition at a decided address stayed hidden.** A decision
  is allowed to follow its posting from paid discovery to the company's own
  board, because the store merges the two discoveries into one row. It was
  following the address instead: the only evidence required was a different
  provider with an agreeing company and title, and a board that later
  advertised a genuinely different opening at the same URL publishes the same
  company and, often enough, the same title. The new requisition then inherited
  an application nobody had made to it and never appeared for review. The store
  already records which case it is -- a provider upgrade leaves the decided
  requisition among the address's aliases in `job_identities`, a replacement
  releases them -- so the queue now asks. Reproduced through `record_source` on
  a real schema: after the upgrade the address held
  `(jsearch, '', JS-A)` and `(ashby, sample, ASH-B)` and the decision stood;
  after the replacement it held only `(ashby, sample, ASH-C)` and the pending
  queue was empty where it should have held one posting. Where the decision
  names no requisition, or the index records no alias for the address, there is
  nothing to check and the older reading stands, so an index built before
  identities were tracked behaves as before. This is the instance of B27 that
  the company-and-title restriction did not settle. Reproducer:
  `ApplicationsTests.test_a_replacement_at_a_decided_address_is_not_hidden_by_a_provider_move`.
- **The review page could not see a pass that was still running.** The queue is
  cached against when its inputs last changed, and the index is read in WAL
  mode, where a commit lands in the `-wal` sidecar: the database file's
  timestamp and length do not move until a checkpoint, which a pass reaches
  only when it closes its connection at the end. Everything a running pass
  found or closed was therefore invisible to the page, and Refresh answered out
  of the cache with nothing to say it was stale. Measured here: a committed
  posting was visible to any reader of the index and absent from `/api/queue`
  until the pass exited; and when another reader held the sidecar open, the
  close-time checkpoint did not run either, so the staleness outlived the pass.
  The sidecar is now part of the key. A reader that recreates a checkpointed
  sidecar moves its timestamp, which costs one extra build and never a missed
  one. Reproducer:
  `HttpTests.test_a_pass_that_is_still_running_reaches_the_queue`.
- **The two halves of `job-store --ranked` disagreed about zero.** `ranked`
  reads a falsy limit as no limit -- `LIMIT -1`, every open posting -- and the
  flag's own help calls the number the count to list. The command line asked
  whether that number was truthy, so `--ranked 0` read as "not asked for" and
  printed nothing but the summary line, which looks exactly like a store
  holding no open postings. The query is now asked whenever the flag is given.
  `docs/vps-deployment.md` used that form for a fortnight's health check and
  was getting the summary line by accident, so it now names the command that
  prints the summary and nothing else. Reproducer:
  `StoreTests.test_the_whole_ranking_is_printed_when_no_limit_is_given`.
- **A check created the index it was checking.** `JOBDISCO_STORE=<copy>
  job-store --verify` is what `deploy/local/backup-from-vps.sh` and the
  deployment notes tell an operator to run against a restored copy of the log,
  on a machine that may hold no index at all. Opening a database creates it, so
  the command verified the copy, left an empty SQLite file behind, and ended in
  a traceback about a missing `jobs` table with its own result scrolled off
  above it. It now says there is no index and exits 0. This is the same rule
  `ledger_guard` already keeps for the credit ledger. Reproducer:
  `StoreTests.test_a_check_does_not_create_the_index_it_is_asked_about`.

Measured, and worth separating from the above: the three page defects from the
round below -- the bare date, the overtaken refresh and the skip dialog's
target -- were covered by contracts on the source because this checkout had no
JavaScript runtime. It has one now. `review_static/app.js` was run under Node
22.22 against a jsdom 30.1 document, with `TZ=America/Los_Angeles`, outside the
repository and outside the suite: a bare `2026-09-20` rendered as Sep 20 rather
than Sep 19; a slow first queue answer landing after a newer one left the newer
queue in place; and a skip dialog opened on one posting filed its reason against
that posting after the selection had moved to another. The fixes hold. The
harness is not committed -- it needs an npm install, and the suite is offline --
so this is a measurement made here, not a test the suite will repeat.

### Paid discovery, B44-B49, from Codex's ninth audit, 2026-09-21 UTC (not deployed)

All six in `jsearch.py`, where a posting bought from the provider is read,
judged and kept. Each has a test red against the code before it; Codex's own
reproducer also stops holding at every assertion it reaches (B44-B46) before
its bookkeeping, written for the defective path, runs out.

- **The search phrase was read as the posting's own words.** `normalize_job`
  records the query that found a posting in `raw.discovery_queries`, and
  `description_text` walked it like any other field. So the phrase decided the
  verdict: an RTL role asking five years was refused when found by "RTL" and
  accepted when found by "RTL Intern" or "RTL New Grad" -- both in the shipped
  plan -- and an antenna job scored 0 or 38 depending on whether the query
  named the trade. Fields this collector writes into a payload are now listed
  once, in `COLLECTOR_FIELDS`, and skipped at every depth. Scores stored before
  this were computed with the leak; `job-store --rescore` corrects them, and
  the review queue's experience gate, which reads raw each time, is corrected
  at once. Reproducer: `PayloadReadingTests.test_the_search_phrase_is_not_evidence_about_the_job`.
- **A record emptied by cleaning took its page down.** `normalize_job` only
  failed where `normalize` did, and a title of whitespace survived that and was
  emptied by `clean_title` afterwards; an object-valued posting date survived
  too. Both reached SQLite at the page checkpoint, outside the per-item
  boundary, where the constraint or the binding raised and every valid posting
  on a page already paid for went with them. An empty title is now a malformed
  record. An object-valued date is dropped rather than refused: the field is
  optional, the provider's value stays in raw, and missing publisher data is
  not held against a posting anywhere else. Reproducer:
  `DiscoveryTests.test_an_unreadable_record_costs_itself_and_not_the_page`.
- **Joining the filter's patterns changed what some of them meant.** `any_of`
  joins patterns into one alternation, which is exact only for patterns with no
  groups: joining renumbers them, so a backreference pointed at a neighbour's
  capture, and two patterns each naming a group compiled alone -- passing
  `load_plan` -- and not together, which failed after a paid page had been
  bought. Patterns with groups, or with inline flags that only compile at the
  start, are now kept apart; the rest are still joined, so the measured saving
  the alternation was built for stands. Reproducer:
  `PayloadReadingTests.test_patterns_that_cannot_share_an_alternation_keep_their_meaning`.
- **An unreadable last page settled the sweep for the cycle.** Exhaustion was
  decided from the page's length alone, so a short page whose only record was
  malformed settled the cursor and the query was not asked again that cycle,
  with the posting lost. Such a page is now held open, exactly as an empty last
  page already is -- the repository has decided that one repeated page a day is
  the right price against a silently skipped query, and this pays it in the
  same place. Only the last page: holding a middle page would stall the query
  there for as long as the record stays broken, so a middle page still moves
  on, and its unreadable record is left to the daily pass. Reproducers:
  `DiscoveryTests.test_a_last_page_that_could_not_be_read_is_asked_again`, and
  `...test_a_middle_page_with_an_unreadable_record_still_moves_on` for the other
  side.
- **The first nonempty link won, not the first usable one.** A blank or
  `javascript:void(0)` apply link was chosen over a working Google link, failed
  the URL check and discarded the job; `https://` with no host passed the check
  and became the posting's identity. Candidates are now taken in their order
  until one is a public HTTP(S) address with a host. `collector.normalize`
  requires the host too, on every path, since an address without one is not
  public anywhere. Reproducer:
  `PayloadReadingTests.test_the_first_public_link_is_used_not_the_first_nonempty_one`.
- **The order of a payload's fields changed the experience verdict.** A field
  whose key names a qualification is emitted as a heading, and its scope ran on
  into whatever field came next: "preferred qualifications" before a job
  description made the description's five years optional, and the same two
  fields reversed refused the posting. The same leak ran the other way through
  the required-section context added for B32, turning a stock vesting schedule
  that followed a required-qualifications field into a requirement. A field
  that opens a heading now closes it, with a mark the parser reads as the end of
  both contexts. Reproducer:
  `PayloadReadingTests.test_the_order_of_a_payloads_fields_does_not_change_the_verdict`.

### Equivalent optimizations, 2026-09-21 UTC (not deployed)

Seven changes that do the same work in less of it, plus one packaging fix. No
policy, no filter and no output field changed; each is held to the answer it
replaced, by the existing suite and by an equivalence digest over a fixed
corpus. Numbers are medians on this workstation, before and after, from the
same script -- they say what changed here, not what the VPS will do.

- **The review queue is built when what it is built from changes.** Every
  request replayed the whole ledger and read every open posting, and a
  decision paid for it twice: once to find the group to write, once through
  the refresh that follows the write. The key is when the ledger and the index
  last changed, how long each is, and today's UTC date -- the last because the
  three-day window is a function of the clock and nothing else. On a synthetic
  2,000 postings one build measured 460 ms, so a decision now waits for one
  rather than two, and the click itself waits for none. Within a day the
  window drifts rather than moving: a posting stays in the recent tab slightly
  longer than it strictly should, and is in the backlog either way.
  Reproducer: `HttpTests.test_a_decision_does_not_rebuild_the_queue_it_was_just_given`.
- **A posting's prose is extracted once per posting.** Scoring it, judging it
  against the keep and reject rules, and running the experience gate each
  walked the raw payload again, and the gate ran twice -- once inside
  `rejection_reason` and once more for the seen record it had already written
  to the row. 2.53 ms to 2.10 ms per posting over a 400-posting corpus, with
  identical decisions, scores and matched terms.
- **A title that is text is not parsed as HTML.** Building a BeautifulSoup
  parser for each one is most of what `clean` cost, and almost every title has
  neither a tag nor an entity. 416 ms to 189 ms per 20,000 titles. The fast
  path is held to the parser's exact output, including its leaving internal
  spacing alone. Reproducer:
  `EquivalentFasterTests.test_the_fast_path_for_a_title_answers_what_the_parser_answers`.
- **A day file is replayed a line at a time.** `rebuild` read each one into a
  list first, which is every posting first seen that day with its description.
  9.4 MB peak to 1.1 MB on a synthetic 4,000-posting day, same rebuild.
- **Sources are stored in the order they finish.** `pool.map` returns in
  submission order, so one slow board held every board behind it out of the
  store -- and committing each source on its own is worth nothing if the
  commits queue behind the slowest board in the catalog. The reports are
  sorted back into catalog order afterwards, so what a reader sees does not
  depend on which board answered first. Reproducer:
  `EquivalentFasterTests.test_a_finished_source_is_stored_without_waiting_for_a_slow_one`.
- **The review page stops asking for what it already has.** A keystroke in the
  search box re-rendered the list and with it the detail, which re-fetched the
  description it had just been given; the search now settles for 120 ms first,
  and the description is remembered for the group it belongs to until the next
  refresh replaces the queue.
- **`tomli` is a dependency rather than an extra.** This package supports
  Python 3.10, where `tomllib` does not exist and every entry point reads the
  query plan through it. Nothing installed the extra, so a 3.10 install was one
  import from failing and nothing said so. Reproducer:
  `PackagingTests.test_the_toml_reader_is_a_dependency_and_not_an_extra`.

The page changes are the two that cannot be run here; see the note in the
round below about there being no JavaScript runtime in this checkout.

### Function-by-function audit, B34-B43, 2026-09-21 UTC (not deployed)

Codex's eighth round, across six files. Four of them read a posting's own words
wrongly, three are in the review server and its page, and three are things the
page can only get wrong in a browser.

- **A number named in order to be ruled out was read as a requirement.** The
  denial was only ever looked for in front of the figure, so "five years of
  experience is not required" rejected the posting that said it -- the ones
  most willing to take someone early were the ones this gate refused.
  Reproducer: `StatedAndDeniedTests.test_a_requirement_denied_after_the_number_is_not_a_requirement`.
- **An internship already served was read as an internship being offered.**
  "Prior internship experience required" granted the entry-level override,
  which skips the experience gate entirely, so the eight years beside it were
  never looked at. Such a posting is not refused for it -- an internship
  already done is a qualification -- it is marked, and the review page shows
  the mark. The same reading is what keeps it out of the override. Reproducer:
  `StatedAndDeniedTests.test_an_internship_already_served_is_not_an_internship_posting`.
- **A slash inside a term of the trade read as a degree alternative.** Any `/`
  in the block made the bachelor's and master's paths alternatives, so
  "BS with 5 years of RTL/FPGA experience, MS with 2 years" took the master's
  two years as the effective requirement and kept a posting asking five. A
  slash now counts only where it stands between the two paths -- spaced, as in
  "BS+4 / MS+2", or joining the degrees themselves. Reproducer:
  `StatedAndDeniedTests.test_a_slash_inside_a_term_of_the_trade_is_not_a_degree_alternative`.
- **A title was only half cleaned, and cleaning it twice gave a different
  answer.** Each suffix is removable only at the end of the string, so whichever
  the publisher put last was the only one a single pass could reach: a title
  ending in its location came back still carrying its date. `clean_title` now
  repeats until the title settles, which also makes it idempotent -- the same
  posting was otherwise stored under two spellings depending on how many times
  the function had been applied. Reproducer:
  `TitleTests.test_both_suffixes_come_off_whichever_order_they_are_in`.
- **An off-query employer overwrote a refusal about the posting itself.**
  `take` set `employer_mismatch` over whatever `rejection_reason` had already
  decided. `seen_jobs` keeps the last decision written, so a posting refused on
  its own terms -- an excluded title, an excluded employer, an experience bar
  -- was recorded as merely off-query, and the review queue's rule for hiding
  rejected postings stopped applying to it. The mismatch is now recorded only
  where nothing else refused the posting. Reproducer:
  `DiscoveryTests.test_an_off_query_employer_does_not_overwrite_a_refusal`.
- **A posting that moved provider was reported as one that had been replaced.**
  The check added for a reused address compared the decision's key with the
  key the row holds now, and a posting found again on the company's own board
  keeps its URL while changing provider -- which changes that key. The history
  of an application then refused to show the description of the job it was
  made against. The page now sends the provider and title it is showing, which
  is what tells a posting that moved from one that was replaced; the URL
  already fixes the employer. Reproducer:
  `HttpTests.test_a_posting_that_moved_provider_is_not_reported_as_replaced`.
- **A plain-text description was handed to an HTML parser.** Everything went
  through BeautifulSoup, including descriptions the provider states as plain
  text, so a sentence about `vector<T>` came back about `vector` -- a hole in
  the text with nothing to say one had been made. Parsing now happens only
  where there is markup to parse, recognised by tag name rather than by the
  presence of an angle bracket. Reproducer:
  `HttpTests.test_a_plain_description_is_not_handed_to_an_html_parser`.
- **Every date on the review page was a day early west of Greenwich.**
  `new Date('2026-09-20')` is UTC midnight, which is the 19th in Los Angeles. A
  bare date is a calendar day and is now read as one.
- **An older refresh could overwrite a newer queue.** Two refreshes can be in
  flight -- a click, a decision saving, a slow first request -- and they do not
  answer in the order they were asked. The later answer is the current one.
- **The skip dialog filed its reason against whatever was selected when it was
  submitted.** A refresh landing while the dialog was open changed the
  selection, and the reason typed for one posting was written against another.
  The dialog now records the posting it was opened for.

The last three are in `review_static/app.js`. This checkout has no JavaScript
runtime, so they are covered by contracts on the source in
`ClientSourceContractTests` -- the shape of the fix, not its behaviour. The
audit that found them runs the script itself, which is where their behaviour
should be confirmed.

### Experience parser, from Codex's seventh audit, 2026-09-21 UTC (not deployed)

Three ways an explicit requirement was read as no requirement at all. Each one
kept a posting in the review queue that states terms disqualifying it, so all
three fail in the direction that shows work rather than hides it -- which is
why they survived: nothing downstream complains about a posting that is there.

- **An optional skill erased the requirement standing beside it.** The clause
  splitter cut a sentence only where a comma introduced another number, so
  "5 years experience required, FPGA knowledge preferred" stayed one clause,
  the trailing `preferred` matched, and the whole sentence was discarded --
  requirement included. A comma now also cuts where it hands an optional marker
  a subject of its own, which is what separates that sentence from "5 years
  experience, preferred", where the same marker attaches to the years
  themselves and still makes them optional. Reproducer:
  `SectionsAndFormatsTests.test_an_optional_skill_does_not_erase_the_requirement_beside_it`.
- **A required heading did not reach the bullet under it.** Headings only ever
  cleared the optional context; they never established a required one. Under
  "Required qualifications:", a line reading "3 years of RTL design." carries
  none of the words the candidate test looks for -- `experience`, `required`, a
  degree -- and is not a bare years expression either, so its three years were
  discarded. There is now a required-section context beside the optional one.
  They are not opposites: either heading replaces both, and Responsibilities,
  About, Benefits or "What you" ends both. A bare duration admitted this way is
  still refused where it is elapsed time rather than experience -- "deliver two
  tape-outs within 3 years" is a deadline the job sets. Reproducer:
  `SectionsAndFormatsTests.test_a_required_heading_makes_the_bullet_under_it_mandatory`.
- **Two numeric formats read as no number.** "3-year experience" failed because
  the unit had to be preceded by whitespace, and "2.5 years" failed because the
  bound had to be an integer -- the decimal guard correctly refused to read the
  trailing 5 as a separate number, and nothing else matched. Both are read now,
  and 2.5 is kept as 2.5: rounding it down puts the posting on the other side
  of a two-year gate. A hyphen carrying the unit does not make a roadmap, a
  degree or a programme into experience; those are still refused by what
  follows the number. Reproducers:
  `SectionsAndFormatsTests.test_a_hyphen_can_carry_the_unit`,
  `...test_a_fractional_bound_is_neither_rounded_down_nor_split`, and
  `...test_hyphenated_durations_that_are_not_work_stay_out` holding the line.

### Fifth review round, 2026-09-21 UTC (branch, not deployed)

Four, and three of them are defects in the fixes made earlier in this same
session. They are recorded here as their own entries rather than folded into
the originals, because a fix that introduces a defect is the thing this log is
for.

- **A decision followed its posting to a provider that was not carrying it.**
  The fix that lets an applied decision survive a posting moving from JSearch
  to the company's own board matched on the URL whenever the provider changed.
  A changed provider is not on its own evidence that it is the same opening:
  an address can be handed to a different board advertising a different job,
  and the new posting was then hidden behind the old decision. The company and
  the title must agree as well. A posting that was genuinely retitled comes
  back as pending, which is the side to err on. Reproducer:
  `ApplicationsTests.test_a_replacement_at_that_address_is_not_the_posting_that_was_applied_to`.
- **A rejection took down whatever held its address.** The fix that hides a
  posting its latest pass rejected matched `seen_jobs` on the URL, so one
  posting refused and another accepted at the same address -- exactly what a
  reused URL produces -- hid the accepted one. The match is now on the
  requisition, which is also `seen_jobs`'s primary key. Measured on a synthetic
  1,200 postings and 12,000 seen rows: 860 ms median for the address match,
  0.86 ms for the requisition match, with the query plan moving from
  `provider_key=?` alone to `provider_key=? AND source_job_id=?`. No additional
  index is owed; the correctness fix is the whole of the speedup. Reproducer:
  `ApplicationsTests.test_a_rejection_of_another_requisition_at_that_address_hides_nothing`.
- **The backfill wrote no manifest for a day that only closed a posting.**
  Closures are appended to the day they happened, which need not be a day
  anything was first seen, and manifests were written only for the days in the
  first-seen index. The export finished, and the store it produced failed its
  own integrity check with a run file nothing described -- so the one command
  for rebuilding history produced history that could not be rebuilt from.
  Reproducer: `BackfillExportTests.test_it_writes_a_manifest_for_a_day_that_only_closed_a_posting`.
- **A rescore the log refused left the index ahead of it.** The fix that
  publishes corrected scores wrote SQLite first and appended afterwards. A
  failed append left the new score in the index and the old one in the log:
  the rebuild restored the old score, the manifest still matched its file so
  the integrity check said nothing, and running the command again found the
  index already holding the new value, counted nothing as changed and published
  nothing -- the correction could not be recovered by repeating the command
  that made it. The log is now written first, per batch, through the same
  connection that holds the uncommitted update, and a failure rolls that update
  back. The index ends up behind the log rather than ahead of it, which is the
  direction a later rescore repairs by itself. Reproducer:
  `ScoreOnceTests.test_a_rescore_the_log_refused_leaves_the_index_where_it_was`.

### Fourth review round, 2026-09-21 UTC (branch, not deployed)

Three more, and one withdrawal. Same conditions: a failing test first, nothing
collected, spent or deployed, no claim checked against the production database.
The withdrawal is recorded in the round below, where the entry was.

- **A posting the last pass rejected was still offered from the copy that
  passed.** A paid pass that rejects a posting does not store the description it
  rejected -- a rejected posting is recognised, not stored -- so the index kept
  the text from the pass that accepted it, and the review queue went on showing
  a posting whose published terms now disqualify it, with the description that
  still qualified. The rejection is already on record in `seen_jobs`, and it is
  newer than the row being shown, which is what the queue now reads. Only the
  same provider, and only the reasons in `HARD_REJECTIONS`: those are
  properties of the posting, while an employer mismatch says the query asked
  the wrong question. The stored description stays stale, deliberately -- the
  posting is hidden, not rewritten, and nothing else reads that text once it is
  out of the queue. An index with no `seen_jobs` table simply has no rejections
  to read. Reproducers:
  `ApplicationsTests.test_a_posting_the_last_pass_rejected_is_not_offered_from_an_older_copy`,
  with `...test_an_older_rejection_does_not_hide_what_a_later_pass_accepted`
  and `...test_a_query_scoped_rejection_does_not_hide_the_posting` holding the
  other side.
- **A TI board was stored under one provider and closed under another.** The
  collector rewrites a `ti_careers` source to the `oracle_cloud` endpoint its
  shell names, so its rows are stored as `oracle_cloud` -- but `main` kept
  reporting and persisting under the source the catalog names, and closing is
  scoped by company and provider. It therefore compared the board against an
  inventory holding no rows: two complete passes went from five postings to
  four and all five stayed open. The pass now persists and reports under the
  source the collector actually read. Reproducer:
  `EffectiveProviderTests.test_a_board_that_lost_a_posting_closes_it`.
- **The TI shell's ETag was stored as the board's validator.** The first
  response from that source is the wrapper page that names the API; `fetch`
  takes its ETag as the source's validator, and the next pass then probed the
  wrapper conditionally. A 304 from a page of unchanged markup ended the pass
  before the jobs API was asked at all, so every arrival and change behind it
  was missed. A source whose postings come from somewhere other than its
  access URL now keeps no validator and is read in full. Whether TI's shell
  actually serves an ETag has not been checked against the live site; the
  trigger was reproduced offline. Reproducer:
  `CollectionTests.test_the_ti_shell_does_not_supply_the_boards_validator`.

### Third review round, 2026-09-21 UTC (branch, not deployed)

Seven more, on the same branch and under the same conditions: each reproduced
by a test that fails on the code before it and passes after, nothing collected,
spent or deployed, and nothing checked against the production database.

- **A source the log refused was committed to the index anyway.** `persist`
  appended to the day file and then committed; when the append raised, the
  exception carried up to the pass's own handler, which sealed the day -- and
  the seal committed. So the index held postings the log had never received,
  which no rebuild can restore, with that source's watermark advanced past them
  so the next pass would not look again, and with the manifest rewritten over
  an unchanged file so `--verify` still called the day sound. The log is the
  record and SQLite is derived from it; the two now fail together. `persist`
  rolls back the source it could not log, and the seal rolls back before it
  writes anything of its own. Reproducer:
  `LedgerBeforeIndexTests.test_a_pass_that_could_not_log_a_source_does_not_keep_it`.
- **Two requisitions at one address, in one batch, became one posting.**
  Nothing is written until the whole batch is prepared, so the second row on a
  URL asked the index and found whatever was there before the pass, not the row
  just prepared. The displaced posting's raw was merged into the new one --
  every field name the new provider payload did not itself use survived, the
  description among them -- and its identity stayed in `job_identities` as a
  live alias. A posting whose title needs its description as evidence was then
  judged on the description of the opening it replaced, and the review queue
  dropped it. The row already prepared is now what a second row on that URL
  follows. Reproducer:
  `OneBatchOneUrlTests.test_the_later_posting_does_not_inherit_the_earlier_one`.
- **The sitemap path never asked what requisition a URL carried.**
  `html_job_id` knows that Renesas ends its slug with the requisition
  (`-jid-6866`), and knows it because without that a retitled or relocated
  posting reads as one withdrawal and one arrival. `collect_sitemap` never
  called it, so exactly that happened on the one board the rule was written
  for. Only providers with a rule of their own take an id from their URL: the
  generic fallback is the last path segment, which two postings can share.
  Reproducer: `EarlyStopTests.test_a_renesas_posting_keeps_its_requisition_when_its_slug_changes`.
- **Withdrawn: a row that would not parse read as a posting that had gone.**
  The case as reported does not occur. A record `normalize` refuses is kept in
  `Collector.rejected`, and `main.direct` turns any pass holding rejects into a
  partial one, so the store never retires what a pass failed to read. The
  reproducer that showed otherwise called `Collector.run` directly and so
  missed the guard that the pipeline applies. The change made for it -- an
  untitled job link reported as a malformed record, and a collector-level
  downgrade on rejects -- was reverted: the downgrade only restated what `main`
  already does, and the untitled-link change would have made any board carrying
  a text-free job link permanently incomplete, which is a board whose postings
  can never be retired. `html_items` skips untitled links again.
- **`--export` could not export history.** The backfill writes each posting
  into the day it was first seen, and every such day but today is a day that
  has sealed, so the one command for rebuilding a store from an index refused
  its own first posting. The seal protects a record that exists; `--export`
  already refuses to run against a store holding any history at all, so there
  is none to protect. That one path may now write sealed days, explicitly.
  Reproducer: `BackfillExportTests.test_it_exports_a_posting_first_seen_on_a_day_that_has_sealed`.
- **An Eightfold position with no link of its own became the board's front
  page.** `urljoin(access_url, item.get('positionUrl') or '')` resolves to the
  board itself, so every such position shared one URL: the first was kept, the
  rest were dropped as duplicates of it, and the pass reported complete. A
  posting without a link is a malformed record and now says so. Reproducer:
  `CollectionTests.test_a_position_without_a_link_is_malformed_not_a_duplicate`.
- **An applied decision was illustrated with another posting's prose.** The
  review page asked `/api/job` for whatever row holds that URL, and a decided
  group is replayed from the snapshot it was decided on. Where a board had
  since advertised a different requisition at that address, the history showed
  the new opening's description under the old one's title -- which reads as
  though the application was made against something it never was. `/api/job`
  now takes the group it is illustrating and says so when the address has
  changed hands. Reproducer:
  `HttpTests.test_history_does_not_show_a_later_requisitions_description`.

### Second review round, 2026-09-20 UTC (branch, not deployed)

Seven reproduced defects in the applications ledger, the store, paid
discovery, collection and the two backup scripts. Same conditions as the round
below: a failing test first in every case, no collection, no spending, no
deployment, and no claim checked against the production database.

- **A decision did not survive its posting changing provider.** A posting found
  first through JSearch and later on the company's own board keeps its URL --
  the store merges the two discoveries into one row -- but takes the direct
  provider, and `decision_key` is scoped by provider. So the pass that found it
  directly put an already-applied job back in the queue, and a second
  application is the mistake the ledger exists to prevent. A decision is now
  also matched by URL where the provider has changed, which stays clear of the
  case the URL fallback was narrowed for: one board reusing an address for a
  new requisition, where the provider is the same. Reproducer:
  `ApplicationsTests.test_a_decision_follows_a_posting_from_jsearch_to_the_direct_board`.
- **`--rescore` did not survive a rebuild.** It wrote the corrected scores to
  SQLite only. SQLite is derived: the next `--bootstrap` replays the log and
  restores the scores the rescore was run to replace, silently and with the
  ranking it was run to fix. The scores that moved are now appended to today's
  log as corrections, and its manifest is re-checksummed without restating what
  the day collected. Reproducer:
  `ScoreOnceTests.test_a_rescore_reaches_the_log_so_a_rebuild_keeps_it`.
- **An unhashable job id threw away a page that had been paid for.**
  `page_identity` built a set of the ids on a page to notice a provider
  repeating itself. An id sent as a list or an object raised there, before
  `take` had been given the page, so one malformed id cost every sound result
  beside it and the credit already spent on them. Such a page is simply not
  comparable, which is what `None` already meant. Reproducer:
  `PageIdentityTests.test_an_id_that_cannot_go_in_a_set_leaves_the_page_incomparable`.
- **The conditional probe turned a POST board into a refused GET.** It sent
  `request_for(source)[0]` -- the URL, without its method or payload. Workday
  answers a POST and holds an ETag like any other board, so it earned a
  conditional strategy and was then probed with a GET it refuses, and a refusal
  is a 24-hour pause for the whole source. The probe is now only used where the
  board is read with a GET; a POST probe would cost as much as the pass it
  precedes, so such a board reads in full instead. Reproducer:
  `EarlyStopTests.test_a_post_board_is_not_probed_with_a_get`.
- **One idle connection stopped the review service.** Requests were served one
  at a time, and reading a request line that never arrives does not return. A
  browser opens such sockets by itself, speculatively, so the review page could
  hang the service it was talking to. It now serves requests in threads with a
  read timeout, and holds a lock across read-queue-then-append so two decisions
  cannot interleave in the one file nothing regenerates. Reproducer:
  `HttpTests.test_an_idle_connection_does_not_stop_the_server`.
- **The disaster-recovery pull accepted a copy it had not checked.**
  `backup-from-vps.sh` verified that operational files were present, that the
  SQLite snapshot opened, and that runs and manifests paired up -- but never
  that a run file matched the digest its manifest records, which is the only
  check that notices a truncated or damaged transfer. An unverified copy
  rotates into `current`, and the next one moves it to `previous`: two pulls
  replace both intact generations. Digests are now verified where a Python
  exists, and said to be unverified where none does. The day still being
  written is exempt: a pass may be appending to it while tar reads it, and its
  manifest is rewritten when the pass finishes, so a mismatch there is a race
  and not a damaged copy. Reproducers:
  `BackupTests.test_invalid_copies_preserve_both_recovery_generations` (the
  `corrupt-run-file` case) and
  `...test_the_day_still_being_written_may_differ_from_its_manifest`.
- **A paid query that paged five times was recorded as one request.**
  `persist_query` wrote `1 if pages_used else 0`, and the checkpoint wrote a
  literal 1. The manifest's request total is what a reader checks paid usage
  against, and it understated every multi-page query by however deep the sweep
  went. Both now record the pages actually billed. Reproducer:
  `DiscoveryTests.test_a_multi_page_query_reports_every_page_it_paid_for`.

### Review findings worked through offline, 2026-09-20 (branch, not deployed)

Nine defects from a review of `collector.py`, `experience.py`,
`collection_policy.py`, `validate_sources.py` and `backup-applications.sh`.
Each was reproduced in a test that fails on `ef6d4b3` before it passes here.
Nothing was collected, spent or deployed for this work, and no claim below
rests on a production database.

- **A pass that hit the job cap could still report a complete board.** `add()`
  stops keeping postings at `--max-jobs`, and `collect_json` then compared the
  page offset with the provider's total and called that complete -- a board of
  150 read under a cap of 100 ended as 'complete' with 50 postings dropped,
  and 'complete' is exactly what lets the store retire what the pass did not
  list. The cap is now answered once, in `run()`, which is the single place
  every collector verdict passes through; `collect()` holds what `run()` used
  to. Reproducer: `CollectionTests.test_the_job_cap_is_never_a_complete_board`.
- **A blank later page outranked the count the board had just stated.** An
  empty page after the first ended pagination as 'complete' whatever the
  provider had said the board held, so a board advertising 500 and stopping at
  120 retired the other 380. An empty page now ends the list only where
  nothing contradicts it. This deliberately changes a case an earlier test
  asserted the other way: `test_a_blank_later_page_just_ends_pagination` held
  a board stating 99 while listing one posting, which is a board disagreeing
  with itself rather than one ending. That test keeps its purpose, with a
  fixture that states no count, and the contradiction is now its own test.
  The same number was already believed in the other direction, at
  `offset >= total`. Reproducer:
  `EmptyBoardTests.test_a_board_that_stops_short_of_its_own_count_is_not_complete`.
- **A stated zero was read as no statement at all.** `reported_total` chained
  `or` across the keys a provider might use, so a board reporting `total: 0`
  fell through to the next key and returned None. The one case the zero exists
  for -- an empty board that says it is empty -- therefore read as a board
  that reported nothing, could never be called complete, and could never
  retire the postings the company had withdrawn. It now returns the first key
  the provider actually sets. Reproducer:
  `CollectionTests.test_a_stated_zero_is_a_count_not_a_silence`.
- **One malformed record ended the source.** `add()` caught `ValueError` from
  `normalize`, but a provider sending null where it has always sent a string
  raises `AttributeError` or `TypeError` -- `externalPath: null` on Workday
  does -- and that escaped the loop, ending the board and every later page of
  good postings with it. Rejected records are already collected, reported and
  written out per source; they now include these. Reproducer:
  `CollectionTests.test_a_null_field_rejects_one_record_not_the_board`.
- **robots.txt was requested before the cooldown was checked.** `SourcePolicy`
  resolved its interval in `__init__`, and resolving it fetches the host's
  robots.txt, so constructing the policy contacted a host that might be inside
  an active pause -- from the object whose purpose is to keep us off it, and
  before `check()` could say so. The interval is now a property resolved on
  first use; every caller already reads it after `check()`. Reproducers:
  `CollectionPolicyTests.test_pacing_is_resolved_only_when_a_request_is_due`
  and `...test_a_paused_source_is_not_asked_for_its_pacing`.
- **"No less than five years" was read as a ceiling.** `NOT_A_MINIMUM` saw the
  "no" and discarded the requirement, so some of the strictest postings in the
  set were read as stating no requirement at all and kept. A floor stated in
  the negative is still a floor. Reproducer:
  `UpperBoundTests.test_a_floor_stated_in_the_negative_is_still_a_floor`.
- **"This is not an internship" was read as one.** `entry_level` already knew
  that a mention governed by a supervising verb describes someone else; a
  mention governed by a denial describes what the posting is refusing to be,
  and it granted the entry-level override on the strength of the word that was
  there to exclude it. An override skips the experience gate entirely.
  Reproducer: `MentionedPeopleTests.test_a_denied_internship_is_not_an_internship`.
- **The validator built its report directory only at the write.** `data/raw/`
  is gitignored, so a fresh checkout does not have it, and `job-validate-sources`
  probed every source and then raised `FileNotFoundError` on the file it had
  spent the whole run producing. The directory is now made before the first
  probe. Reproducer:
  `ValidatorReportTests.test_the_report_directory_exists_before_the_first_probe`.
- **The ledger backup never retried a failed push.** `backup-applications.sh`
  pushed only on the tick that had just committed something. A push that
  failed left the commit local, and the next tick found no new decision,
  reset the index and exited 0 -- so the ledger waited for the next decision
  rather than the next tick, which is backwards: the failed push is what
  leaves it on one disk, and days can pass before another decision is made.
  Its own comment claimed the opposite ("will go out with the next tick").
  Committing and pushing are now separate: any commit `origin/main` does not
  have is pushed. Reproducer:
  `ApplicationsBackupTests.test_a_failed_push_is_retried_on_the_next_tick`,
  which needs flock and skips on Windows; the behaviour was measured here
  instead by driving the script under Git Bash with a lock stub, where the old
  script left the remote at one commit after the remote came back and the new
  one pushed without a new decision.

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

### Mentoring an intern read as being one

The experience gate skips its years check when a posting is an intern or
new-grad opening, and it looked for those words in the title **and anywhere in
the description**. Descriptions routinely name interns as people the role
supervises, so `You will mentor our interns` granted the override to a posting
demanding eight years, and the gate never ran.

The title is still taken at its word. In the body a mention governed by a
supervising verb -- mentor, manage, lead, coach, train, oversee, support,
collaborate with -- is now read as what it is: evidence of seniority, not of an
internship. A posting describing *itself* (`This internship runs for 12 weeks`)
still overrides, because no such verb governs it.

### A ceiling was read as a floor

`fewer than 3 years`, `no more than 5 years`, `under 5 years`, `up to 6 years`
and `no 3 years of experience needed` all state who may apply, not what they
must already have. The years pattern saw only the number and treated each as a
minimum, so postings that were advertising themselves as junior were rejected
for being senior.

A number preceded by a denial or an upper bound is no longer a requirement.
`at least`, `minimum` and a bare `3+ years` are untouched, and both directions
are covered by tests, because the risk of a rule like this is that it quietly
swallows the real floors too.

### The same posting was read four times to judge it once

`rejection_reason` asked `description_text` for the same payload three times
and `relevance` asked a fourth, each walking the raw JSON in full. It reads
once and passes the text down now: two extractions per posting, which is the
floor while the experience gate needs a structured variant and the score needs
a flat one. Output is identical; only the number of walks changed.

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
