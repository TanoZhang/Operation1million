# The daily pass on a VPS

The collection pass runs on an OVH VPS-1 (2 vCPU, 4 GB, 40 GB, Ubuntu 24.04)
rather than on a GitHub Actions runner. The move is not about cost. A runner
starts with an empty disk, so every hosted pass rebuilt the database from the
committed log first: 639 MB at peak and 21.5 seconds, paid daily for a result
that never changed. A machine that keeps its disk pays it once. The same disk
removes the 2,000-minute monthly budget and the 120-minute job timeout, and the
timeout is what used to bound how deep a search could go.

`.github/workflows/collect-backup.yml` stays, dispatch-only and titled as a
backup. It costs nothing once it no longer fires on its own, and it is the
clean-room way to run a pass while this machine is being changed or is suspect.

## Install

Everything lives under `/opt/jobdisco`, owned by a system account with no login:

    /opt/jobdisco/code    the collector, checked out from the code repository
    /opt/jobdisco/data    the data repository; JOBDISCO_STORE points here
    /opt/jobdisco/venv    the virtualenv
    /opt/jobdisco/code/.local          the quota and cooldown ledgers
    /opt/jobdisco/code/data/db         the derived SQLite, gitignored
    /etc/jobdisco/env     the three secrets, mode 640, root:jobdisco

On the box:

    git clone https://github.com/TanoZhang/Operation1million.git
    sudo bash ./Operation1million/deploy/vps/install.sh

The first run writes `/etc/jobdisco/env` with blank values and stops. Fill it in
with an editor **on the box** — not by passing values on a command line, which
puts them in your shell history and in the process list — and run the script
again:

    sudo nano /etc/jobdisco/env
    sudo bash ./Operation1million/deploy/vps/install.sh

| Variable | What it is |
| --- | --- |
| `JSEARCH_API_KEY` | OpenWeb Ninja API key for the fixed JSearch plan |
| `GITHUB_TOKEN` | Fine-grained PAT scoped to both repositories, Contents: read and write |
| `HEALTHCHECK_URL` | Healthchecks.io ping URL for the production check |

A fine-grained PAT applies one permission set to every repository it selects,
so the token carries write on the code repository as well even though the pass
only ever reads it and only ever pushes to the data repository. Splitting that
would take two tokens and a per-repository helper, which is more moving parts
than the difference buys on a machine that already holds the JSearch key.

The token is handed to git by a credential helper that reads it from the
environment at run time, so it is never written into `.git/config` and never
appears in a remote URL that `git remote -v` or `ps` would show.

The installer is idempotent. Running it again updates the checkout, the
virtualenv and the units, and leaves the database, the ledgers and the secrets
alone.

## The heartbeat

Nothing on a VPS volunteers that it has died. A timer that stops, a disk that
fills and a process the kernel kills are all silent, and Actions' failure email
does not exist here. So the pass reports to a Healthchecks.io check, and the
absence of a report is itself the alarm.

| When | Ping |
| --- | --- |
| The pass starts | `$HEALTHCHECK_URL/start` |
| Collection, store verification **and** the commit and push all succeeded | `$HEALTHCHECK_URL` |
| Anything failed, including a failure `set -e` took on its own | `$HEALTHCHECK_URL/fail` |
| The machine, the timer or the unit never ran | nothing — the check times out |

Four properties matter, and each has a test in `tests/test_heartbeat.py`:

- **The monitor never changes the pass.** A ping that cannot be delivered is a
  warning on stderr and nothing more. A monitor that could fail the run it
  monitors would turn a good collection red and teach you to ignore the alarm.
- **A failure keeps its exit code.** `/fail` is sent and then the original
  non-zero status is restored, so systemd and `systemctl status` see the real
  failure rather than a swallowed one.
- **Success is never reported early.** The success ping is sent from the EXIT
  trap on status 0, which is reached only after the push.
- **Only production pings.** The URL comes from `/etc/jobdisco/env` through the
  unit and appears nowhere in the source tree — a test walks every tracked file
  to keep it that way. A shell without that variable, which is every manual
  diagnostic and every test, stays silent, because a ping it sent would tell the
  check a production pass had succeeded when none had run.

Configure the check as **period 1 day, grace 3 hours**. A full-depth pass is
about 110 minutes and a sweep day is longer, so a grace period shorter than that
would page you about a pass that is still running normally.

One deliberate exception: collector exit code 2 means the pass finished with
partial or paused sources. That is a warning the project does not treat as a
failure, so it pings success and prints the warning to the journal. If you would
rather be paged on it, change the final `exit` handling in `daily-pass.sh`.

