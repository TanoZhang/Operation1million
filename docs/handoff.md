> **Startup rule:** Read the newest handoff first. Older handoffs are historical
> evidence, not current instructions or an active backlog.

# Continued audit and improvement study - 2026-09-23 UTC (codex)

Source remains `b2c9340f84dbe5f7fb020301c2d724af32587424`; the standing codex
branch contains audit documentation and synthetic harnesses only. Four new
defects reproduce through storage and Review: negated citizenship requirements,
lost requirements-field headings, experience preference scope and an inline
required PhD heading after a preferred section. The new eight-test harness has
four failures and four passing controls; R1-R3 remain in the earlier report.

Behavior-preserving prototypes pass 43 existing tests and exact-output checks.
Reusing parsed description text cuts HTML parsing from three calls to two and
measures 1.90x faster for synthetic details with qualification fields. Per-sort
bounded caches measure 1.75-3.46x faster with repeated timestamps but 10.5% slower
with all-unique inputs. Consolidating decision matching is an unimplemented
structure proposal. See [round-two report](review-audit-round2-2026-09-23.md),
its reproduction harness and `docs/review-benchmark-2026-09-23.py`.

No application code, database/schema, log format, collection or deployment
changed. Measurements are offline and synthetic, not production throughput.

# Latest Review audit - 2026-09-23 UTC (codex, findings only)

Audited application source and last fetched main:
`b2c9340f84dbe5f7fb020301c2d724af32587424`. Three synthetic defects reproduce:
empty HTML refresh deletes the only useful teaser and admits an ineligible
posting; a null teaser retains obsolete experience requirements; conditional
PhD wording hides a posting without establishing an exclusive requirement.
See [audit report](review-audit-2026-09-23.md) and its runnable six-case
reproducer. Existing focused tests: 177 pass. Reproducer: three failures and
three passing controls. Published on standing `codex`; no application source
changes, deployment, production measurement or collection. Prior deployment
status below remains historical evidence.

# PhD preference wording and stale-text rejects - 2026-09-23 UTC (claude, not deployed)

Base: 583bfd7. Fixes wrong hard rejects: PhD wording that is a preference
(desirable, advantage, encouraged, ideal, welcome, "Ph.D. Preferred",
preference headings after a required section), a stale teaser surviving a
full-description update, and "If selected for a position that requires..."
read as an unconditional citizenship requirement. Details in the architecture
bug log. Zero verdict changes over the local index's 38,193 open postings
(the VPS holds more; not measured there). Pushed to main only: run
`deploy/vps/install.sh` to deploy.

Follow-up, same day: a record with qualification fields but no description
now shows the paid `jsearch.job_description` with those sections (kind
`discovery`) instead of the sections alone; 0 of 38,193 local open postings
had that shape, so nothing visible changes today. `store.slim` keeping
duplicate HTML that has inline tags is deliberately left alone: dropping it
would delete a field the plain text cannot reconstruct, which
`docs/coding-standards.md` forbids. `deploy/local/open-review.bat` is now
tracked.

# Audit fixes deployed - 2026-09-23 UTC

Code release: cc8bd4a014db3ee4ec00352d2800de9f909c49fd, pushed to private main
and installed through deploy/vps/install.sh. The installer printed that exact
commit. Earlier audit sections marked not deployed are now deployed.

Evidence: full local suite 639 tests, 630 passed and nine Windows skips; VPS
focused description, rules, payload and store suite 178 tests, all passed.
A read-only comparison of the old and new citizenship predicate over 40,662
open production postings found zero changed verdicts. Review queue and one
pending job detail returned HTTP 200; queue groups were 453 pending, 6,931
backlog, two applied and three skipped. Review service, collection timer and
backup timer were active. No manual collection, data purge or history rewrite
was performed. The documentation-only commit carrying this record follows the
tested code release and is synchronized through the same installer.

# Audit fixes release validation - 2026-09-22 UTC

The user authorized merging the accumulated audit fixes into private main and
deploying them through the VPS installer. The complete offline suite on c1a322e
plus this patch ran 639 tests: 630 passed, nine Windows environment skips.
Whitespace checks passed. No storage purge, history rewrite or collection is
part of this release. The unrelated local open-review.bat is not included.
Deployment and production verification are pending at this checkpoint.

# Nested qualification display fix - 2026-09-22 UTC (not deployed)

Base: c1a322edddd54aaa0a34edff8cded252cce2d99d plus prior local fixes.
Fixed nested qualification dictionaries and arrays being silently omitted from
Review details even though filtering reads their strings. Recursive display
preserves labels and scalar values without changing raw storage or policy.
The new HTTP regression failed before the fix; all 132 focused description,
payload and store tests pass afterward. No production data or deployment changed.

# Content-preservation follow-up - 2026-09-22 UTC (not deployed)

On c1a322e plus the prior six-fix patch, fixed three additional cases: unique
teaser requirements lost beside nonempty descriptions, required headings hidden
by substring-based display deduplication, and literal type names lost when plain
text contained HTML entities. Distinct excerpts are retained and shown, separate
qualification sections preserve their meaning, and Review shares the text
renderer. No stored-data changes or deployment occurred.

