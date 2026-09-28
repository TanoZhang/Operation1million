# Claude Code

[AGENTS.md](AGENTS.md) is the rulebook, shared with Codex. Nothing here overrides it.

## Running

There is no `python` on PATH. Use the checkout's virtualenv:

    PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover -s tests

The suite is offline and takes about a minute. Run all of it before pushing.
Tests that need `data/db/job_discovery.sqlite` skip when it is missing; say so
when a result depends on real rows.

Nothing needs to skip. On this machine (set up 2026-09-27):

- The index: the private data repo is cloned at
  `../Operation1million-data`; build it with
  `JOBDISCO_STORE=../Operation1million-data PYTHONPATH=src .venv/Scripts/python.exe -m jobdisco.store --bootstrap`.
- The POSIX-only tests (flock, process groups, file modes) run in a WSL1
  distro, `Op1mTest`, with a non-root `tester` user and its own `.venv` in
  `~/op1m`. WSL2 cannot start here (virtualization is off in firmware). Pull,
  link the index and run:

      wsl -d Op1mTest -u tester -- bash -c "cd ~/op1m && git pull -q && ln -sf /mnt/c/Users/Tano/Documents/Operation1million/data/db/job_discovery.sqlite data/db/job_discovery.sqlite && PYTHONPATH=src .venv/bin/python -m unittest discover -s tests"

## Reporting

Keep what you measured apart from what you assume. If a claim matters and is
cheap to test, test it.
