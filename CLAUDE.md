# Claude Code

[AGENTS.md](AGENTS.md) is the rulebook, shared with Codex. Nothing here overrides it.

## Running

There is no `python` on PATH. Use the checkout's virtualenv:

    PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover -s tests

The suite is offline and takes about three minutes. Run all of it before
pushing. Tests that need `data/db/job_discovery.sqlite` skip when it is
missing; say so when a result depends on real rows.

- The index: the private data repo is cloned at
  `../Operation1million-data`; build it with
  `OPERATION1MILLION_STORE=../Operation1million-data PYTHONPATH=src .venv/Scripts/python.exe -m operation1million.store --bootstrap`.
- The 13 POSIX-only tests (flock, process groups, file modes) skip on Windows.
  GitHub Actions (`.github/workflows/tests.yml`, Ubuntu) runs the whole suite
  on every push, those included; read its result before calling a push
  verified. The WSL distro that used to run them, `Op1mTest`, is gone
  (2026-10-23), and virtualization is on in firmware now.

## Reporting

Keep what you measured apart from what you assume. If a claim matters and is
cheap to test, test it.