Latest verification: 131 focused storage, description and payload tests passed;
diff whitespace checks passed. The 635-test full run below predates these
follow-up changes. New regression fixtures cover both persisted filtering and
loopback HTTP responses.

# Six post-location audit fixes - 2026-09-22 UTC (codex, not deployed)

Base: c1a322edddd54aaa0a34edff8cded252cce2d99d plus the working tree.
Claude's location and degree fixes are retained. This patch fixes stale HTML
resurrection, structural HTML deduplication, citizenship clause scope, empty
HTML hiding teasers, omitted qualification sections and non-object paid raw
payloads breaking the Review queue. It also covers array-valued qualifications
and the equivalent malformed JSON scalar/list cases.

The focused suite passed 154 tests, including real storage, log replay
and loopback HTTP. Full suite: 635 discovered, 626 passed, nine environment
skips on Windows. No deployment, provider
requests or production-data changes were made. Historical text already removed
by old slimming cannot be recreated from the remaining text; future provider
updates use the corrected write path.

# The eligibility refactor reviewed, merged and deployed - 2026-09-22 UTC

**Deployed.** The sections below written as "not deployed" -- the shared
eligibility entry point, the PhD preference, negation and structured-field
fixes, and `coding-standards.md` -- were reviewed, merged and deployed in
`bb8e934` and the commit carrying this section. Their own claims are otherwise
unchanged; only their deployment status is.

What the review checked, rather than taking the green suite for it:

- `jsearch.eligibility_rejection` runs the same three checks in the same order
  the two callers ran separately -- experience, U.S. person, PhD -- and still
  writes `experience_filter` into the row for the paid collector's diagnostics.
  The queue keeps setting `job['experience_filter']` from its return.
- The PhD additions only ever keep more: a title that says a PhD is preferred
  or a plus, "No PhD required", "PhD optional", and an explicit "or relevant
  experience" alternative. Measured against every open posting in the live
  index, they change no verdict.
- One gap left: a requirement behind its own heading on one line, "Required:
  PhD in EE", was read as neither a heading nor a requirement. Both halves are
  now read. Measured on the live index: no posting changes verdict, so this is
  a latent case closed, not a change to the queue.

# Current patch overview - 2026-09-22 UTC (not deployed)

Base: feda989aa91d407408f2df1d21e6f5eb8f985407 plus the local working tree.
The patch fixes PhD preference, negation, alternative-experience and structured
field boundary handling, and shares eligibility checks between intake and Review.
The latest structural change separates description preparation from degree
policy and groups patterns before helpers. All 89 focused tests pass; comparing
the immediate pre-refactor code with the refactor on 38,302 local stored postings
produced zero changed degree verdicts. This is local evidence, not a VPS run.

Documentation responsibilities: this handoff records current status;
[architecture](architecture.md) maps modules and preserves bug evidence;
[coding standards](coding-standards.md) defines implementation conventions and
the user's lossless storage requirement. Historical detail follows below.

No field removal, export-format change, stored-data rewrite or deployment is
included. Disk savings have not yet been implemented; the measurements below
identify candidates for future lossless compression and deduplication.

# Coding conventions and lossless storage scope - 2026-09-22 UTC

The user clarified that optimization must preserve every content value and
function. Withdrawn local company-values field removal and compressed-only
export changes; collector, store and daily-pass behavior remains unchanged.
Removed only the newly created tests/test_storage_size.py for that withdrawn
implementation; it is recoverable from this task's patch history.

Added docs/coding-standards.md covering shared responsibilities, explicit side
effects, measured optimization and lossless round-trip requirements. Simplified
the degree matcher from a stateless wrapper object to a typed boolean helper;
documented the shared eligibility helper's raw diagnostic mutation. All 89
degree, experience and Review-rule tests pass on feda989 plus this working tree.
No deployment or stored-data modification occurred.

Read-only VPS measurement: root filesystem 5.1 GB used / 33 GB available;
code/runs 1.6 GB, durable data/runs 275 MB, data/.git 497 MB. A local historical
export sample compresses from 447,013,279 combined CSV/JSONL bytes to 26,851,736
JSONL gzip bytes, but that representation was withdrawn because it omits the
existing CSV interface. These are measurements, not savings already realized.

# PhD-only boundary fixes - 2026-09-22 UTC (codex, not deployed)

Latest follow-up: corrected the working-tree alternative matcher so that
`PhD required` plus `relevant experience` remains a hard reject unless `or`
explicitly offers the experience as an alternative. Reused degree matches
within each description block to avoid repeated regex scans. The 89 relevant
degree, experience and Review-rule tests pass on base `feda989` plus this patch.
The full-suite result below predates this focused follow-up.

