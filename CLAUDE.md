# Claude Code

[AGENTS.md](AGENTS.md) is the rulebook, shared with Codex. Nothing here overrides it.

## Running

There is no `python` on PATH. Use the checkout's virtualenv:

    PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover -s tests

The suite is offline and takes about a minute. Run all of it before pushing.
Tests that need `data/db/job_discovery.sqlite` skip when it is missing; say so
when a result depends on real rows.

## Reporting

Keep what you measured apart from what you assume. If a claim matters and is
cheap to test, test it.
