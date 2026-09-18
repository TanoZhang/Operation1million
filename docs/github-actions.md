# GitHub Actions operations

This is the deployment contract for the enabled private daily workflow.
The runner is temporary; every authoritative private input must be restored
before collection and saved after successful checkpoints.

## Repository boundary

The intended separation supports a clean code repository containing source,
tests, schemas, configuration examples, workflow definitions and documentation,
and a private data repository containing compressed run history and manifests.
`JOBDISCO_STORE` can point at the private checkout without changing the collector.

The current operating repository remains private because old Git history
contains real data. Do not change its visibility or mirror its history into a
public code repository. The existing public overview is still documentation
only. Publishing a clean code history and wiring repository access are separate
deployment steps; this integration changes neither visibility nor permissions.
Run the data-handling workflow privately so logs and artifacts stay private.

## Required state

| Item | Runner behavior |
| --- | --- |
| Source code and config | Checkout the reviewed code revision and install the package |
| JSEARCH_API_KEY | Map the private Actions Secret into the process environment |
| JOBDISCO_STORE/runs/*.ndjson.gz | Restore immutable private daily event history and numbered shards |
| JOBDISCO_STORE/manifests/*.json | Restore private checksums and run statistics |
| JOBDISCO_STORE/source_state.json | Restore the private source checkpoint |
| data/db/job_discovery.sqlite | Rebuild locally; never commit this derived database |
| .local/source_access.sqlite | Restore and save private provider cooldown state |
| .local/jsearch_usage.sqlite | Restore and save the private page-credit ledger |
| runs/<UTC timestamp>/ | Optional private, retention-limited transient exports |

A cache alone is not an authoritative store. Missing quota or cooldown state
must stop a hosted run rather than silently creating a fresh allowance. Data
repository credentials must be scoped to the private destination and supplied
as secrets; they are separate from JSEARCH_API_KEY.

## Credentials

The local `.env.local` is not copied to Actions. Use environment injection:

```yaml
env:
  JSEARCH_API_KEY: ${{ secrets.JSEARCH_API_KEY }}
```

Do not print headers, credentials, raw paid responses, environment dumps or
private job records. Public artifacts and public workflow logs are unsuitable
for collected data, regardless of whether download requires a login.

## Run order

1. Checkout reviewed code and restore the private data checkout and both ledgers.
2. Set JOBDISCO_STORE to that checkout's store directory.
3. Install dependencies and run `python -m jobdisco.store --bootstrap`.
4. Run the offline regression suite.
5. Run `python -m jobdisco.collector --jsearch-plan` and verify the budget.
6. Run `python -m jobdisco.collector --jsearch` with one collector process.
7. Verify checksums and inspect completion/failure metrics, including exit code 2.
8. Save `operational/source_access.sqlite` and
   `operational/jsearch_usage.sqlite` even after collection failures: attempted
   credits remain spent and cooldowns remain active. These are the only SQLite
   files force-added despite the data repository's general SQLite ignore rule.
   Save valid source checkpoints and daily files privately; never rewrite an
   already sealed daily log. A dry run checkpoints only these safety ledgers,
   not collected jobs.
9. Retain optional exports privately and publish only a non-sensitive summary.

Use concurrency control to prohibit overlapping writers. Multiple passes may
append to the current UTC day and refresh its manifest. Once the UTC date
changes, the prior log is sealed and cannot be rewritten. Do not discard
history or reset usage during recovery.
Before an append would take the current file above 90 MB, it becomes a numbered
same-day shard with its own checksum manifest. This keeps blobs below GitHub's
100 MB limit without rewriting or dropping events.
The bounded transport test used one credit and succeeded before paid scheduling
was enabled. The billing anchor is day 16, the day the provider resets. A page
is reserved before it is
requested and is charged even when the provider fails, so the day's spend is a
floor on what was asked for, never a guarantee of returned pages or coverage.

## Current status

The workflow is scheduled daily at 04:38 `America/Los_Angeles`. It restores the
private data repository, rebuilds the derived database, runs offline tests,
previews the fixed JSearch plan, collects direct sources with three workers, and
runs paid JSearch. It checkpoints both operational ledgers even on collection
failure. Manual dispatches default to no paid search and expose an explicit
`enable_jsearch` toggle. The data repository credential was replaced and later
hosted runs completed checkout, collection, checkpointing, and report upload.
Collector exit code 2 produces a workflow warning and retained report because it
means partial or paused sources; unexpected nonzero exits still fail the job.
A dry run emits an explicit notice with new, closed, and seen counts, restores
tracked durable files, and removes untracked daily files before the runner exits.
Only the safety ledgers and the retention-limited triage report survive it.
Sweeps require the same paid-search opt-in as daily discovery on manual runs.
Missing or empty operational ledgers stop the workflow before collection. If
collected history fails verification, publication restores the previous sweep
cursors while retaining all new charges and cooldowns, and the job fails after
saving those ledgers. A remote push conflict fails without rebasing independent
quota histories; reconcile the private ledgers before retrying collection.
Paid paging also has a graceful runtime ceiling: 25 minutes in the daily pass
and 50 minutes in the end-of-cycle sweep. The ceiling is checked before buying
the next page so the job can seal and push its partial progress before the
120-minute Actions timeout.

## Actions minutes

The free allowance is 2,000 minutes a month, and a private repository's jobs are
billed rounded up to the minute. The billing API needs the `user` token scope,
which this checkout does not carry, so the figure below is summed from run
durations instead:

```bash
gh api "repos/TanoZhang/Operation1million/actions/runs?per_page=100"   --jq '.workflow_runs[] | [.id, .created_at, .updated_at, .conclusion] | @tsv'
```

As of 2026-09-18: **88 minutes billed, 1,912 remaining.** Six runs, of which the
46-minute one predates the Microsoft lock. A daily pass now costs 14 to 24
minutes, so thirty of them is roughly 600, and three backfill days add to that.
No alerting is wired for this yet; the number is recorded, not watched.
