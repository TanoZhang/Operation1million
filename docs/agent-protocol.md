# Agent protocol

This document answers one startup question: who is changing what now? Completed
work belongs in the newest handoff, the architecture bug log, and Git history.

## Active claims
```text
Owner: codex
Scope: Second offline audit of identity transitions, durable recovery, Review concurrency and paid malformed payloads; findings only. User owns fixes from the first audit.
Files: docs/file-audit-round2-2026-09-20.md, docs/audit-repro-round2-2026-09-20.py, docs/agent-protocol.md
Base commit: a7572bec2e09b14506b7fd42152414c809d2d465
Last inspected main: ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1
Date: 2026-09-20
Status: claimed
Next: Reproduce new boundary failures without editing application code or first-audit findings.
```

```text
Owner: codex
Scope: File-by-file offline audit; findings only, no behavior changes.
Files: docs/file-audit-2026-09-20.md, docs/audit-repro-2026-09-20.py, docs/agent-protocol.md
Base commit: b263553a7fe5ec47cd31c191134de8925a013c52
Last inspected main: ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1
Date: 2026-09-20
Status: done
Next: Review docs/file-audit-2026-09-20.md and prioritize fixes; no application code changed. Nine defects reproduced offline; existing suite 405 tests, eight skips, exit 0.
```

```text
Owner:   codex
Scope:   Reduce mandatory startup context and make current work mechanically visible.
Files:   AGENTS.md, docs/agent-protocol.md, docs/architecture.md, docs/handoff.md, docs/collection-rules.md
Base commit: ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1
Status:  review
Next:    Claude compares this compact version with its working-tree patch and merges the chosen result.
```

## Claim format

Add one block under **Active claims** before editing:

```text
Owner:   claude | codex
Scope:   one sentence describing the behavior being changed
Files:   exact paths expected to change
Base commit: full commit SHA
Status:  claimed | blocked | review | done
Next:    one concrete action or blocking condition
```

`Scope` and `Files` decide whether work overlaps. Disjoint claims proceed
independently. Overlapping claims require a fetch, comparison of both diffs, and
tests that settle the disagreement. Git is not a lock; the claim makes the
collision visible.

Update the block when scope changes. Set it to `review` when the branch is ready,
`blocked` only with a concrete blocker, and `done` promptly when the work is
finished. Remove completed blocks after their result is merged and recorded in
the handoff or architecture log. Do not leave dead claims in the active list.

## Branches

There are three standing remote branches:

| Branch | Meaning |
| --- | --- |
| `main` | Reviewed, tested, deployable truth |
| `codex` | Codex work awaiting review or integration |
| `claude` | Claude work awaiting review or integration |

Do not create a remote branch per problem. Use a worktree from your standing
branch for isolation. Push the standing branch before stopping so the other
agent can inspect it. A push does not mean merged or deployed.

## Synchronization

- Before claiming, run `git fetch origin`, inspect `HEAD..origin/main`, all three
  branch tips, the active claims, and the newest handoff.
- A fetch updates remote references, not an old worktree. Test the exact SHA you
  report and ensure imports come from that worktree.
- Before editing overlapping files, after an interruption, and before reporting
  or pushing, fetch again and inspect changes since the last known SHA.
- Never alter uncommitted work you did not create. Use another worktree if it
  blocks you.
- Preserve both implementations until overlap is compared. Choose by behavior
  and evidence, not authorship.

## Evidence and handoff

For a finding, record the inspected commit, file or function, trigger, expected
and actual behavior, and reproducer. Use precise states: suspected, reproduced,
fixed on branch, merged, deployed, or verified in production. An offline fixture
does not prove production incidence or provider coverage.

Update `docs/architecture.md` in the same commit for changed ownership, pipeline
order, protected decisions, or fixed bugs. Update only the newest handoff section
with current operating facts; never rewrite older snapshots into current advice.

When two agents collide, preserve both tips, compare from their merge base, run
the deciding tests, and record what resolved the difference. Commit authors
distinguish the agents: Codex uses `TanoZhang`; Claude uses `TanoZhang`.
