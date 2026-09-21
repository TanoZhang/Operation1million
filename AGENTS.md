# Start here

This file is the mandatory entry point, not the project manual. Current work,
system reasoning, operating detail, and history live under `docs/`.

## Before changing code

1. Read **Active claims** in [docs/agent-protocol.md](docs/agent-protocol.md).
2. Read only the newest section of [docs/handoff.md](docs/handoff.md) as current
   state. Older sections are historical evidence, not current instructions.
3. Read the protected decisions in
   [docs/architecture.md](docs/architecture.md) before changing existing behavior.
4. Claim the work before editing. Include scope, files, base commit, status, and
   next action.
5. Fetch before touching overlapping work. Compare the other diff and settle
   disagreements with tests.
6. Never revert, stash, reset, or overwrite another agent's changes to simplify
   your patch. Use a separate worktree when necessary.

Mark the claim `done` promptly. A stale claim is a false lock.

## Invariants

- The daily page-credit boundary is 04:38 `America/Los_Angeles`; the 30-day
  billing cycle uses UTC dates. Do not unify these clocks.
- Reserve every paid credit before its request leaves, through `RequestGuard`.
- SQLite is derived. The decision ledger and `operational/` state are durable.
  Application decisions never live in SQLite.
- `first_seen` records observation, not publication.
- Hard rejects run before keeps and scores and cannot be overturned. A word
  with an ordinary semiconductor meaning is not a hard reject by itself.
- Never bypass access challenges, overlap collector processes, rewrite sealed
  logs, or bypass the 25% closure fuse. Read
  [docs/collection-rules.md](docs/collection-rules.md) before collection work.
- A GitHub push does not deploy. `deploy/vps/install.sh` deploys and prints the
  installed commit.
- Keep both repositories private. Read
  [docs/publication-policy.md](docs/publication-policy.md) before publishing.

## Document order

| Need | Read |
| --- | --- |
| Current ownership and coordination | `docs/agent-protocol.md` |
| Current operating state | Newest section of `docs/handoff.md` |
| Ownership, pipeline, invariants, fixed bugs | `docs/architecture.md` |
| Collection or endpoint work | `docs/collection-rules.md`, then `docs/jsearch.md` for paid discovery |
| VPS operations | `docs/vps-deployment.md` |
| Review behavior | `docs/application-review.md` |

Use English and UTF-8 for project artifacts. Preserve original provider data.
Report the exact commit tested and distinguish offline evidence, production
measurement, deployment, and inference.
