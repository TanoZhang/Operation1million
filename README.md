# Job Discovery

Job Discovery finds relevant hardware engineering opportunities from configured
company sources, ATS providers, public feeds, and compliant search fallbacks.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

Credentials stay in the ignored `.env.local` file. Copy `.env.example` and add
values locally; never commit credentials.

## Run

Read [Collection Rules](docs/collection-rules.md) for request intervals,
cooldowns, direct source decisions, and the daily incremental behavior. Read
[GitHub Actions](docs/github-actions.md) before changing hosted runs.

```powershell
.\.venv\Scripts\python.exe -m jobdisco.collector
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The collector reads `data/db/job_discovery.sqlite` and `data/config/`. Without
`--output`, it creates a UTC directory under `runs/`. Generated run contents
are ignored by Git; `runs/latest.json` is the reviewed pointer.

## Layout

- `src/jobdisco/`: installable Python package and console entry points
- `tests/`: package tests
- `data/config/`: schemas, migrations, provider and source configuration
- `data/raw/`: source validation reports
- `data/db/`: SQLite catalog
- `runs/`: timestamped generated collection results
- `docs/`: operating rules, usage notes, and publication policy

Versioned SQL and migrations define the source catalog. The executable JSearch
plan is `data/config/jsearch_queries.toml`. Private compressed event history is
the durable job store; SQLite is a rebuildable local index.

## Job store and incremental runs

Each pass writes into the shared `jobs` table and checkpoints `source_state`.
On a fresh machine, restore private history under `JOBDISCO_STORE` (default
`data/store`) and bootstrap the derived database:

```powershell
.\.venv\Scripts\python.exe -m jobdisco.store --bootstrap
```

`first_seen` is our own observation and exists for every board. `posted_at` only
exists where the board publishes an absolute date, which is about half of them;
Workday states only relative text such as `Posted 7 Days Ago`, kept verbatim in
`posted_relative` and never converted. Anything that reports "new today" must
therefore key off `first_seen`, not `posted_at`.

`source_state` is empty before the first run, so the first pass downloads every
board in full. Later passes pick the cheapest safe strategy per source:

| Strategy | Chosen when | Effect |
| --- | --- | --- |
| `conditional` | the board returned an `ETag` | one probe; `304` ends the source |
| `since` | the board lists strictly newest-first | stop paginating past the last complete pass |
| `lastmod` | the sitemap carries `<lastmod>` | refetch only changed detail pages |
| `full` | anything else | read the whole board |

`full` is the default on purpose: a board that merely trends newest-first, or
whose dates are relative, is read completely rather than guessed at. Only a
`complete` pass advances a source's watermark. Only a complete inventory pass
may retire a posting; a since-window scan, search, capped, paused or failed pass
never closes a job it simply did not reach.

Pass `--no-store` to write run files without touching the store.

## JSearch functional discovery

Read [JSearch daily discovery](docs/jsearch.md) before enabling paid collection.
Preview the 52-query plan with `python -m jobdisco.collector
--jsearch-plan`. Run `python -m jobdisco.collector --jsearch` to collect direct
boards first, functional searches second, and configured company fallbacks last.
Each call asks for a single page and a query stops when the provider runs
short, so the number of pages a day uses is discovered, not declared; a runaway
guard of 40 pages bounds any one query. Tier A is paged to exhaustion before
tier intern, then B, then C. Depth is set per tier so that order is a
preference and not an exclusion: a single depth let tier A spend the whole
budget while thirty-seven queries, every internship among them, went unasked.
The ceiling is 320 page
credits/day and the monthly target is 9,600. Paid search
is off in local and manual commands without explicit flags. The private GitHub
Actions workflow runs daily at 04:38 America/Los_Angeles and enables the fixed
plan for scheduled runs. Finalized daily logs cannot be appended again.