Fixed conservative-filter violations found while reviewing `886e375`.
Titles saying a PhD is preferred, a plus or ideal now stay. So do explicit
negations (`No PhD required`, `PhD optional`) and alternative relevant or
comparable experience; positive PhD requirements remain hard rejects. Structured raw
fields now end their own required/preferred heading scope through the shared
`experience.SECTION_END` marker, preventing both a preferred field from
hiding a later requirement and a required field from capturing later prose.
Paid intake and Review now call one `jsearch.eligibility_rejection` helper for
experience, U.S.-person and PhD checks, instead of independently maintaining
the same sequence.

Ten focused degree tests and 150 related cross-path tests pass. The full
offline suite passed at `feda989aa91d407408f2df1d21e6f5eb8f985407` plus this
working tree: 624 discovered, 615 executed, nine environment skips. No provider call,
VPS operation, rescore or deployment was performed. The untracked local Review
launcher was not changed.

# Review filters rebuilt with the user; everything deployed - 2026-09-22 UTC

**Deployed.** The VPS runs `886e375`, the head of `main`. That includes all of
Codex's work below this section -- the answer bank, the highest-Fit sort, the
DOJ and user domain blocklists -- which those sections still call "not
deployed": they were merged and deployed the same day. Suite green on the VPS
(620 tests, no skips); stored scores rescored for all 41,923 postings after
the last change to scoring.

What the review queue now does, all asked for by the user during the day; the
bug log in `architecture.md` has the measurement behind each:

- **One list.** "To review" runs new (72 h), then backlog, then everything
  `less_related` (last band and Fit under `min_confidence`) at the end. A
  decision moves the posting immediately; the server patches its cached queue
  instead of rebuilding.
- **Removed outright** (queue and paid filter alike): titles naming principal,
  lead or trabajo (except "up to Principal Level" and "Lead & IC Engineers");
  the soft title block now reaching direct boards, with a softer
  `function_title_patterns` tier kept when the title names hardware and a
  role; blocked job sites by host, publisher or word; descriptions requiring
  U.S. citizenship or U.S. person status (not hedged ones); a hands-on
  duration over two years ("8+ years of hands-on FPGA designs"); listings
  placed only outside the U.S. (`location.py`, unknown kept); PhD-only
  postings (`degree.py`, any other degree or "or equivalent" kept).
- **Fit** of a posting without a full description is floored at the median
  Fit of described postings in its title band (`title_only_floor`).
- Third-party paid listings are labelled with their publisher and offer a
  search of the employer's own site.

**The user's standing instruction for filters: do not remove the wrong
postings.** Every rule above was run against the live queue before deploying
and its removals read; a full audit found and undid about 80 wrong catches
(see "Reading every removal" in the bug log). A new rule should be measured the
same way -- build the queue with and without it on the VPS, read what it
removes, and let every doubt keep the posting. The audit and measurement
scripts were one-off and are not in the repository.

Open, waiting on the user: whether to send the postings these rules cannot
settle to a language model (paid API, cached per posting). Nothing is built;
the proposal is to count that slice first and quote a real cost.

Heredocs through the Bash tool turned `\b` into a backspace character twice
today; both were found and fixed. Write patches through files, and scan for
control characters before committing a regex.

# User-supplied domain exclusions - 2026-09-22 UTC (codex, not deployed)

Added all eight domains from the user's explicit list to the existing hard
domain blocklist: trabajo.org, bebee.com, experteer.com, jobsora.com, geebo.com,
higher-hire.com, nexxt.com and adviesvanspijk.nl. The list now has 21 distinct
entries including the prior 13 DOJ-seized domains. These eight are documented
as preference exclusions, without adopting the supplied fraud allegations.
Existing broader publisher patterns remain unchanged. Domain and subdomain
checks apply before paid keeps and when reading the Review queue. No deployment
or live measurement was performed. Fetched main remained d9aed44; no overlapping
remote work needed integration.
All 35 offline Review rules tests passed, including every configured domain,
subdomains, hard rejection before keeps, and hiding existing indexed rows.

# Evidence-backed recruitment blocklist - 2026-09-22 UTC (codex, not deployed)

The user explicitly chose reliable fraud evidence over excluding all third-party
sites. Added 13 DOJ-seized fake consulting recruitment domains, with the source
and limits in `docs/blocked-recruitment-domains.md`. Existing Trabajo, Advies
Van Spijk and Experteer preference blocks remain unchanged and are not labeled
proven scams. No blacklist was scraped from anonymous complaints.

`exclude_publisher_domains` is validated as lowercase DNS names and checked by
the shared `publisher_excluded` function before paid keeps and at Review read
time. URL hosts and domain-form publishers match exact domains/subdomains;
path/query mentions and unrelated suffixes do not. No durable records changed.
The worktree was fast-forwarded to fetched main `d9aed44` before editing.
All 134 offline tests passed (35 Review rules and 99 JSearch tests), covering
all domains and existing rows. No deployment, paid
requests, or production measurements were performed.

# Review UI: highest Fit first - 2026-09-22 UTC (codex, not deployed)

