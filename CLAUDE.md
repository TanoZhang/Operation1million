# Claude Code

**[AGENTS.md](AGENTS.md) is the rulebook for this repository. Read it first.**
It is shared with the other agent that works here, so that both of us are held
to the same rules rather than to whichever file our own tool happens to load.
Nothing in this file overrides it.

## Running things here

There is no `python` on PATH. Use the checkout's virtualenv:

    PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover -s tests

The suite is offline and takes about a minute. Run all of it before pushing;
`--jsearch` tests use fixtures and spend nothing.

`data/db/job_discovery.sqlite` is derived, gitignored, and may be absent. Tests
that need a real store skip without one, so a green run in a fresh checkout
proves less than a green run against a collected database. Where a check is
worth doing against real rows, say so rather than trusting the skip.

## Reporting

Say what was measured and what was assumed, and keep them apart. "Tested on the
VPS as ubuntu: it copies all 41,029 postings" and "a read-only WAL connection
should need write access to -shm" are different kinds of claim, and this
repository has already shipped a wrong one of the second kind stated as the
first. When a claim is load-bearing and cheap to test, test it.
