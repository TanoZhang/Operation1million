# Agent rules

Claude and Codex both work in this repo and follow the same rules. Detail lives in `docs/`.

## Before editing

1. Read the active claims in `docs/agent-protocol.md`.
2. Read the newest section of `docs/handoff.md`. Older sections are history.
3. Read the protected decisions in `docs/architecture.md` before changing existing behavior.
4. Add a claim: owner, scope, files, base commit, status, next step. Mark it `done` when finished.
5. Fetch before touching shared work. Settle disagreements with a test.
6. Never revert, stash, reset or overwrite the other agent's changes. Use a separate worktree if needed.

## Invariants

- The daily credit budget resets at 04:38 America/Los_Angeles. The 30-day billing cycle counts UTC dates. Keep the two clocks separate.
- Every paid request reserves its credit through `RequestGuard` before it is sent.
- SQLite is derived and rebuildable. The decision ledger and `operational/` are the durable record. Application decisions never go in SQLite.
- `first_seen` is when we first saw a posting, not when it was published.
- Hard rejects run before keeps and scores, and nothing overrides them. A word with an ordinary semiconductor meaning is not a hard reject by itself.
- Don't bypass access challenges, run two collectors at once, rewrite sealed logs, or bypass the 25% closure fuse. Read `docs/collection-rules.md` before collection work.
- A push doesn't deploy. `deploy/vps/install.sh` does (or `deploy/local/deploy-vps.bat`) and prints the installed commit.

## Public repo

This repo is public. The data repo, `Operation1million-data`, stays private.

- Never commit keys, `.env.local`, job records, application decisions, SQLite files, answer-bank content, or personal details.
- History is public too. Removing a file later does not unpublish it.

## Reporting

- English, UTF-8. Keep provider data as received.
- Say which commit you tested. Keep offline tests, production measurements, deployment and guesses apart.
- For a bug fix, show the failing case first.

## Where to look

| Need | Read |
| --- | --- |
| Who is changing what | `docs/agent-protocol.md` |
| Current state | newest section of `docs/handoff.md` |
| Design, invariants, fixed bugs | `docs/architecture.md` |
| Collection | `docs/collection-rules.md`, then `docs/jsearch.md` |
| VPS | `docs/vps-deployment.md` |
| Review page | `docs/application-review.md` |
| Code style | `docs/coding-standards.md` |