The user requested descending Fit. Review now defaults to highest Fit first
across the selected tab, with a selector for lowest Fit first or the original
Recommended order. Sorting occurs after search and before the 75-row display
limit. Equal scores retain server order; missing/nonfinite scores stay last.
Sorting a filtered copy preserves the original server queue for switching back.
Refresh and decision updates rerender through the same sorting function.

Node executed the actual filtering function against 161 fixture rows, covering
pagination, equal scores, missing scores, both directions, original ordering,
tab changes, search and source immutability. JavaScript syntax and 19 Review
payload tests passed. No browser visual verification or VPS deployment is
claimed. The user's uncommitted main-checkout edits were left untouched.
The complete merged-worktree suite passed: 584 discovered, 574 executed, ten
environment skips. Imports were pinned to this worktree's source.

Before editing, `origin/main` at `de12047` was merged into the Codex worktree,
retaining its description, queue, filtering and store fixes alongside the answer
bank. The live review page changes only after these assets are installed.
The later main commit `39bd8c5` was inspected before pushing; its filter changes
do not touch these UI assets and were not included in this tested tree.

# Qualcomm answer import and position restrictions - 2026-09-22 UTC (codex)

The user authorized importing the filled Chrome application and automatic
reuse of its known answers. The ignored workstation bank now holds 27 answered,
bound questions, with no pending mapping. Real values and the local import
report remain under `.local/autofill`; none are committed. No website answer
was changed and no application was submitted. Six values omitted from browser
text output were verified from visible screenshots, not inferred to be blank.

Two answers depend on the particular summer internship. Bindings can now require
a position ID. `observe`/`resolve` with missing or different position context
withhold those answers, even when automatic filling is enabled. The exact
matching position resolves all 27 local entries; SQLite integrity, source digest
and the two context rejection paths were checked locally. Seventeen focused
offline answer-bank tests pass. Final live reinspection was unavailable because
Chrome could list the tab but could not attach to it; earlier DOM/screenshot
observations are the import evidence. No persistent browser watcher was added.

The concurrent `main` changes through `de12047` were inspected and left intact;
this work stays on the standing Codex branch and is not deployed.

# Local reusable autofill answers - 2026-09-22 UTC (codex, not deployed)

Added `jobdisco.answer_bank` and the `job-answers` CLI. Canonical fields each own
one typed answer; observed headings link to fields rather than copying values.
New wording is recorded as pending, exact ordinary aliases can resolve, and
confirmed mappings remain scoped to site/section/control/options. Personal
questions default to per-use review. There is no browser watcher, form filling,
or submission in this change. The next integration is a Chrome form reader
calling `observe` and presenting pending mappings for confirmation.

Authoritative state is local JSON under a file lock with atomic replacement;
SQLite is refreshed after writes and is recoverable from that JSON. This is
separate from VPS application decisions. Back up the local JSON privately; the
VPS backup does not contain it. See `docs/answer-bank.md`.

Created the user's ignored workstation store at
`D:/Operation1million/.local/autofill`: 17 empty fields and seven text questions
observed in the Qualcomm application. Four headings resolve to fields with
missing answers; three address headings await mapping. No personal answer was
inferred or copied from the browser, and no external form was changed.

Sixteen focused tests cover synonym reuse, ambiguity, scope isolation, changed
options/negation, personal review, answer types, interrupted writes and derived
index recovery. Full offline suite: 569 discovered, 559 passed, ten environment
skips on Windows; imports were pinned to the Codex worktree. The user's separate uncommitted changes in the main checkout
were left untouched. Implementation is based on `bcfe953` in the Codex worktree.

# Codex's B68-B84 merged; the review page's empty state and slow decisions fixed - 2026-09-22 UTC

Codex's `79e44e2` (B68-B84) was screened and merged into `main`. One defect
was found in it by running it on the VPS as the backup user, not by reading it:
the new archive could not open the service account's lock file. Fixed; see the
bug log.

Reported by the user from the live page and fixed in the same commit: the
review page could show "All done for today" over hundreds of postings, and a
decision left the posting in the list until a full rebuild answered. Both are
in the bug log with what was measured.

R02, the B23/B27 residual and O10 from Codex's round 15 were fixed in the
commit after it, along with the soft title block now reaching direct boards and
the user's added title words; see the bug log. The backlog is postings still
open and undecided that were first seen more than three days ago -- not
expired -- and it was 18,620 because the queue has no score floor and direct
boards were never held to the soft block.

# B68-B84 fixed on codex; awaiting review, not deployed - 2026-09-21 UTC

Implemented all 17 findings from audits 13-15. The numbered mechanisms and
evidence are in the newest architecture bug-log entry. Historical audit
reproducers remain unchanged; new regression tests assert the corrected behavior.

The changes cover authoritative recovery snapshots and validation, interrupted
backup rotation, safe history-compaction publication, published source pauses,
validator error/empty/challenge handling, configuration and migration backups,
moving requisition history, monotonic seen import, interrupted event writes,
and Review cache invalidation after a filter edit.

