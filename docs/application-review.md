# Application review

The review server runs on the VPS, which owns the index, the seen table and the
decisions written through it. It binds only to `127.0.0.1` and is reached over
an SSH tunnel; see **VPS review** below. Running it against a local checkout
(`python -m jobdisco.review`, then `http://127.0.0.1:8765`) is for development,
not for deciding: a decision written on a second machine is a second writer, and
two copies of an append-only log do not reconcile. `--port` moves the port,
`--db` selects a different index.

It never submits an application, collects jobs, buys credits, or commits data.

## What the queue holds

**To review** is every open posting first seen in the last 72 hours.
**Backlog** is everything older that nobody has ruled on yet -- three days is a
working rhythm, not an expiry, so a posting missed on Friday is still reachable
on Monday.

A position is one requisition: the provider's own job id, and the URL only where
a provider publishes no id. Several listings share a position only when they
carry the same id, which is the one case where they are provably the same
opening. A role genuinely advertised once per location therefore appears once
per location. That is deliberate -- showing a posting twice is recoverable and
hiding one is not, and company-and-title grouping was burying 48 Apple
requisitions behind a single Skip.

The hard title and employer exclusions are re-applied at read time, so a rule
tightened after collection takes effect on rows already stored.

## Ordering

Positions are ranked by band first and by date second; `jobdisco/ranking.py`
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

## Durable state

The authoritative file is `JOBDISCO_STORE/operational/applications.ndjson`.
Without that environment variable, it is `data/store/operational/applications.ndjson`,
which is ignored by the code repository. `--ledger` can select another path.
Set `JOBDISCO_STORE` to the local checkout of the private data repository to keep
the ledger there. Back up or commit this file to that private repository; a file
stored only locally is not a remote backup. Never put it in the public overview.

Each line is an immutable decision with URL, UTC timestamp, status, optional
reason, stable company/title group ID, and a snapshot of the grouped listings.
The last event in append order determines the current status. Undo is another
event, never a rewrite. URL-only events with `url`, `at`, and `status` are also
accepted for compatibility.

Writes are serialized with an OS file lock, flushed and fsynced before returning
success. Do not run simultaneous writers on separate Git checkouts or manually
merge competing histories. A malformed or interrupted line stops replay and
writes with its line number, preserving evidence for explicit recovery.
The adjacent `.lock` file is disposable and should not be committed.

No application status lives in SQLite. The review server replays the ledger,
so rebuilding the job database with `job-store --bootstrap` cannot erase decisions.
To recover on another machine, restore the private job logs and application
ledger, rebuild the job database, and start the review server.

## VPS review

`deploy/vps/jobdisco-review.service` serves only `127.0.0.1:8765` on the VPS.
Its code snapshot lives in `/opt/jobdisco/review-code`, independently of an
in-flight collector. It reads `/opt/jobdisco/code/data/db/job_discovery.sqlite`
and writes `/opt/jobdisco/data/operational/applications.ndjson`. The collection
publisher includes this ledger in the next private data-repository checkpoint.
Decisions made after that checkpoint remain local to the VPS until the next one.

Access it with an SSH tunnel, not a public port:

```text
ssh -N -L 8767:127.0.0.1:8765 <configured-vps-host>
```

Then open `http://127.0.0.1:8767`. Keep one authoritative ledger on the VPS;
the earlier standalone local ledger is not automatically merged into it.
