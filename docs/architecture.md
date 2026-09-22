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

### Local personal answer preparation

`answer_bank.py` owns a separate workstation-only autofill knowledge store:
canonical fields and one answer per field, exact built-in aliases, scoped
observed questions and confirmed bindings. Its authoritative `.local/autofill/
answers.json` is atomically saved under a lock; `answers.sqlite` is a derived
view refreshed after writes and can be rebuilt. This is not application decision
state, does not write the VPS ledger, and is never read by job-index rebuilds.
It emits no personal-review answer automatically and performs no browser writes.
Position-restricted bindings withhold answers unless the caller supplies the
matching position ID; passing no context cannot silently reuse a prior cycle.
See `docs/answer-bank.md` for matching, storage, backup and extension contracts.

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
  internship or publication date. This is the server's recommended order. The
  Review UI defaults to the user's requested highest-Fit-first display and
  offers Recommended order to restore the server ordering without rescoring.
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

### Eight explicit user domain exclusions, 2026-09-22 UTC

The user subsequently supplied trabajo.org, bebee.com, experteer.com,
jobsora.com, geebo.com, higher-hire.com, nexxt.com and adviesvanspijk.nl as
hard exclusions. All eight now share the exact host/subdomain filter with
the 13 enforcement-backed domains. Their reason is user preference, not a
new fraud finding. Earlier broader text patterns remain unchanged. Offline
regressions cover all 21 entries in paid filtering and existing Review rows.

### Evidence-backed recruitment domain exclusions, 2026-09-22 UTC

The user limited new blocks to reliable fraud evidence. Thirteen recruitment
domains named in DOJ's June 10, 2026 seizure announcement now live in
`exclude_publisher_domains`, separately from earlier preference text patterns.
The existing paid filter and Review queue share exact host/subdomain matching;
domain mentions in paths and queries do not cause rejection. Existing broader
preference exclusions are unchanged. See `docs/blocked-recruitment-domains.md`
for the complete list, official source, evidentiary limits and offline checks.
No deployment or production hit count is claimed.

Newest first. Each entry is what was wrong, how it showed, and what settled it,
so that a later reader can tell whether a decision was reasoned or measured.

### Reading every removal: the wrong catches in today's rules, 2026-09-22 UTC

At the user's request ("don't catch the wrong ones"), the queue was built on
the VPS with each of today's rules switched off and compared with the live
one, and every posting a rule removed was attributed and read. Nothing was
removed without a rule to account for it. By rule:

- **Abroad, 5,404: no wrong catch.** Every location with a U.S.-looking token
  (204) and every one placed by a city alone (79) was read; the ambiguous
  ones -- Cadence's "DUBLIN" and "CORK 01", Apple's "Location Vancouver" --
  are Ireland and British Columbia.
- **Blocked sites, 34: none wrong.** All BeBee, Trabajo.org or Advies Van Spijk.
- **U.S. person, 121: two wrong of 40 distinct wordings.** "ITAR projects,
  which may require U.S. citizenship" and Microsoft's "If the role requires
  US citizenship, as indicated in the job description" state no requirement
  for the posting. A match now does not count when its sentence puts if, may,
  might, could, where, whether or should before it. Wärtsilä's "U.S. and
  Puerto Rico positions must be a U.S. citizen ... [not] F-1, H-1B" stays.
- **Principal and lead, 2,221: five wrong.** "(Up to Principal Level)" and
  "Lead & IC Engineers" hire across levels; both patterns now leave them.