Validation on the Windows worktree, with imports pinned to its `src`: 544 tests
discovered, 535 executed successfully and nine skipped. Skips require POSIX
process groups, `flock`, or a populated local index. Backup and compaction
regressions use temporary files and local Git remotes; compaction stubs `flock`.
All three changed shell scripts also pass `bash -n`. No provider calls, real
credit spending, VPS operations, or production lock-contention tests were run.

Operational changes to review before installation: workstation backups now
require Python locally and snapshot runtime ledgers from
`/opt/jobdisco/code/.local` (override with `JOBDISCO_VPS_STATE`). Compaction holds
the decision lock and uses a freshly fetched explicit push lease. See
`docs/vps-deployment.md` for the updated recovery contract.

`origin/main` was rechecked at `5e78ae814514115866532bf96f8397d0331354d2`.
The user checkout and deployment are unchanged. Merge/review the standing
`codex` branch before installing; pushing this branch deploys nothing.

# The first pass on the new code, and a Workday regression it exposed - 2026-09-21 UTC

The 11:38 UTC pass ran on `2f1f7be` and succeeded: suite green with no skips,
index rebuilt from the log, manifest written, pushed. Read from its journal and
the live index, not reasoned:

- **Eightfold's first full pass added 350 postings** -- Micron 129, Qualcomm
  153, Microsoft 68 -- against 0 to 7 a day on the incremental passes before it,
  and closed 540 that incremental passes never retire. Most of the 350 are
  presumably postings those passes had missed, which is B51 in production; some
  are that day's genuine arrivals, and the two were not separated.
- **Every Workday board stopped at 40 postings and reported complete.** A
  regression from this session's first round, explained in the bug log. The
  closure fuse held on all nine boards; one Workday posting was closed that day.
  Fixed and deployed in the commit carrying this section.
- Google closed 206 and gained 56 against a board listing 154 fewer postings
  than the day before, which is consistent with the board itself; the closed
  URLs were not checked against the live site.

Workday's missing postings come back on the next complete pass. That is 11:38
UTC tomorrow unless a pass is started sooner by hand.

# Deployed to the VPS, and B63-B67 - 2026-09-21 UTC

**The VPS was updated today** from `ef6d4b3`, the commit it had held since
before this session, to `72e93e0` at 09:27 UTC, and then to the commit carrying
B63-B67 before the 11:38 pass. Measured there, not reasoned:

- The full suite passed **on the VPS with no skips** -- 515 tests, including the
  flock-dependent backup tests that are skipped on Windows and had never run,
  and the check of the alternation against every title the live store holds.
- `job-store --migrate --rescore` ran under the collection lock: migration 006
  applied, 41,176 postings rescored in 2 minutes 9 seconds, **2,994 scores
  corrected**, and `--verify` passed for every day including the one the rescore
  wrote. That file and its manifest are left for the pass to commit.
- The review server restarted with the new code. A cold queue build took
  **28 seconds** on the live queue and a cached one 0.3 seconds. A decision used
  to cost two builds and now costs one, but one is still 28 seconds, which is
  the next thing worth making faster.

What the 11:38 pass will do differently, reasoned from the code:

- **Rebuild the index from the log**, because `data/config` changed and the
  pass rebuilds whenever its inputs change. Nothing is lost: the oldest posting
  in the live index was first seen 2026-09-17 and the oldest run file is
  2026-09-17, so the log holds all of it.
- **Read every Eightfold board in full**, since no full pass is on record yet.
- Commit the rescore's corrections along with its own day.

B63-B67, fixed in this commit, are in the bug log. B67 -- which ledger the
recovery branch rewinds -- was verified by reading the script, not by running
that branch.

Measured locally: 523 offline tests, exit 0, 8 skips on Windows.

# Store lifecycle, B58-B62 - 2026-09-21 UTC

Codex's eleventh audit, in `store.py`, fixed on `main`. Mechanisms and
reproducers are in the architecture bug log.

What changes in operation:

- **Every append now rewrites the day's manifest.** That is what keeps a day
  verifiable across UTC midnight. It costs one digest of the day file per
  source committed; on an ordinary day that file is small.
- **A large batch is written as several shards** instead of one oversized file.
- **Direct postings that took over a paid one keep the paid payload under
  `raw.jsearch`.** Rows already stored flat stay flat until their board lists
  them again; `job-store --rescore` does not restructure raw, it only rescores.
- **More descriptions are kept.** A teaser that was a record's only description
  is no longer dropped, so some postings will start being judged on text they
  were always sent.

One of my own test gaps is worth recording: the B61 test first checked only the
experience gate, not the review queue where the symptom is. Codex's reproducer
prints a literal `pending: 0` there, which is bookkeeping and not a measurement;
checking the queue directly showed the posting is pending again, and the test
now asserts that too.

Measured: 515 offline tests, exit 0, 8 skips on Windows; each new test red on
the code before it. Codex's reproducer completes against this tree and holds at
none of its defect assertions. Nothing collected, spent or deployed.

# Direct collection, B50-B57 - 2026-09-21 UTC

Codex's tenth audit, in `collector.py`, fixed on `main`. Mechanisms and
reproducers are in the architecture bug log.

