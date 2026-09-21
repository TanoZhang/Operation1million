# Agent protocol

This document answers one startup question: who is changing what now? Completed
work belongs in the newest handoff, the architecture bug log, and Git history.

## Active claims
```text
Owner:   claude
Scope:   Twenty-nine reviewed defects from B1-B30, across collection completeness,
         posting identity, the experience gate, the applications ledger and Review
         server, rescore durability, paid-request accounting and both backup scripts.
Files:   src/jobdisco/{collector,store,applications,review,jsearch,collection_policy,
         experience,validate_sources}.py, review_static/app.js, deploy/{vps,local}/*.sh,
         tests/, docs/architecture.md
Base commit: ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1
Status:  done
Next:    Merged into main as df5898a with 455 offline tests passing. B20 is reverted
         as retracted; B27, B28 and B30 were defects in these fixes and are fixed
         here too. Not deployed: `deploy/vps/install.sh` has not run.
```

```text
Owner: codex
Scope: Systematic function-by-function offline audit of the text-to-Review path; consolidate variants by root cause and record coverage before moving between files.
Files: docs/file-audit-round8-2026-09-20.md, docs/audit-repro-round8-2026-09-20.py, docs/agent-protocol.md
Base commit: 7ecafb4a4494c9b6011c102b7156723e09465323
Status: claimed
Next: Complete experience.py, job_text.py, ranking.py, applications.py and Review server/UI function inventories with boundary tests and caller validation; report evidence and remaining scope.
```

```text
Owner: codex
Scope: Seventh offline audit of required-experience parsing and its paid-intake/Review effects.
Files: docs/file-audit-round7-2026-09-20.md, docs/audit-repro-round7-2026-09-20.py, docs/agent-protocol.md
Base commit: 1e42525
Status: done
Next: User reviews B31-B33 in docs/file-audit-round7-2026-09-20.md. Four defective inputs and three controls exercised through collector.main and Review on both source trees; no business-code changes.
```

```text
Owner: codex
Scope: Sixth offline audit of the user's pending fixes: identity replay, rejection matching, historical export and interrupted rescore.
Files: docs/file-audit-round6-2026-09-20.md, docs/audit-repro-round6-2026-09-20.py, docs/agent-protocol.md
Base commit: ba2cf0f5c8bd3ccddc193c19c0c642141d27b73c
Status: done
Next: User reviews B27-B30 in docs/file-audit-round6-2026-09-20.md. Four follow-up defects reproduced on pending fixes; source fingerprints recorded, no business-code edits.
```

```text
Owner: codex
Scope: Fifth offline audit of paid rejection updates and durable metadata, including correction of the invalid B20 finding.
Files: docs/file-audit-round5-2026-09-20.md, docs/audit-repro-round5-2026-09-20.py, docs/file-audit-round4-2026-09-20.md, docs/audit-repro-round4-2026-09-20.py, docs/agent-protocol.md
Base commit: d080ed1
Status: done
Next: User reviews B24-B26 in docs/file-audit-round5-2026-09-20.md. Three new cases reproduced through collector.main on both source trees. B20 retracted and its report/reproducer corrected; no application changes.
```

```text
Owner: codex
Scope: Fourth offline bug audit of rejected-row completeness, historical export, provider URL normalization and historical Review detail.
Files: docs/file-audit-round4-2026-09-20.md, docs/audit-repro-round4-2026-09-20.py, docs/agent-protocol.md
Base commit: 73fef06
Status: done
Next: User reviews B21-B23 in docs/file-audit-round4-2026-09-20.md. B20 was retracted in round 5 because its fixture bypassed main.direct; no priority labels or business-code changes.
```

```text
Owner:   unassigned
Scope:   Production verification that seen deduplication works, carried over from
         the register this file used to keep.
Files:   none; this needs a pass to run rather than anyone to edit code
Status:  blocked
Next:    The offline test is merged and requires a second pass to report 0 new /
         1 existing. Production reported 0 existing on three consecutive passes;
         the next pass is the first to run the same plan against a seen table
         holding its own rows.
```

```text
Owner: codex
Scope: Third offline audit of failure sealing, same-batch URL reuse and sitemap identity wiring; findings only, user owns implementation.
Files: docs/file-audit-round3-2026-09-20.md, docs/audit-repro-round3-2026-09-20.py, docs/agent-protocol.md
Base commit: c5db61a3f86592c16a79fbdc851fd30188a95504
Last inspected main: ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1
Status: done
Next: User reviews B17-B19 in docs/file-audit-round3-2026-09-20.md. All three reproduced on committed source and the user's uncommitted first-round fixes; no application code changed.
```

```text
Owner: codex
Scope: Second offline audit of identity transitions, durable recovery, Review concurrency and paid malformed payloads; findings only. User owns fixes from the first audit.
Files: docs/file-audit-round2-2026-09-20.md, docs/audit-repro-round2-2026-09-20.py, docs/agent-protocol.md
Base commit: a7572bec2e09b14506b7fd42152414c809d2d465
Last inspected main: ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1
Date: 2026-09-20
Status: done
Next: User reviews docs/file-audit-round2-2026-09-20.md for B10-B16, confirmed R02 and measured O08-O09. Seven new defects reproduced; 405 suite tests, eight skips, exit 0. No application code changed.
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

The row above is closed, but its files are worth naming: `collector.py`,
`store.py`, `applications.py`, `review.py`, `jsearch.py`, `collection_policy.py`,
`experience.py`, `validate_sources.py`, both backup scripts and their tests.
Several of those changes decide when a pass may call itself complete, which is
what permits the store to retire postings, and others change how a posting is
identified across providers and batches. Anyone touching `collect_json`,
`store.record_source` or `applications.decision_key` should read the four
review-round entries in the bug log first.

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

Merge into `main` only when both sides can be seen at once: fetch, read the
other branch's diff, resolve by taking the better answer rather than your own,
and run the suite on the merged tree before the merge stands. Say in the merge
what was taken from where. Two agents fast-forwarding `main` in turn is how one
of the two answers disappears without anyone having read it, and that rule left
this file when the entry point was shortened, which is why it is here now.

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
