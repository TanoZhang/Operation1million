# Local application review

Run `python -m jobdisco.review` and open `http://127.0.0.1:8765`.
Use `--port` if that port is occupied, or `--db` to select a derived job index.
The server binds only to the local machine. It never submits an application,
collects jobs, buys credits, or automatically commits or pushes data.

The queue contains open jobs first discovered in the preceding 72 hours, using
`first_seen`, not a provider's potentially missing or ambiguous posting date.
Company identity and normalized title merge location variants into one position.
Positions are ordered by their stored relevance score. There is no additional
score cutoff. Current hard title and employer exclusions also apply to existing
records. Publisher "Posted ..." suffixes and known trailing locations do not
participate in title identity; original provider text stays in raw evidence.
Posting dates are displayed separately, with a "Posted today" marker when the
structured date matches the browser's local day. Missing dates are not guessed.
Old ledger snapshots are normalized during replay without rewriting them.
Use the listing links to apply, then choose **Mark applied**, or
choose **Skip** with an optional reason. Both actions handle the whole position,
including future location variants under that same company and title.

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