**A correction first.** The fourth-round section below says a TI shell ETag
already stored "is cleared by the next complete pass". It was not: validators
were written with `COALESCE`, so a pass supplying none kept the old one, and a
VPS with a stored shell ETag went on answering 304 for the whole TI board after
the B26 fix was installed. That claim was reasoned and never tested. It is true
from this commit, with a test.

What to expect after installing:

- **Migration `006_source_full_pass`** adds `source_state.last_full_at`. It runs
  on the first `migrate`, which every pass performs.
- **The first pass reads every Eightfold board in full** -- Micron, Microsoft,
  Qualcomm -- because none has a recorded full pass yet. That pass is slower
  than an incremental one, at 2.5-3 seconds a request, once. From then on each
  such board is read in full at most a week apart, and incrementally back a
  week from its watermark in between.
- **Multi-page boards stop being conditional.** Any validator stored for a
  board that needs more than one page is cleared by its next complete pass, and
  such a board is read in full each time. That costs requests on boards that
  sent an ETag; it is the price of not trusting a validator for pages it never
  described.
- **More passes will report partial** where a record cannot be read or has no
  id to build a link from. That is the intended direction: those passes used to
  report complete and retire postings they had failed to read.

Measured: 509 offline tests, exit 0, 8 skips on Windows; each new test red on
the code before it. Codex's reproducer no longer holds at any of its nine
defect assertions, and all nineteen of its per-provider positive controls still
hold. No provider contacted, nothing spent, nothing deployed, and the
Eightfold full-pass cost above is reasoned from the configured interval, not
measured.

# Paid discovery, B44-B49 - 2026-09-21 UTC

Codex's ninth audit, all in `jsearch.py`, fixed on `main`. Before them, `main`
took `1aa8456` from another Claude session on `claude`: a decision confirmed
against the store's own aliases before it follows a posting across providers,
the review cache watching the WAL sidecar where a running pass's commits land,
and two `job-store` flags that answered the wrong question. It corrected a claim
of mine -- that a same-title replacement could not be told from a provider move
-- by finding that the store already records the difference.

Two things want doing after this is installed:

- **`job-store --rescore`.** Until now the phrase that found a paid posting was
  read as part of the posting, and stored relevance scores include it. The
  review queue's experience gate reads raw each time and is correct at once;
  the stored scores that order the queue and settle evidence titles are not,
  until they are recomputed. `--rescore` publishes what it corrects to the log.
- Nothing else. The backfill change costs one repeated page a day for a query
  whose last page carries an unreadable record, which is what an empty last
  page already costs.

Measured: 498 offline tests, exit 0, 8 skips on Windows. Each new test red on
the code before it. Codex's reproducer, run against this tree with every
assertion recorded rather than fatal, no longer holds at B44, B45 or B46; its
own bookkeeping for the defective path stops it there, and B47-B49 rest on the
tests above. No provider contacted, no credit spent, nothing deployed.

# A bug check: three defects, and the page run for the first time - 2026-09-21 UTC

A pass over the review path and the store's command line, on `main`. Mechanisms
and reproductions are in the architecture bug log.

Two of the three change what a reader sees. A posting that a board advertises
at an address where something else was applied to now reaches the review queue
instead of inheriting that application -- this is the instance of B27 that the
company-and-title restriction left open, and the evidence it now asks for is
the store's own identity table. And the review page can see a collection pass
while it is running: the index is read in WAL mode, where a commit lands in the
sidecar, so the cached queue was blind to the whole of a pass and Refresh said
nothing about it.

The third is smaller and entirely on the command line. `job-store --ranked 0`
printed nothing: the query behind it reads zero as no limit, the flag did not,
and the deployment note that used that form for a health check was getting the
summary line by accident -- it now names the command that prints the summary.
And `job-store --verify` against a restored copy of the log created an empty
index and died on it rather than reporting what it had just verified.

Measured separately, and a weaker claim than the rest: the three page defects
from the eighth audit were covered by contracts on the source because there was
no JavaScript runtime here. There is one now, and `app.js` was run under Node 22
with a jsdom document in `America/Los_Angeles`: the dates, the overtaken refresh
and the skip dialog's target all behave as the fixes claim. That harness needs
an npm install, so it is not in the suite and not in the repository; it is a
measurement made here, not something the suite will repeat.

Not measured: nothing was collected, spent or deployed, and none of this has run
on the VPS or against the production index. The B27 reproduction drives the real
`store.record_source`, so its identity rows are the ones a pass would write, but
the postings in it are synthetic.

Measured: 491 offline tests, exit 0, one skip (no collected database in this
checkout). Each new test was run against the code before its fix and failed
there with the symptom described.

# Equivalent optimizations - 2026-09-21 UTC

Seven, on `main`, each measured before and after and each held to the answer it
replaced. Details and numbers are in the architecture bug log.