- **Soft block, 4,120: chip work in four places.** Power-management firmware
  and chip power analysis (firmware, embedded, subsystem and "power analysis"
  now name hardware); semiconductor product engineering, development and test
  (the product word now means management and design only); the chip senses of
  front end and back end ("GPU Front-End Methodology", "Digital Backend
  Flow"); and EDA, 3D-IC, circuit and memory software. GPU and CPU application
  software, analog, RF and PCB stay blocked as chosen.
- **Less related, 4,324: sorted, not removed, but mis-banded.** Timing design,
  gate-level, EM/IR, CAD/EDA, layout, circuits, packaging and "Design
  Engineering" openings were in the last band; `ranking` now knows them.

Measured with this code on the live queue before deploying: 79 postings
restored, every one read. Reproducer: `AuditedWrongCatchTests`.

### Postings located only abroad, and a title's Fit without a description, 2026-09-22 UTC

Both asked for by the user.

- **Located only outside the U.S.** `location.country` places a location
  string as U.S., abroad, or unknown, in every format the live queue holds:
  "US, WA, Seattle" and "IN, KA, Bengaluru" (country code first), "Bangalore,
  India", "..., United States of America", Apple's "Location Cupertino", a
  bare "Austin, Texas". A U.S. sign wins -- a written-out state, "United
  States", a U.S. city, a state code that is not also a country code -- so
  "Dublin, California", "Paris, TX" and a multi-city string naming Austin stay.
  Blank, "2 Locations", "Remote" and anything unplaced are unknown and kept.
  The queue drops a listing only when it is placed abroad; a requisition also
  offered in the U.S. keeps that listing. Measured on the live queue before
  deploying: of 12,647 listings, 5,752 placed in the U.S., 5,446 abroad and
  1,449 unknown (826 blank); 5,404 groups were located only abroad, 183 of them
  in the recent tab. Reproducers: `tests/test_location.py` and
  `QueueRulesTests.test_a_posting_located_only_abroad_is_hidden`.
- **No description no longer means a low Fit.** Most boards publish none, and a
  posting was scored on its title's words alone: "Design Verification Intern"
  scored 12. A posting whose description is absent or shorter than
  `min_description_chars` now scores at least `title_only_floor` for its
  title's band -- the median score of postings in that band that do publish a
  full description, measured on the live index: 55, 50, 62, 21 and 0, where
  the same bands without one had medians of 29, 12, 21, 0 and 0. A floor only:
  a higher score is kept, an excluded title still scores 0, and an RF evidence
  title is not floored, since its name is what may not be trusted. Stored
  scores change on `job-store --rescore`. Reproducer: `TitleOnlyFitTests`.

### One review list, less related last; hands-on durations, 2026-09-22 UTC

- **The review tab is one list to work down**, at the user's request: postings
  new in the last 72 hours, then the backlog, then everything less related from
  either, each section sorted by the menu and headed by a divider. "Less
  related" is set by the server: a title in the last band *and* a Fit under
  `min_confidence`. The band alone would have buried "SDC, Synthesis and STA
  Engineer" (Fit 69); the score alone would bury every board that publishes no
  description. The Backlog tab is the backlog alone, less related last.
- **"8+ years of hands-on FPGA designs" was read as no requirement.** A
  duration counted only beside "experience", "professional", "industry", a
  required marker or a degree. `HANDS_ON` now admits the work named right after
  the duration -- hands-on, practical, proven, or a verb of the trade --
  capped at 15 years and not after "within" or "in", so company boilerplate
  and deadlines stay out. Measured against every open posting in the live
  index: 3 more hard passes, each a real requirement ("5+ years building ...
  distributed systems", "10+ years designing ... boards"). Checked in the same
  run: the 317 postings passed on a requirement over 15 years are all real
  requirements, not a company's age. Reproducer: `HandsOnDurationTests`.

### Blocked job sites, 2026-09-22 UTC

At the user's request, listings republished by experteer.com, Trabajo.org and
Advies Van Spijk are a hard pass (`excluded_publisher`) in the paid filter and
the review queue. `exclude_publisher_patterns` in the config is matched against
the link's host and the publisher JSearch names, so either one is enough. The
live index held 25 open Trabajo.org postings, one from Advies Van Spijk (an
Intel listing attributed to "成都intel") and none from experteer.com. Reproducer:
`QueueRulesTests.test_a_blocked_job_site_is_hidden_by_host_or_by_publisher`.

`lead` joined `senior`, `sr` and `principal` as a level excluded outright, at the
user's request the same day. It is the word only: "Leadership Development
Program" and "Leading-Edge" are untouched.

"trabajo" is blocked wherever it appears, also at the user's request: in a
title, and anywhere in a posting's link -- the site blocklist now reads the
whole link rather than its host, which caught an Amazon posting whose address
contained the word.

### Third-party listing links, 2026-09-22 UTC

The user asked why a posting linked to interviewsense.org. A paid listing's
link is wherever Google Jobs found the posting. Measured on the live index:
every one of the 1,033 open JSearch postings has exactly one apply option and
none is direct -- LinkedIn 264, JobLeads 222, BeBee 49, ZipRecruiter 48 -- so
there is no employer link to prefer. What the payload does carry is the
publisher and the employer's website. The queue now passes both for a
non-direct paid listing, and the page shows "via <publisher> (third-party
site)" and a "Find on company site" search of the employer's domain for the
exact title. Checked in a browser against the local index on a Keysight
listing published by InterviewSense. Reproducer:
`QueueRulesTests.test_a_third_party_listing_says_who_published_it`.

### A softer tier for the new title words, and a U.S.-person hard pass, 2026-09-22 UTC

Both asked for by the user, after the previous entry's filter went live.

- **The new title words took silicon roles with them.** Power, product,
  manufacturing and the rest were added to the soft block, which a title
  escaped only by carrying a keep pattern or a strong term. Measured on the live
  queue, that dropped 38 early-career groups -- "AI GPU Power Architect - New
  College Grad", NAND and DRAM product engineering internships, "Product
  Validation Intern" -- with the supply planners it was aimed at. They are now
  their own group, `function_title_patterns`, and a title is kept when it names
  the hardware it is about (`hardware_title_terms`) and an engineering role or
  an early-career opening (`role_title_terms`). "CPU Power Engineer" stays;
  "Business Operations Analyst, Processor" does not. The older soft block --
  software, analog, RF, quality and the rest, the user's earlier choices -- is
  unchanged. Measured with this code on the live queue: all six probed titles
  back, backlog 12,996 to 13,038.
- **U.S. citizenship or U.S. person status is a hard pass.** Read from the
  structured description by `jsearch.us_person_required` in both the paid
  filter and the queue, with the patterns in the config beside the title rules.
  Drafted against the live index: the first patterns matched 662 open
  postings, all 25 sampled real requirements; the misses sampled among the
  other mentions added "requires that the candidate selected be a US Citizen",
  "must be a (i) U.S. citizen" and GovCloud's "restricted to ... who are U.S.
  Citizens". Left alone on purpose: an offer "contingent upon ... citizenship
  ... or ability to obtain prior license approval", a definition of who counts
  as a U.S. person, EEO lines about citizenship status, and "no U.S.
  citizenship required". It removes 122 groups from the live queue, 7 of them
  early-career -- Blue Origin's "ASIC Engineer - Early Career", SpaceX's
  "Silicon Engineering Internship/Co-op". Reproducers: `UsPersonTests` and
  `QueueRulesTests.test_a_us_person_requirement_hides_a_direct_posting`.

### R02, the B23/B27 residual, O10, and the soft block on direct boards, 2026-09-22 UTC

The three follow-ups Codex's fifteenth audit left open, and a filter change the
user asked for after seeing an 18,620-posting backlog.

- **R02: descriptions the review page did not look for.** `/api/job` read six
  top-level keys. Measured on the live index, most direct boards store no
  description at all -- Eightfold, Workday, Apple, Google and Oracle keep the
  listing only -- and nothing here can show what was never collected. What was
  stored and missed: Phenom's `descriptionTeaser`, the only description on
  1,280 of its 1,314 open postings; `content`, Codex's case; and the paid
  listing's text kept under `raw['jsearch']` when a direct posting took one
  over. `job_text.display_description` now reads them, current payload first,
  and says which kind it returned; the page labels an excerpt and a discovery
  listing as such. `store.slim` reads the same two field lists, so the log and
  the page cannot disagree about what a description is. Reproducers:
  `DescriptionTests` in `tests/test_review_description.py`.
- **B23/B27: the description view trusted the page.** Whether a decided posting
  moved provider or was replaced was judged from the provider and title the
  page sent, with no alias check, so a same-titled replacement's prose was shown
  under an application made to the old requisition. The server now takes the
  decided job from its own queue's snapshot and applies the queue's rule --
  same requisition, or a provider change with company and title agreeing and the
  decided requisition still among the address's aliases -- through
  `applications.describes_decision`. The page no longer sends provider or title.
  Reproducers: `test_a_replacement_under_the_same_title_is_not_shown_as_the_decided_job`
  and its control, `test_a_posting_that_only_changed_provider_still_shows_its_description`.
- **O10: every checkpoint re-read the whole day.** An append re-described the
  day, and describing it hashed and decompressed the entire file: Codex counted
  420 records visited to log 40 over twenty checkpoints. The append now extends
  a cached digest and count by exactly what it wrote. The cache is trusted only
  while the file's size and mtime are what that write left; another writer, a
  truncation after a failed write and a shard rollover each force a full read.
  Twenty checkpoints now read the file once. Reproducers:
  `CheckpointManifestTests`, which also check each of those three cases against
  a fresh scan. They error rather than fail on the old code, which has no
  `_scan_file`; the reduction on the old code is Codex's measurement.
- **The soft title block never reached direct boards.** `reject_title_patterns`
  ran only in `rejection_reason`, on paid results as they arrived. A direct
  board's posting was held to the hard exclusions alone, and the queue has no
  score floor -- it cannot have one, since a board with no descriptions scores
  on the title and 15,694 backlog groups below the floor include "Design
  Verification Intern". So the backlog carried 2,855 groups the existing rules
  already named: software, analog, quality, recruiting, accounting. The queue
  now applies the soft block through `jsearch.title_blocked`, which the paid
  filter uses too, and which lets a title through when it also names the trade
  (a keep pattern or a strong term). RF evidence titles keep their exception.
- **At the user's request**, `principal` is a hard exclusion, a level like
  `senior`, and power, product, supply, manufacturing, mechanical, magnetics,
  project and program management and operations join the soft block. Two tests
  that held principal as an allowed individual-contributor level were changed
  to match. Measured against the live queue before deploying: the backlog goes
  from 18,620 to about 12,995 and the recent tab from 530 to 427. Among what
  goes are 21 early-career titles caught by `product` -- "Intern Position
  (Custom IC Product Group)", "Hardware Products Early Career Rotation Program"
  -- and one by `power`, "AI GPU Power Architect - New College Grad".
  Reproducers: `SoftBlockTests` and
  `QueueRulesTests.test_the_soft_block_reaches_direct_boards_in_the_queue`.

### An empty review page, a 28-second decision, and a backup that could not read, 2026-09-22 UTC

Two reported by the user from the live page, one found screening Codex's B68
fix on the VPS before merging it.

- **The page said "All done for today" over a queue of 532.** The page starts
  from an empty placeholder state until `/api/queue` answers, and a tab click
  or a keystroke in the search box rendered that placeholder: zero to review,
  zero applied, zero skipped, and the all-done message. The server was holding
  532 recent and 18,619 backlog groups at the time, measured over the same
  tunnel. The page now draws nothing until the first queue has arrived, and a
  first load that fails says so where the jobs would be. Measured in a browser
  against a local server: a tab click during the load leaves "Loading jobs...".
- **Why the load was slow enough to click through.** The cache key included
  the `-wal` sidecar's timestamp. Every reader that opens the index recreates
  an empty sidecar and moves that timestamp -- measured on the VPS, a 0-byte
  `-wal` touched at 03:03 UTC with no pass running -- so the cache was thrown
  away by ordinary reads and the next visitor paid a full build, about 28
  seconds. An empty or absent sidecar holds no commit and now has no
  fingerprint; a non-empty one still invalidates. The server also rebuilds in a
  background thread when the inputs change, so the first request after a pass
  finds the queue built.
- **A decision cost a full rebuild before the posting left the list.** The
  ledger is part of the cache key, so each Skip or Mark applied made the next
  queue request -- the page's own refresh -- a cold build, and the posting stayed
  where it was until that answered; the next decision waited behind it. The
  server now moves the decided group in its cached queue when the ledger is the
  only input that changed, and builds in full otherwise; a test holds the moved
  queue equal to a full replay of the same ledger. The page moves the posting
  into Applied or Skipped the moment the save succeeds and selects the next
  one. Measured locally: 66 ms for Mark applied, 485 ms for Skip. Moving a
  posting back to review is still decided by the full build, because whether
  it belongs in the recent tab or the backlog is the server's call.
- **Codex's B68 archive failed as the backup user.** `backup-snapshot.py` took
  the decision lock by opening `applications.lock` for append. The workstation
  backup runs as `ubuntu`, which can read the data checkout but not write that
  file, owned by `jobdisco` with mode 644. Run on the VPS before merging: every
  archive stopped with `Permission denied` after the SQLite snapshots. `flock`
  needs no write access, so an existing lock is now opened read-only on POSIX.
  Reproducer: `BackupTests.test_a_lock_file_the_backup_user_cannot_write_is_still_honoured`,
  which runs on the VPS and skips on Windows and as root.
- **...and could not open the index as the backup user either.** After the
  deploy restarted the review server, nothing held the index open, its `-wal`
  and `-shm` were gone, and a read-only connection as `ubuntu` failed with
  "attempt to write a readonly database": a WAL database needs a `-shm`, and
  `ubuntu` cannot create one in that directory. The run before had succeeded
  only because a reader happened to be holding the sidecars. This predates
  B68 -- the old one-line snapshot opened the index the same way. The helper
  now runs as the service account, which owns every file it reads; run that
  way on the VPS, the archive carried all six files and every pipe stage
  exited 0. Reproducer: `BackupTests.test_the_snapshot_runs_as_the_service_account`.

### B68-B84: recovery, validation and replay, 2026-09-21 UTC (merged and deployed 2026-09-22)

Audits 13-15 remain historical reproductions. The following fixes have offline
regression coverage in `tests/test_backup.py`, `tests/test_compaction.py` and
`tests/test_audit_recovery.py`:

- **B68:** Workstation backups now snapshot the authoritative runtime quota and
  source-pause databases, including committed WAL contents, instead of stale
  published copies. The index is snapshotted first; decisions are copied under
  their own lock. Database snapshots are independently consistent, not a single
  transaction across all files. A stale published quota versus a newer live
  WAL reservation was tested.
- **B69:** Backup validation now requires Python, checks both operational SQLite
  schemas and integrity, parses application events, and decompresses/parses the
  full seen snapshot. Corruption of each operational file preserves both good
  generations. An empty decision ledger is accepted.
- **B70:** Failed backup installation restores `current`; startup recovers a
  leftover `previous.tmp` before staging cleanup. Repeated installation failure
  preserves both generations and the last successful pull marker.
- **B71:** History compaction fetches and compares the actual remote tip and
  pushes with an explicit lease for that hash. Both an already published remote
  change and a change after the fetch are tested to survive.
- **B72:** Compaction constructs its candidate in a temporary worktree and changes
  the live checkout only after push acceptance. Rejected push, normal pull and
  successful retry were tested with disposable local bare repositories. The
  script also holds the application-decision lock alongside the collection lock;
  these tests stub `flock` on Windows and do not prove Linux lock contention.
- **B73:** Before collection, merge published source pauses into the local ledger
  using the later `retry_at`, preserving the reason belonging to that deadline.
  The merge is tested offline; scheduled-pass invocation is checked from code.
- **B74:** Request construction is inside the validator's per-source exception
  boundary. A malformed source becomes a failed report row and subsequent
  sources are still processed.
- **B75:** Empty catalogs produce a header-only validation report, written to a
  temporary file and installed after completion, instead of indexing `rows[0]`.
- **B76:** Apple validation extracts nested anchor text through BeautifulSoup;
  a normal nested job-title link is recognized.
- **B77:** Challenge detection uses visible text and explicit challenge elements,
  shared by validation and collection. An Akamai script URL alone does not pause
  a source.
- **B78:** HTML challenges are checked before provider-specific link extraction,
  so a challenge page containing a job link still records a durable pause.
- **B79:** All seven pattern groups must be arrays of strings before regex
  compilation. Scalar, table and mixed-value groups fail at configuration load.
- **B80:** Pre-migration query-catalog backups include a hash of the canonical
  source database path. Migrating two distinct databases no longer collides at
  one fixed backup filename; both original backups remain available.
- **B81:** When an old address is reused during a requisition move, capture the
  moving identity's row before processing either batch order. Carry its first
  seen time, publication metadata and description to the new address and log a
  full changed snapshot. Both orders and rebuild preserve that history without
  giving it to the replacement requisition.
- **B82:** Seen-snapshot import retains the earliest first observation and only
  updates disposition/metadata from a strictly newer observation. An older
  accepted snapshot cannot undo a newer rejection during an in-place rebuild.
- **B83:** Interrupted multi-member appends describe the surviving primary
  fragment (or remove an empty fragment) before propagating failure. An injected
  second-member fsync failure, verification, next-day retry and rebuild are
  tested. This does not promise successful recovery writes on a persistently
  failing disk.
- **B84:** Review's queue cache includes the active filter fingerprint. A rule
  edit with unchanged ledger/index files rebuilds the queue on the next request;
  tested through loopback HTTP.

No provider requests, paid credits, VPS execution or deployment were involved.

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

### Workday stopped at forty postings, 2026-09-21 UTC (found in production, fixed and deployed)

A regression from this session's own first round, found by reading the journal
of the first production pass on the new code, not by any audit or test.

- **What happened.** Every Workday board returned exactly 40 postings and
  reported `complete`: Cadence, Intel, Lattice, Marvell, NVIDIA, NXP, Samsung,
  SiFive and Silicon Labs, against the 608, 612, 142, 206, 2,000, 789, 692,
  123 and 80 postings the store held open for them. Workday states its real `total` on the first page and
  `total: 0` on every page after it. The round-one fix made a stated zero count
  as a count, so the second page -- forty postings in -- satisfied
  `offset >= total` and ended the board.
- **What it cost.** The closure fuse caught all nine: each would have retired
  50% to 99.7% of its open postings, and none did. Measured in the live index
  afterwards, one Workday posting was closed that day, at Altera. What was lost
  is the day's new postings and edits beyond the first forty on each board,
  which the next complete pass collects. Postings on a Workday board small
  enough that forty was over three quarters of it would not have tripped the
  fuse; the live index shows none were closed.
- **The fix.** A page that lists postings is not stating that the board holds
  none, so a zero on such a page is set aside and the last credible total
  stands; completion is judged against that. A board that is empty and says so
  is still complete. Reproducer:
  `CollectionTests.test_a_workday_board_is_read_past_its_second_page`, which
  fails on the deployed code with exactly the production symptom, 40 of 45.
- **Why it got through.** The round-one test exercised a stated zero on a first
  page only, and the fixture every Workday test uses states the same total on
  every page -- which is not what Workday sends. A test fixture that is more
  consistent than the provider it stands for hides exactly this.

### Quota, pacing and recovery, B63-B67, from Codex's twelfth audit, 2026-09-21 UTC

Five across `jsearch.py`, `jsearch_access.py`'s callers, `ledger_guard.py`,
`collection_policy.py` and `daily-pass.sh`. B63-B66 each have a test red on the
code before it, and Codex's reproducer no longer holds at any of their
assertions. B67 is different in kind: its defect is which ledger a shell branch
rewinds, and neither this suite nor Codex's reproducer drives the pass script
into that branch. It is covered by a contract on the script's text and a test
of the rewind against real ledgers -- the wiring was read, not run.

- **A page answered after the cycle rolled finished the new cycle's sweep.**
  `resume_page` and `advance` each asked for the billing period at the moment
  they ran, so a page requested at 23:59:59 on a cycle's last day and answered
  two seconds later wrote its progress into the new cycle and marked it done.
  A sweep now captures its period once, reads and writes its cursor under it,
  and stops when the period changes under it: the page numbers in hand belong
  to the sweep that ended, and the new one starts at page one on its own run.
  Reproducers: `DiscoveryTests.test_a_page_answered_after_the_cycle_rolls_belongs_to_the_old_sweep`
  and `...test_a_sweep_stops_when_the_cycle_rolls_under_it`.
- **The startup ledger check compared the billing period only.** The budget
  day and the billing cycle turn over at different moments, deliberately, so a
  budget day can hold spend from the previous cycle. A local ledger that had
  lost it compared zero against zero on the new cycle and was allowed to spend
  the day's allocation again. The check now requires the local ledger to know
  the current budget day's spend as well; a ledger ahead on both, as a failed
  push leaves it, still passes. Neither clock moved. Reproducer:
  `BudgetDayAcrossTheCycleTests`.
- **Another crawler's Crawl-delay was applied to this one.** The largest delay
  anywhere in robots.txt was taken, so a host asking this collector for two
  seconds and another bot for six hundred got six hundred. Groups are now read
  as robots.txt defines them: the group naming this crawler, else `*`, never
  another's. Measured on the same file: 600 seconds before, 2 after.
  Reproducer: `CollectionPolicyTests.test_the_delay_is_the_one_given_to_this_crawler`.
- **A throttled robots request did not pause the source.** Only a 200 was read;
  a 429 became "no delay declared" and the next board page went out. A 429 on
  robots.txt now pauses the source for at least 15 minutes or its Retry-After,
  as a 429 anywhere else does, and is not cached so a later run asks again.
  Reproducer: `CollectionPolicyTests.test_a_throttled_robots_request_pauses_the_source`.
- **Recovery rewound the published ledger, not the one the next pass reads.**
  When collected history fails verification, the pass rewinds unpublished
  cursor progress before publishing the ledger. It did so on the copy in the
  data repository, while the runtime ledger under `$CODE/.local` -- the one the
  next pass on this machine uses -- kept the progress, so the next sweep treated
  queries as finished whose results were never published. Both are rewound
  now, credits and cooldowns kept in each. Reproducers:
  `UnpublishedProgressTests`, one reading the script and one rewinding real
  ledgers.

### Store lifecycle, B58-B62, from Codex's eleventh audit, 2026-09-21 UTC (not deployed)

Five in `store.py`. Each has a test red on the code before it. Codex's own
reproducer, run to completion against this tree with only one line of its
defect-path bookkeeping skipped, no longer holds at any defect assertion, and
its controls -- replay equal to the live store, a direct description passing on
its own -- still hold. B62 in particular is shown there through
`collector.main` with an injected clock, which this suite's store-level test
cannot do alone.

- **Slimming deleted the only description some records carry.** `description_short`
  and `descriptionTeaser` were in `DROP_FIELDS` as truncated renderings "of a
  description we keep in full" -- true only when there is one. Where a record
  had nothing else, its requirements went with them, before the log was
  written, so no replay could restore them. A teaser is now dropped only where
  a full description stands beside it. Reproducer:
  `StoreLifecycleTests.test_the_only_description_is_kept_whatever_it_is_called`.
- **A moved requisition survived or not depending on batch order.** With A
  moving from `/shared` to `/new-A` and B taking over `/shared`, A's alias
  pinned it back onto `/shared` if it came first, and B then displaced it there
  -- a complete pass that lost A, durably, including through a rebuild. The
  batch's own addresses are now read before any alias is followed: a posting
  whose old address the batch lists under another requisition keeps the
  address it is listed at, and the stale alias goes. Reproducers:
  `StoreLifecycleTests.test_a_moved_requisition_survives_whichever_order_the_batch_lists_it_in`
  and `...test_the_replay_keeps_both_as_well`.
- **One batch could make a run file of any size.** The shard limit was checked
  against what was already on disk, never against the batch arriving, and not
  at all on an empty day. A batch is now split until each part fits; a single
  record larger than a shard is written alone, because a record is never split
  across files. A failure part-way through a split batch leaves the log ahead of
  the index, the direction a rebuild repairs. Reproducer:
  `StoreLifecycleTests.test_no_run_file_outgrows_a_shard_because_one_batch_was_large`.
- **A superseded paid description overruled the board's current one.** When a
  company's own board took over a posting first found through the paid
  provider, the two payloads were merged flat, and twice: once while preparing
  the batch and once more against the stored row while writing it. The paid
  "5 years" sat beside the board's "2 years" as though both were current, and
  the gate took the larger. The paid payload is now kept as provenance under
  `jsearch`, as the reverse direction already did, and the experience gate does
  not read it. Relevance still does, deliberately: a superseded requirement can
  only refuse a posting wrongly, while extra vocabulary can only add. Reproducer:
  `StoreLifecycleTests.test_the_board_that_replaced_a_paid_posting_is_the_posting`,
  which checks the review queue as well as the gate.
- **A day that ended mid-pass was left without a manifest.** The manifest was
  written once, at the end of a pass, and a day seals when the clock passes it,
  so a pass that appended before UTC midnight and finished after could not
  describe the file it had written -- not at completion, not on the failure
  path -- and the day failed `verify` and refused to replay. Every append now
  describes its day as part of the append, with the seal decided once, when the
  append begins; a pass whose day has sealed by the time it finishes leaves that
  description as it is and does not reopen the day to add its summary. Neither
  clock moves. Reproducer:
  `StoreLifecycleTests.test_a_day_that_ends_mid_pass_is_left_verifiable`, and
  Codex's collector-level case.

### Direct collection, B50-B57, from Codex's tenth audit, 2026-09-21 UTC (not deployed)

Eight in `collector.py`, and the direct-intake half of B45. Each has a test red
on the code before it. Codex's own reproducer, run against this tree with its
defect assertions recorded rather than fatal and the bookkeeping written for
the defective path skipped, no longer holds at any of its nine defect
assertions -- and every one of its nineteen positive controls, one per JSON
provider and one per HTML extractor, still holds.

- **HiBob prepared its batch outside the per-record boundary.** Every record's
  URL and location were built before any record reached `add`, so one without
  an id raised a KeyError that failed the source and lost every valid posting
  beside it. Records are now prepared one at a time, and one without an id is
  a malformed record. Reproducer:
  `CollectionTests.test_a_hibob_record_without_an_id_costs_itself_and_not_the_batch`.
- **Eightfold's incremental pass skipped what its dates did not announce.** A
  `since` pass stopped at the first posting published before the last run,
  which is only safe if a posting's stated date moves when it appears or
  changes. It need not: a posting can reach the index after its stated date,
  and an edited one keeps the date it was published under. Both were invisible
  to every incremental pass after, each reporting complete. An incremental pass
  now reads back `RECONCILE_DAYS` (seven) before its watermark, and a board
  whose last full pass is older than that, or unknown, is read in full. That
  needs to know when the last full pass was, which `last_success_at` cannot
  say because every incremental pass moves it, so migration `006` adds
  `source_state.last_full_at`. Reproducers in `IncrementalReconciliationTests`.
- **A first-page validator was taken to speak for the whole board.** The
  first response's ETag became the source's validator, and a 304 on the next
  pass's probe -- a request for page one -- ended the whole source, however
  many pages the board had. A board that needs a second page now keeps no
  validator; one read in a single response keeps its own. This also exposed
  that a stored validator could never be cleared: see the correction to B26
  above. A complete pass now states the validator exactly, including stating
  that there is none. Reproducers:
  `CollectionTests.test_a_validator_from_the_first_page_does_not_speak_for_the_second`
  and `IncrementalReconciliationTests.test_a_complete_pass_without_a_validator_clears_the_stored_one`.
- **A missing id was stringified into a link.** Oracle built `/job/None`,
  which is a public HTTP address as far as any URL check can tell; the record
  was accepted, the pass stayed complete, and the posting it could not identify
  was taken as proof that a real one had been withdrawn. Workday, SmartRecruiters,
  Phenom and AMD built links the same way. Each now refuses a record missing
  the field its link is built from, which keeps the pass partial. Reproducer:
  `CollectionTests.test_a_link_is_not_built_from_a_missing_id`.
- **A page of unreadable records was read as a repeated page.** Pagination
  took "nothing accepted" as the provider ignoring the offset, and a page of
  malformed records also accepts nothing, so the pass stopped with every later
  valid page unread and the provider blamed for it. Nothing accepted is a
  repeat now only when nothing was refused either; the pass stays partial for
  the rejects and carries on reading, within its page cap. Reproducer:
  `CollectionTests.test_a_page_of_unreadable_records_is_not_a_repeated_page`.
- **`--no-store` built the job store.** A missing index was bootstrapped to
  read the catalog before the flag was consulted. It now reads the catalog
  through a temporary database, as the plan preview already did. Reproducer:
  `NoStoreTests.test_a_missing_index_is_not_built_to_read_the_catalog`.
- **Structured data for some of a page's jobs hid the rest.** `html_items`
  returned as soon as it found any JobPosting, so a page publishing metadata
  for four of the five jobs it listed became a four-job inventory, and the
  fifth -- still linked -- was retired by a pass that called itself complete,
  under the closure fuse's threshold. Structured records are still preferred;
  a listed job they do not cover is kept from its link. Covered means the same
  address, or the same requisition where the provider's URLs carry one this
  code can name. A page whose JSON-LD and links spell one job's address
  differently can now list it twice, which is the recoverable direction.
  Reproducer: `CollectionTests.test_structured_data_for_some_listed_jobs_does_not_hide_the_rest`.
- **A sitemap detail page kept only its heading.** Where a detail page had no
  JSON-LD, the fallback kept the H1 and the URL and discarded the page it had
  just downloaded, so a posting whose requirements were written beneath its
  heading reached the review queue as one that asked for nothing. The page's
  main text is now kept as its description. Reproducer:
  `SitemapDetailTests.test_the_requirements_under_the_heading_are_kept`.
- **B45 on the direct path.** A whitespace title passed `normalize`'s check,
  was emptied by cleaning afterwards and raised in SQLite at commit; a posting
  date sent as an object raised there too. The title is now checked after
  cleaning and the date dropped rather than refused, at the boundary both
  intake paths share. Reproducer:
  `CollectionTests.test_a_whitespace_title_is_refused_at_the_record_not_the_commit`.

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
  **Correction, found in the B52 round:** this stopped the collector from
  taking the shell's ETag, but a shell ETag already stored stayed stored.
  `record_source` wrote validators with `COALESCE`, so a complete pass that
  supplied none kept the old one, and `plan` went on returning `conditional`.
  The handoff said the stale validator would be cleared by the next complete
  pass; that was reasoned, never tested, and false. It is true since B52, with
  `IncrementalReconciliationTests.test_a_complete_pass_without_a_validator_clears_the_stored_one`.

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
  **This fix caused a production regression; see "Workday stopped at forty
  postings", 2026-09-21.** The `or` it removed had also been discarding the
  `total: 0` Workday sends on every page after its first, and the test above
  covered only a first page.
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
