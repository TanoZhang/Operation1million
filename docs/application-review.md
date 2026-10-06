# Application review

The review server runs on the VPS, which owns the index, the seen table and the
decisions written through it. It binds only to `127.0.0.1` and is reached over
an SSH tunnel; see **VPS review** below. Running it against a local checkout
(`python -m operation1million.review`, then `http://127.0.0.1:8765`) is for development,
not for deciding: a decision written on a second machine is a second writer, and
two copies of an append-only log do not reconcile. `--port` moves the port,
`--db` selects a different index.

It never submits an application, collects jobs, buys credits, or commits data.

## What the queue holds

**To review** is every open posting first seen in the last 72 hours.
**Backlog** is everything older that nobody has ruled on yet -- three days is a
working rhythm, not an expiry, so a posting missed on Friday is still reachable
on Monday. Since 2026-09-26 the Backlog tab leaves early career postings out:
an older intern / NG posting is under Early career's backlog section only.

**Early career** takes the To review postings whose title names an intern, a
new grad (or "NG") or the early career -- the server's `early_career`, from
`ranking.EARLY_CAREER`. Everything else, such as "Master's in EE plus 2 years
of experience", stays on To review. Both tabs run new postings first, then the
backlog, and Remaining counts both.

**Low relevance** holds what is barely related, new or old: a title in the last
band *and* a Fit under `min_confidence` (the server's `less_related`). Those
postings appear on that tab only, never under To review or Backlog, and
Remaining does not count them. They can still be marked applied or skipped
there.

A position is one requisition: the provider's own job id, and the URL only where
a provider publishes no id. The id is scoped the way the store scopes
`job_identities` -- JSearch ids hold across the provider, a direct source's ids
only within that company's own board -- so two boards that both number a
requisition `12345` stay two positions. Several listings share a position only
when they carry the same scoped id, which is the one case where they are
provably the same opening.

A role genuinely advertised once per location therefore appears once per
location. That is deliberate -- showing a posting twice is recoverable and
hiding one is not, and company-and-title grouping was burying 48 Apple
requisitions behind a single Skip.

Two exceptions since 2026-10-05, at the user's request. **Mark applied** also
hides every other listing with the same employer and title -- a job board's
copy, or the company reposting it under a new job number -- unless both name
cities and they differ. A listing that names no city ("US", "3 Locations", a
bare state) is taken to be the same job. **Skip** still answers only its own
requisition. And undecided intern / new grad listings with the same employer,
title and named places are one entry.

The hard title and employer exclusions are re-applied at read time, so a rule
tightened after collection takes effect on rows already stored.

## Ordering

Positions are ranked by band first and by date second; `operation1million/ranking.py`
holds the rules and the reasoning.

| Band | Contents |
| --- | --- |
| Intern / New Grad | The trade, open to the early career |
| Related · Intern / New Grad | Adjacent hardware, open to the early career |
| Core VLSI | The trade: RTL, ASIC, FPGA, SoC, DV, physical design, DFT, VLSI |
| Related Hardware | Adjacent: embedded, firmware, validation, memory, PCIe |
| Other | Kept, but naming neither |

Both early-career bands come before either regular one, because an internship
is what this search is for: an adjacent internship is an opening it can take
and a principal RTL role is not, so the internship is shown first even though
the other is more squarely the trade.

Early career never rescues a posting from outside the trade and its
neighbourhood, though. `Software Marketing Intern` names neither, so it stays
in the last band below every engineering posting in the queue -- the word
"Intern" is not a lift out of it. Within a band the order is the publication
date newest first, then the relevance score, then discovery time, then a stable
tie break.

The score alone could not do this. It measures how much of the trade's
vocabulary a posting uses, which says nothing about whether the posting is open
to someone who has not graduated, and rates a staff-level opening exactly as it
rates one a new graduate can take. It is kept for what it is good at: separating
postings inside a band.

**`first_seen` is not a publication date.** It is consulted only where the
employer published none, and a position standing on that fallback sorts behind
one of the same day that stated its date, because the first is an inference and
the second is a statement. The first collection pass gave forty thousand
postings the same `first_seen`; treating the two as interchangeable would have
read every one of them as published that morning.

A position marked **Adjacent** was admitted on its description rather than its
title -- see `evidence_title_patterns` in `data/config/jsearch_queries.toml`.
`RF Engineer` is not the trade and `RFIC Digital Verification Engineer` plainly
is, so the title decides neither and the posting's own text decides both. A
posting with no readable description has shown nothing and is not admitted.

Publisher "Posted ..." suffixes and known trailing locations do not participate
in title identity; the original provider text stays in raw evidence. Posting
dates are displayed separately, with a "Posted today" marker when the structured
date matches the browser's local day. Missing dates are not guessed. Old ledger
snapshots are normalized during replay without rewriting them.

Use the listing links to apply, then choose **Mark applied**, or **Skip** with
an optional reason. Both cover the whole requisition and nothing wider.

Applied and skipped views retain decision history, including jobs that have
since closed or aged out. **Move to review** appends a `pending` event. A reopened
position appears in the queue only if it still meets the open/72-hour rule.

## Sorting and the Excel export

Added 2026-10-01 at the user's request. The sort menu offers fit high to low
(then newest or oldest), fit low to high (then newest), newest first, oldest
first, and the recommended order above. A group's date is its newest posting
date, or where no listing states one, the newest day it was first seen; a
group with neither goes last. The browser remembers the choice.

**Export to Excel**, or the **E** key anywhere outside a text field, writes the
list on screen -- this tab, this search, this order, one row per listing --
to one workbook: `.local/exports/review-queue.xlsx` unless `job-review
--export PATH` names another, such as a shared folder others apply from.
Each export replaces that file; nothing is opened and no second copy is made.
While Excel has the workbook open, Windows refuses the replacement and the page
says to close it. The file holds job data: keep it out of the public repo.

Served from the VPS through the tunnel, the workbook is written on the VPS
(`/opt/operation1million/exports/review-queue.xlsx`; the checkout is read-only to the
service), not on the machine running the browser. Double-click
`deploy/local/get-export.bat` to copy it to `Documents\review-queue.xlsx`
(or `OPERATION1MILLION_EXPORT`), replacing the last copy.

## The company's own link for a third-party listing

Added 2026-10-02 at the user's request. A paid listing usually links to a
third-party site. Once the company's own posting is found, **Use company
link** on that listing records it; **Open company listing** then leads the
row, the third-party link stays beside it, and **Change** / **Remove** edit it.
The link is kept in `OPERATION1MILLION_STORE/operational/listing_links.ndjson`, beside
the decision ledger and append-only like it (the latest record for an address
wins; an empty link removes it). It applies to every listing at that address,
survives index rebuilds, is backed up with the ledger, and is what the Excel
export links to, with the third-party address in its last column.

## Durable state

The authoritative file is `OPERATION1MILLION_STORE/operational/applications.ndjson`.
Without that environment variable, it is `data/store/operational/applications.ndjson`,
which is ignored by the code repository. `--ledger` can select another path.
Set `OPERATION1MILLION_STORE` to the local checkout of the private data repository to keep
the ledger there. Back up or commit this file to that private repository; a file
stored only locally is not a remote backup. Never put it in the public overview.

Each line is an immutable decision with URL, UTC timestamp, status, optional
reason, requisition-level group ID, and a snapshot of the grouped listings. The
last event in append order determines the current status. Undo is another event,
never a rewrite. URL-only events with `url`, `at`, and `status` are also accepted
for compatibility.

Writes are serialized with an OS file lock, flushed and fsynced before returning
success. Do not run simultaneous writers on separate Git checkouts or manually
merge competing histories. A malformed or interrupted line stops replay and
writes with its line number, preserving evidence for explicit recovery. The
adjacent `.lock` file is disposable and should not be committed.

No application status lives in SQLite. The review server replays the ledger, so
rebuilding the job database with `job-store --bootstrap` cannot erase decisions.
To recover on another machine, restore the private job logs and application
ledger, rebuild or restore the job database, and start the review server.

## VPS review

`deploy/vps/operation1million-review.service` serves only `127.0.0.1:8765` on the VPS.
It runs from `/opt/operation1million/code`, the same checkout the collector uses, so the
Review queue and the collector use the same filter rules. It reads
`/opt/operation1million/code/data/db/job_discovery.sqlite` and writes
`/opt/operation1million/data/operational/applications.ndjson`. The collection publisher
includes this ledger in the next private data-repository checkpoint, and
`operation1million-backup.timer` backs the ledger up more frequently. Decisions made
after the most recent checkpoint remain local to the VPS until the next backup
or collection publication.

Access it with an SSH tunnel, not a public port:

```text
ssh -N -L 8767:127.0.0.1:8765 <configured-vps-host>
```

Then open `http://127.0.0.1:8767`. Keep one authoritative ledger on the VPS; the
earlier standalone local ledger is not automatically merged into it.
# Checkbox selection and browser Excel download

Each position has an independent checkbox. Select all matching positions includes
the entire current filtered list, including rows behind Show more. Selection
survives tabs/search/sorting, and Clear selection removes all checked IDs.
Download selected Excel downloads the selected requisitions, including all their
locations, directly to the browser. It does not mark them Applied or Skipped.
Download Excel/E now downloads checked positions, or all current matching
positions when none are checked. It no longer silently saves to a VPS path.
The download endpoint requires the same page token and creates workbook bytes
in memory, without replacing or locking the existing server export file.
Third-party badges and the Excel Third-party site column share one classification
in export.third_party_site. LinkedIn and Handshake are user-requested exceptions;
other paid/third-party listings are marked. Direct company-board rows are not.

## Pasted links (2026-10-02)

Paste one individual posting URL in Review. Add job and score reads public
JobPosting structured data, scores it with the active relevance rules, and keeps
it regardless of automatic discovery eligibility. Optional Company and Title
allow saving without fetching when a site blocks access; Description improves
scoring. An optional requisition ID supports matching across different URLs.
Already applied matches a known URL without fetching and writes the normal
application ledger. Unknown links can first be read or supplied with details.

Company/title alone never establishes identity. A matching explicit URL or
company-scoped requisition ID deduplicates; check the company-link box to replace
a matching third-party listing. Original snapshots remain in manual_jobs.ndjson
beside the decision ledger. This private durable file must be backed up with
operational/. It survives rebuilding SQLite. Scheduled discovery still applies
all hard rejects, including JobMesh.io. Public fetches share the production
collection lock, stop at challenges, and persist source cooldowns. The reader
takes Greenhouse and SmartRecruiters links from their posting APIs and other
pages from their JSON-LD or schema.org microdata; on a board the index reads,
the company is the catalog's. Apple, Google, HiBob and Oracle (TI) pages publish
no structured posting: fill Company and Title for those (#301-310).
Pasted jobs skip discovery's filters except citizenship: Add job refuses an
excluded employer (the defence list) or a posting that states U.S. citizenship
or U.S. person status, and says why. Already applied still records (#311).
Excel buttons download into the browser; no server workbook is written.

## Applied view and selection scope (2026-10-02)

Switching category clears Excel checkbox selections. Applied changes the paste
form's primary action to Add to Applied: known links are moved to Applied, and
new imported postings receive an application decision directly. Applied cards
and details highlight the recorded application date, including the year. This
date comes from the application ledger, not the posting's publication date.
Queue GETs time out after 25 seconds with a visible message and retry every
10 seconds; initial server warm-up returns Preparing/503 rather than waiting
behind the cold build. Writes are not automatically retried.

## Passed or Declined (2026-10-05)

The Applied tab lists **Passed** first, then **Declined**, then **Waiting for
a reply**, each under its own heading with a select-all box. The **Show**
menu narrows the tab to one of them. The status is printed large above the
company, with "from Gmail" when the mailbox set it.

On the Applied tab, a position can be marked **Passed** or **Declined**.
Clicking the marked button again, or **Clear outcome**, removes the mark.
A passed position turns the card yellow, and a declined position is greyed out.
The position stays applied: the decision ledger is not touched. Marks are
kept in `operational/application_outcomes.ndjson`, next to the ledger. That
file is append-only like the company links, and the latest mark for a
position wins. It is backed up and merged line by line with the ledger.
Moving a position back to review hides its mark until it is applied again.

### From Gmail

`operation1million-gmail.timer` runs `python -m operation1million.gmail_outcomes` on the VPS
every thirty minutes. It reads the mailbox over IMAP with a Gmail app password
(`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` in `/etc/operation1million/env`). The folder is
read with `BODY.PEEK`, so nothing is marked read. The one change it makes is
to star every reply it reads as Passed, including later rounds (Gmail's star is IMAP
`\Flagged`), once:
`starred.json` remembers it, so a reply the user unstars stays unstarred. A
blank password turns the check off.

Each reply is read sentence by sentence:

- **Passed**: an interview, screen, scheduling link, assessment (HackerRank,
  CodeSignal, HireVue and others) or offer, in a sentence that is neither
  negated nor about what happens *if* the applicant is selected.
- **Declined**: a plain rejection phrase. Courtesies such as "unfortunately"
  or "best of luck" never establish a rejection, even together; ambiguous
  combinations are left for review, and confirmations remain confirmations.
- An application confirmation is nothing, however often it says "interview",
  and so is a description of the process ("Step 2 - Assessments").

Phrases match whole words only, overlapping phrases are all seen, and lines a
mailer wrapped at 72 columns are joined back into their sentences. Each of
those was a real miss. The rules are held to a fixed evaluation set in
`tests/test_gmail_outcomes.py`. On 2026-10-05 they were also measured on 89
real rejections published under MIT by DiogoRibeiro7/Job-Rejection-Analysis:
80 of the 81 with a body read Declined, and the 81st is a confirmation.

A second round (another assessment, another interview) after Passed changes
no outcome, but each round's email is starred once. A
rejection after it turns the position Declined, because the latest reply wins.

A reply is matched to one applied position by the company, in the sender or
subject first. Where several applications went to one company, a requisition
ID or a uniquely matching full title in the email decides. Matching titles
with different or missing requisitions remain ambiguous; explicit contradictory
requisitions block title/company fallback. Role wording in the body counts too. A reply from before the application is about something
else. The latest reply wins, so an interview and then a rejection ends as
Declined. Marks made from Gmail say "Gmail" on the chip. A mark set or cleared
by hand is never overridden.

Whatever this cannot settle goes in **Gmail: replies need a look** on the
Applied tab rather than being dropped. That covers both sides being present
(passed and declined), a vague mention of an interview, or an email naming no
single position. Clicking an item opens the position when one was guessed.
Items leave the list after a later manual decision or a later decisive email
settles all candidate positions, or after 21 days. An older mark cannot hide a
newer ambiguous reply. Gmail decisions are compared by email time, not replay time.

The private working files (message cache, the unsettled list, the last run's
summary) live in `/opt/operation1million/gmail`, mode 700, outside both repositories.