What a reader should expect to notice: a decision in Review waits for one queue
build instead of two, and the click itself for none; a pass stores each board
as it finishes instead of in catalog order; a rebuild of a large day uses about
a tenth of the memory. Nothing about what is collected, kept, scored or shown
has changed, and the suite that says so is the same one as before.

One behavioural consequence worth stating: the queue is now cached against the
ledger's and the index's last-changed time plus the UTC date, so within a day
the three-day window drifts rather than moving continuously. A posting can stay
in the recent tab a little longer than it strictly should. It is in the backlog
either way, and any write to either file rebuilds immediately.

Measured here, medians: queue build 460 ms on 2,000 postings (now paid once per
decision, not twice); per-posting judgement 2.53 to 2.10 ms; `clean` 416 to 189
ms per 20,000 titles; rebuild peak 9.4 to 1.1 MB on a 4,000-posting day. The
equivalence digest over the judgement corpus is identical on both sides.

Not measured: none of this was run on the VPS, against the production index, or
in a browser. The two page changes -- a debounced search box and a remembered
description -- have no runtime here to run them.

Measured: 485 offline tests, exit 0, 8 skips on Windows.

# Ten more, across six files - 2026-09-21 UTC

Codex's eighth audit, B34-B43, on `main`. Mechanisms and reproducers are in the
architecture bug log.

Four change what the experience gate concludes, and they move in both
directions: a posting saying "five years of experience is not required" stops
being refused, one asking for prior internship experience stops skipping the
gate, and one whose requirement hid behind a slash in `RTL/FPGA` starts being
read at five years rather than two. A posting asking for an internship already
served is marked in the review page rather than filtered: an internship already
done is a qualification, and the mark is only there so the word can be seen for
what it is.

`clean_title` is now idempotent. It was not, which means the same posting could
be stored under two spellings depending on how many times it had been cleaned.

Three are in the review page's JavaScript -- dates a day early west of
Greenwich, an older refresh overwriting a newer queue, and a skip dialog filing
its reason against whatever happened to be selected when it was submitted.
There is no JavaScript runtime in this checkout, so those three are covered by
contracts on the source rather than by running it. That is a weaker claim than
the rest of this section and is marked as such in the bug log; Codex's harness
runs the script and is where the behaviour should be confirmed.

Measured: 480 offline tests, exit 0, 8 skips on Windows. Each new test that can
run was run against the code before its fix and failed there.

# Experience parser: three explicit requirements it could not read - 2026-09-21 UTC

B31-B33 from Codex's seventh audit, fixed on `main` directly after the merge
that took Codex's documentation. The mechanisms are in the architecture bug
log; four tests fail against the parser as it stood and ten pass on both sides.

This one changes what the review queue shows, and in the direction that hides:
a posting stating "5 years experience required, FPGA knowledge preferred", or
"3 years" under a Required heading, or "3-year" or "2.5 years", was reaching
the queue as though it stated no requirement at all. Those postings will stop
appearing. Anything already decided keeps its decision -- the ledger is
replayed, not recomputed -- so this affects the pending queue only.

Not measured: no estimate of how many live postings use these phrasings. The
audit says the same and calls them synthetic examples of explicit requirements,
not a claim about their frequency.

Measured: 465 offline tests, exit 0, 8 skips on Windows.

# Fifth review round: three of my own fixes were wrong - 2026-09-21 UTC

B27, B28 and B30 are defects in fixes made earlier in this session, found by
the review that followed them; B29 is in the export path the same session
repaired. All four are fixed, each with a test that fails against the code as
this session left it. The bug log carries them as their own entries, which is
where a fix that introduced a defect belongs.

- A decision no longer follows its posting across a provider change unless the
  company and title agree too. A retitled posting will come back as pending.
- The rejection lookup matches the requisition rather than the address. It is
  also the table's primary key: 860 ms to 0.86 ms on a synthetic 1,200
  postings and 12,000 seen rows, measured here, with no new index.
- `--export` writes a manifest for every day it wrote a file, including days
  holding only closures.
- `--rescore` appends to the log before committing the index, per batch. A
  failed append now leaves the index behind the log, which a later rescore
  repairs by itself, instead of ahead of it, which nothing could.

Measured: 455 offline tests, exit 0, 8 skips on Windows; each new test red
against the code before its fix, with the reported symptom. Reasoned, not
measured: nothing collected, spent or deployed, and nothing checked against the
production database.

# Fourth review round, and one withdrawal - 2026-09-21 UTC

Same branch and base (`claude`, `ef6d4b3`), uncommitted. B24-B26, plus the
withdrawal of B20 from the round below.

- The review queue now hides a posting whose latest paid pass rejected it on
  the posting's own terms, using the rejection already recorded in `seen_jobs`.
  It hides rather than refreshes: the stored description stays as it was.
- A TI board is persisted and reported under the provider the collector
  actually read (`oracle_cloud`), not the one the catalog names. This is what
  lets its postings close at all, so the first pass after it installs may
  retire TI postings that the board stopped listing some time ago. That is the
  backlog of closures the bug was suppressing, not a new closure event, and the
  closure fuse still applies to it.
