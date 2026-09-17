# GitHub Actions operations

This is the deployment contract, not an enabled workflow or schedule.
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
| JOBDISCO_STORE/runs/*.ndjson.gz | Restore immutable private daily event history |
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
4. Run `python -m jobdisco.collector --jsearch-plan` and verify the budget.
5. Run `python -m jobdisco.collector --jsearch` with one collector process.
6. Verify checksums and inspect completion/failure metrics, including exit code 2.
7. Save `operational/source_access.sqlite` and
   `operational/jsearch_usage.sqlite` even after collection failures: attempted
   credits remain spent and cooldowns remain active. These are the only SQLite
   files force-added despite the data repository's general SQLite ignore rule.
   Save valid source checkpoints and daily files privately; never rewrite an
   already sealed daily log. A dry run checkpoints only these safety ledgers,
   not collected jobs.
8. Retain optional exports privately and publish only a non-sensitive summary.

Use concurrency control to prohibit overlapping writers. A sealed UTC day
cannot be run again in the same store. Interrupted unsealed logs require
inspection/recovery before retry; do not discard history or reset usage.
First perform an explicitly authorized bounded manual deployment test to verify
restore, write access, quota accounting, duration and crash/failure handling.
Configure the real billing-cycle start day and choose a schedule time only after
that test. The functional plan's 310 pages are reservations, not a guarantee of
310 returned pages or complete job coverage.

## Current status

The integration includes offline regression tests, shared persistence and an
API-free plan preview. The daily workflow is enabled but its first scheduled
attempt failed while checking out the private data repository because
`DATA_REPO_TOKEN` was rejected. Replace that secret before dispatching another
run. The workflow now restores and checkpoints both operational ledgers; paid
JSearch remains disabled in the workflow with `--jsearch-budget 0`.
