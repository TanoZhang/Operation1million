# The daily pass on a VPS

The collection pass runs on an OVH VPS-1 (2 vCPU, 4 GB, 40 GB, Ubuntu 24.04)
rather than on a GitHub Actions runner. The move is not about cost. A runner
starts with an empty disk, so every hosted pass rebuilt the database from the
committed log first: 639 MB at peak and 21.5 seconds, paid daily for a result
that never changed. A machine that keeps its disk pays it once. The same disk
removes the 2,000-minute monthly budget and the 120-minute job timeout, and the
timeout is what used to bound how deep a search could go.

`.github/workflows/collect.yml` stays, with `workflow_dispatch` only. It costs
nothing once it no longer fires on its own, and it is the clean-room way to run
a pass while this machine is being changed or is suspect.

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
    sudo ./Operation1million/deploy/vps/install.sh

The first run writes `/etc/jobdisco/env` with blank values and stops. Fill it in
with an editor **on the box** — not by passing values on a command line, which
puts them in your shell history and in the process list — and run the script
again:

    sudo nano /etc/jobdisco/env
    sudo ./Operation1million/deploy/vps/install.sh

| Variable | What it is |
| --- | --- |
| `JSEARCH_API_KEY` | RapidAPI key for the fixed JSearch plan |
| `GITHUB_TOKEN` | Fine-grained PAT: Contents read on the code repository, Contents read **and write** on the data repository |
| `HEALTHCHECK_URL` | Healthchecks.io ping URL for the production check |

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

    sudo /opt/jobdisco/code/deploy/vps/install.sh

The code checkout is reset hard to `origin/main`, so local edits on the box are
discarded by design: the repository is the source of truth and a machine that
has drifted from it is the thing you are trying to avoid. The data checkout is
only ever fast-forwarded, because it holds commits this machine made.

## Triage

    systemctl list-timers jobdisco-collect.timer   # when it next fires
    systemctl status jobdisco-collect.service      # how the last pass ended
    journalctl -u jobdisco-collect.service -n 200  # what it printed
    journalctl -u jobdisco-collect.service --since '2 days ago'

To run a pass by hand **without** disturbing the monitor:

    sudo -u jobdisco HOME=/opt/jobdisco \
      /opt/jobdisco/code/deploy/vps/daily-pass.sh --no-heartbeat

Note that this is a real pass: it spends credits, writes the log and pushes. It
differs from a production pass only in staying silent to Healthchecks. There is
no dry-run mode on the box; use the workflow's `dry_run` dispatch for that.

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

The pass mirrors `collect.yml` step for step except in three places, each a
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

**The 14-day local retention discussed during planning is not implemented, and
deliberately so.** Deleting old log files inside the data checkout would stage a
deletion that the next `git add`/`commit` would publish, removing them from the
authoritative copy on GitHub — the opposite of the intent. The safe equivalents
(sparse-checkout with a pattern rewritten daily, or a shallow clone) are real
machinery for a problem this machine does not yet have: at about 20 MB a day,
tree and history together fill 36 GB in roughly two and a half years.

What is implemented instead is the 5 GiB floor: the pass refuses to start rather
than failing partway through a write. Revisit retention when the data repository
is reset, which the ~5 GB GitHub guidance forces in roughly eight months anyway
and which is the deliberate act that actually reclaims anything.

## The fixed address

Actions runners rotate through Azure ranges; this machine does not. Collection
is polite — per-source request intervals, `Crawl-delay` honoured, durable
cooldowns on 429 and 403 — and a predictable polite caller is usually treated
better than an unpredictable one. But a stable IP against 35 boards is the one
thing that could behave differently after the move, so watch the per-source
outcomes for a fortnight:

    sudo -u jobdisco /opt/jobdisco/venv/bin/job-store --ranked 0 2>/dev/null
    journalctl -u jobdisco-collect.service --since '14 days ago' | grep -i 'paused\|403\|429'