- A `ti_careers` source keeps no ETag or Last-Modified validator, so it is read
  in full every pass. [Corrected in the B50-B57 section: until then this was
  false.] A stale shell validator already stored is cleared by the
  next complete pass. Whether the live shell serves an ETag at all has not been
  checked; the trigger was reproduced offline.
- B20 is withdrawn. `main.direct` already turns a pass holding rejected records
  into a partial one, so the store never retires what a pass failed to read;
  the reproducer that suggested otherwise called `Collector.run` directly. Both
  halves of that change are reverted, including the untitled-link change, which
  would have made any board carrying a text-free job link permanently
  incomplete -- and a board that can never be complete is a board whose
  postings can never be retired.

Measured: 447 offline tests, exit 0, 8 skips on Windows. Each new test was run
against the code as it stood before its fix and failed there, with the reported
symptom: the posting still in the queue, five open postings against a board of
four, and the shell's ETag held as the validator. The tests written to guard
against over-correction pass in both directions.

Reasoned, not measured: nothing collected, spent or deployed, and nothing
checked against the production database or the live TI site.

# Two further review rounds, fourteen more defects - 2026-09-21 UTC

Same branch and base as the section below (`claude`, `ef6d4b3`), uncommitted.
B10-B16 and B17-B23 from two further reviews. Each defect, its mechanism and
its reproducer are in the architecture bug log.

What changes behaviour rather than only reporting:

- The index and the day log now fail together. A source whose rows could not be
  appended is rolled back instead of committed by the seal, so a pass that
  cannot write its log stores nothing and advances no watermark.
- `--rescore` appends the scores that moved to today's log. A rescore of the
  whole store will add one record per changed posting; on the live index that
  is tens of thousands of small records in one day file, which the existing
  shard threshold handles but which a reader should expect to see.
- A second row landing on a URL another row in the same batch claimed now
  displaces it instead of merging with it. One row per URL either way; what
  changes is which posting's description and identity the survivor carries.
- Renesas sitemap postings now take the requisition from their URL, so a
  retitled or relocated posting is the same row rather than a withdrawal and an
  arrival. Only Apple and Renesas take an id from a URL.
- An untitled job link and an Eightfold position with no link of its own are
  now malformed records rather than silently absent ones, so the pass reports
  itself incomplete instead of letting the store retire what it failed to read.
- The review server answers requests in threads, and `/api/job` refuses to
  illustrate a decided group with a description belonging to a different
  requisition. `review_static/app.js` sends the group id and renders that case.
- `backup-from-vps.sh` now verifies each run file against its manifest digest,
  except for the day still being written.
- The conditional probe is used only on GET boards; a Workday board reads in
  full instead of being probed with a method it refuses.

Measured: 438 offline tests, exit 0, 8 skips on Windows. Every new test was run
against the code as it stood before its fix and failed there; the tests written
to guard against over-correction pass in both directions. `bash -n` passes on both
backup scripts, and the corrupt-copy and still-being-written cases of
`backup-from-vps.sh` were driven end to end under Git Bash.

Reasoned, not measured: no collection ran, nothing was spent, nothing was
deployed, and no claim here was checked against the production database. The
review page's JavaScript change was not executed -- there is no JavaScript
runtime in this checkout, and the page's own contract test reads it as text.
The rescue-pull digest check has not been run against a real VPS copy, and the
threading change has not been exercised by a real browser.

# Nine reviewed defects, fixed offline - 2026-09-20 UTC

On `claude`, base `ef6d4b3`, uncommitted at the time of writing. Reviewed
findings in `collector.py`, `experience.py`, `collection_policy.py`,
`validate_sources.py` and `deploy/vps/backup-applications.sh`. Each defect and
its reasoning is in the architecture bug log; each has a test that fails on
`ef6d4b3` and passes here.

Three of them change when a direct pass may call itself complete -- the cap no
longer reports a complete board, an empty page no longer outranks the count the
board just stated, and a stated zero is read as the count it is. Completeness
is what permits the store to retire postings, so these change what gets closed,
in the conservative direction in the first two cases and the permissive one in
the third. The closure fuse in `record_source` is unchanged and still applies.

One earlier test was deliberately changed rather than worked around:
`EmptyBoardTests.test_a_blank_later_page_just_ends_pagination` asserted
'complete' for a board that stated 99 postings and listed one. It keeps its
purpose with a self-consistent fixture, and the contradicting case is now its
own test asserting the opposite verdict. Nothing else asserted the old
behaviour.

Measured: 417 offline tests, one failure resolved to that test, then exit 0
with 8 skips on Windows. The backup script was additionally driven end to end
under Git Bash with a lock stub, because its own test needs flock and skips
here: the pre-fix script left the remote without the commit after a failed push
and a restored remote, and the fixed script pushed it on the next tick with no
new decision. `bash -n` passes.

Reasoned, not measured: no collection ran, nothing was spent, nothing was
deployed, and no claim here was checked against the production database. The
three completeness changes have not been observed against a real board, and the
robots.txt ordering change has not been observed against a live host.

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
