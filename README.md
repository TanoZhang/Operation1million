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
cooldowns, direct source decisions, and the daily incremental design.

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

The database is the source of truth for companies, sources, enabled search query
templates, and collected job records.

## Job store and incremental runs

Each pass writes its rows into the `jobs` table and records what it learned about
the source in `source_state`. Run one migration before the first collection:

```powershell
.\.venv\Scripts\python.exe -c "from jobdisco import store; store.migrate()"
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
`complete` pass advances a source's watermark or retires a posting, so a capped,
paused or failed pass never closes a job it simply did not reach.

Pass `--no-store` to write run files without touching the store.
