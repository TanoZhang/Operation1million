# GitHub Actions Operations

This document describes the intended hosted-run boundary. It does not enable a
schedule by itself. The workflow belongs only in the private
`TanoZhang/Operation1million` repository.

## What the runner needs

| Item | Action behavior |
| --- | --- |
| Source code and config | Checkout this private repository at `main` |
| `JSEARCH_API_KEY` | Read `${{ secrets.JSEARCH_API_KEY }}` into the process environment; never write it to a file or log it |
| `data/db/job_discovery.sqlite` | Restore the latest private database before collection and save the updated database after a successful checkpoint |
| `.local/source_access.sqlite` | Restore private cooldown state before collection and persist it after the run |
| `.local/jsearch_usage.sqlite` | Restore the private quota ledger before collection and persist it after the run |
| `runs/<UTC timestamp>/` | Keep generated JSONL/CSV output private; upload only to a private retention-limited destination |
| `.venv/` | Do not restore; install the package in the fresh hosted runner |

The runner is temporary. Files disappear when the job ends unless the workflow
explicitly restores and saves them. The tracked SQLite file can be committed
back to this private repository, or all mutable state can use a private durable
storage mechanism. A cache alone is not a source of truth.

## Secret handling

The local `.env.local` file is not copied to Actions. The workflow maps the
repository secret to an environment variable for the collector, for example:

```yaml
env:
  JSEARCH_API_KEY: ${{ secrets.JSEARCH_API_KEY }}
```

Keep logs free of request headers, response bodies containing credentials, full
environment dumps, and unredacted exception objects. The public overview
repository receives no secret and has no collection workflow.

## Private output handling

Collected jobs, raw responses, SQLite state, filter settings, and application
information are private data. Do not commit generated `runs/` files to a public
repository. If Actions artifacts are used, keep the workflow in the private
repository, use a short retention period, and avoid putting personal data in
step summaries or log output. The database checkpoint and the output artifact
must be restorable by the next run.

## Run order

1. Checkout the private repository.
2. Install Python dependencies.
3. Restore the latest database, cooldown ledger, and JSearch ledger.
4. Run `python -m jobdisco.collector` with the configured conservative limits.
5. Verify the exit status and collection manifest.
6. Save the database and operational ledgers before publishing the run artifact.
7. Upload only private output and a short status summary.

Do not advance a source watermark or close missing jobs after a capped, paused,
or failed run. Do not overlap scheduled runs. The first hosted run must be a
manual, bounded test that measures duration, request count, artifact size, and
whether the private state is restored correctly. Only after that test should a
daily schedule be added with an explicitly chosen time.

## Current status

`JSEARCH_API_KEY` is already present as a repository Actions Secret. No Actions
workflow or schedule is enabled yet. Persistent job-store code exists, but the
hosted restore and checkpoint workflow still needs implementation and testing.
