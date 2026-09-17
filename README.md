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
- `data/raw/`: research inputs and validation reports
- `data/db/`: SQLite catalog
- `runs/`: timestamped generated collection results
- `research/`: historical probes and one-off analysis
- `docs/`: operating notes and source attribution

The database is the source of truth for companies, sources, and enabled search
query templates. Generated job records remain run artifacts until storage and
review tables are added.