## Update

    sudo bash /opt/jobdisco/code/deploy/vps/install.sh

From the Windows machine, three double-click files in `deploy/local/`:
`open-review.bat` opens the review page through the ssh tunnel;
`deploy-vps.bat` pulls, pushes whatever is committed locally, and runs the
command above over ssh; `backup-vps.bat` runs `backup-from-vps.sh` through Git
Bash into the usual backup folder.

Both checkouts advance only by fast-forward. Local source edits or divergent
history stop installation instead of being discarded. Installation and daily
collection use the same lock, so an update cannot replace running collector code.

## Reaching the review queue

The review server binds to the loopback interface and has no authentication of
its own: the token it issues is handed out by `GET /api/queue` to anyone who can
reach the port. That is safe because nothing can reach the port, and it stops
being safe the moment something can. So it is reached through ssh, not exposed.

From a machine holding the deploy key:

    ssh -N -L 8765:127.0.0.1:8765 ubuntu@<vps>

Leave that running and open `http://localhost:8765`. The Host header the browser
sends is `localhost:8765`, which is what the server already accepts, so nothing
about the service changes.

Opening it to the public internet is a different piece of work and has not been
done: it needs authentication that survives someone finding the address,
TLS, and a proxy in front. Until then a phone needs an ssh client that can hold
a local forward, which is the awkward part of this arrangement and the reason to
do the proxy properly rather than by loosening the bind address.

## Backing it up to a workstation

The VPS owns everything -- the scraper, the index, the seen table, the review UI
and the decisions written through it. A workstation holds a copy in case that
machine is lost, and never writes back: a second writer is how two copies of a
decision log stop agreeing.

    ./deploy/local/backup-from-vps.sh [target-dir]

It streams the data tree over SSH, using the bundled `backup-snapshot.py` on
the VPS. Python is required on both machines; `JOBDISCO_PYTHON` selects the
workstation interpreter. The archive includes the index at
`sqlite/job_discovery.sqlite` and replaces published credit/cooldown copies
with snapshots of the authoritative runtime databases under
`/opt/jobdisco/code/.local` (`JOBDISCO_VPS_STATE` overrides that directory).
Application decisions are copied while holding the decision ledger lock.

The helper runs as the service account (`sudo -n -u jobdisco`, overridden by
`JOBDISCO_VPS_USER`), so the SSH user needs passwordless sudo, which the
default `ubuntu` user has. As `ubuntu` itself it failed, measured on the VPS:
it could not take the lock, which it had no write access to, and it could not
open the index whenever no other process had it open, because a WAL database
with no `-shm` needs one created in a directory `ubuntu` cannot write.

**Copying the file is not the same as copying the database.** The index is in
WAL mode and a pass writes to it for an hour, so `cp` during that hour yields a
main file missing every committed transaction still sitting in the WAL, or a
torn page from a checkpoint that landed mid-read. Neither announces itself, and
both are discovered on the night the copy is needed. The snapshot is taken with
`sqlite3.Connection.backup()`, which copies under a read transaction and starts
again if a writer moves underneath it.

Each database snapshot is independently consistent; this is not one atomic
snapshot of the entire store. The index is captured before quota state, so
discoveries in that snapshot already have their reserved credits represented.
Remote helper and transfer failures stop the pull. On arrival, SQLite integrity
and operational schemas, application events, and the complete compressed seen
snapshot are checked before rotation. An empty application ledger is valid.
Run/manifest pairing and sealed-file checksums must also pass.

Validation failure preserves both installed generations and `last-pull`.
Installation failure restores `current`; a later invocation recovers any
remaining `previous.tmp` before reusing staging. The previous valid generation
is retained until another successful installation.

The minimum set to restore from, in the order it matters:

| What | Where | Regenerated by |
| --- | --- | --- |
| Application decisions | `operational/applications.ndjson` | nothing |
| JSearch credit ledger | `operational/jsearch_usage.sqlite` | nothing |
| Source cooldowns | `operational/source_access.sqlite` | nothing |
| Seen snapshot | `operational/seen_jobs.ndjson.gz` | nothing |
| Job index | `sqlite/job_discovery.sqlite` | the log, but only 14 days of it |
| Run log and manifests | `runs/`, `manifests/` | collection, for what is still open |
| Per-source watermarks | `source_state.json` | a full pass |

Restoring prefers the snapshot, because it holds postings older than the log.
Rebuilding from the log alone still works and remains the tested path, but it
reconstructs only what the fourteen-day window holds: `seen`, `closed` and
`score` events are UPDATE statements, so a posting whose job line has aged out
of the window is not recreated by them.

    JOBDISCO_STORE=<target>/current job-store --bootstrap --verify

