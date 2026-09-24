# Operation1million

A job search pipeline for early-career chip design roles in the US: RTL, design
verification, physical design, DFT, FPGA and nearby hardware work.

Every morning it reads the career boards of 35 semiconductor companies, runs a
capped paid search for everyone else, throws out what I can't or won't apply to,
and leaves the rest in a review page where I mark each posting applied or skipped.

## What it filters out

- Senior, principal, lead, manager, director and other levels past early career
- Jobs outside the trade: software, sales, legal, fab process, optics and so on
- More than two years of required experience
- PhD-only postings
- A U.S. citizenship or U.S.-person requirement
- Postings located only outside the US

## How it runs

- **Sources:** Workday, Greenhouse, Ashby, Eightfold, SmartRecruiters, Phenom
  and a few company-specific sites, plus JSearch for paid discovery.
- **Schedule:** one VPS, a systemd timer at 04:38 Pacific.
- **Storage:** an append-only daily event log, with SQLite as a rebuildable
  index. Collected data and application decisions live in a private repo.
- **Review:** a small local web server reached over an SSH tunnel.

## Layout

| Path | What |
| --- | --- |
| `src/jobdisco/` | collector, filters, store, review server |
| `data/config/` | source catalog, search plan, filter rules |
| `tests/` | offline test suite |
| `deploy/vps/` | installer, daily pass, systemd units |
| `deploy/local/` | double-click scripts: open review, deploy, back up |
| `application-autofill/` | standalone local-only application form reader and filler |
| `docs/` | design notes and operating rules |

## Run it locally

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
$env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m jobdisco.collector --company marvell --no-store
```

Paid search stays off unless you pass `--jsearch` and set `JSEARCH_API_KEY` in
`.env.local` (copy `.env.example`).

## More

- [Architecture](docs/architecture.md): how the pieces fit, and the bug log
- [Collection rules](docs/collection-rules.md): pacing, cooldowns, stop conditions
- [Job store](docs/job-store.md): incremental passes and what closes a posting
- [VPS deployment](docs/vps-deployment.md)
- [Local answer bank and application autofill](docs/answer-bank.md)