## Triage

    systemctl list-timers jobdisco-collect.timer   # when it next fires
    systemctl status jobdisco-collect.service      # how the last pass ended
    journalctl -u jobdisco-collect.service -n 200  # what it printed
    journalctl -u jobdisco-collect.service --since '2 days ago'

To run a pass by hand **without** disturbing the monitor:

    sudo -u jobdisco HOME=/opt/jobdisco \
      bash /opt/jobdisco/code/deploy/vps/daily-pass.sh --no-heartbeat

Note that this is a real pass: it spends credits, writes the log and pushes. It
differs from a production pass only in staying silent to Healthchecks. There is
no dry-run mode on the box; use the workflow's `dry_run` dispatch for that.

**Check the UTC clock before starting one by hand.** The day's log seals when
the UTC date advances -- `sealed()` is `stamp[:10] < now()[:10]` -- and a pass
holds the stamp it began with. A pass started late enough to cross 00:00 UTC
loses the ability to write partway through and reports it as corruption rather
than as a clock. The scheduled pass cannot reach this, being eleven hours clear
in both offsets, but a manual one started in the evening UTC can.

To run a real production pass now, outside the timer:

    sudo systemctl start jobdisco-collect.service

Common failures, and what they look like:

- **`Refusing to collect: only N MiB free`** — the pass checks for 5 GiB before
  doing anything, because a full disk fails exactly where the store is least
  able to survive it. See *Disk* below.
- **`Required operational ledger is missing or empty`** — the data checkout has
  no `operational/jsearch_usage.sqlite` or `source_access.sqlite`. Without them
  the pass would not know what it had already spent, so it refuses.
- **`the store did not verify`** — a day file does not match its manifest. The
  collected postings are deliberately **not** committed; only the operational
  ledgers are. Repair the manifest before the next pass.
- **push rejected** — the remote holds commits this machine has not seen. The
  push is never forced and the histories are never merged, because both sides
  would hold independent quota reservations. Resolve it by hand.

## What differs from the Actions workflow, and why

The pass mirrors `collect-backup.yml` step for step except in three places, each a
consequence of the disk persisting:

1. **The database is built only when it is absent.** `job-store --bootstrap`
   always rebuilds from scratch and replaces the file, so calling it every run
   would reimpose the cost the move was meant to remove. Every pass still runs
   `job-store --verify`.
2. **The operational ledgers are seeded, never restored.** Actions copies them
   out of the data repository on every run because its disk is empty. Here they
   persist and are authoritative: a pass whose push failed leaves the local
   ledger ahead of the published one, and copying the published one back over it
   would resurrect credits the provider has already charged. The published copy
   seeds a new machine and never overwrites a live ledger.
3. **Paid search is always on.** There is no `enable_jsearch` toggle, because
   this machine only ever runs the scheduled production pass.

## Disk

40 GB total, about 36 GB free. The working set is small: the derived SQLite at
roughly 198 MB, the data checkout at about 123 MB today, and the virtualenv.

Runs and manifests in the private data checkout are pruned to a rolling
fourteen-day window after the store verifies. That window is only the compact
recent event history. Pruning never touches the live SQLite database, the
application ledger, the seen snapshot, source_state, cooldowns, quota ledgers,
or anything under `operational/`. The local workstation backup also carries a
SQLite backup snapshot, because a pruned event window is not meant to be the only
way to recover the current live index.

The pass keeps a 5 GiB free-space floor and refuses to start below it rather
than failing partway through a write. Git history still grows until it is
explicitly compacted: pruning the working tree removes old run files from the
current checkout, but old blobs remain in repository history until
`deploy/vps/compact-history.sh` replaces that history by hand.

Compaction holds both collection and application-decision locks, fetches the
remote tip, and requires a clean `main` matching it. Pruning and the replacement
commit are built in a temporary worktree. An explicit lease protects that exact
remote tip; the live checkout follows the candidate only after a successful
push. A rejected push therefore leaves the original branch and files available
for an ordinary pull or retry.

## The fixed address

Actions runners rotate through Azure ranges; this machine does not. Collection
is polite — per-source request intervals, `Crawl-delay` honoured, durable
cooldowns on 429 and 403 — and a predictable polite caller is usually treated
better than an unpredictable one. But a stable IP against 35 boards is the one
thing that could behave differently after the move, so watch the per-source
outcomes for a fortnight:

    sudo -u jobdisco /opt/jobdisco/venv/bin/job-store 2>/dev/null
    journalctl -u jobdisco-collect.service --since '14 days ago' | grep -i 'paused\|403\|429'
