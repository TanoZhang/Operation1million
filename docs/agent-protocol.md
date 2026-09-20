# Two agents, one repository

Claude Code and Codex both work here. Neither can see the other: each reads the
repository once, forms a picture, and then works for hours against a picture
that has since stopped being true. Everything below exists because that has
already cost this project real work.

**What it has cost, so far.** The same SQLite snapshot built twice. The same
two bugs -- internship queries never sent, the budget day resetting at a time
nothing observes -- found and fixed twice, independently, in two different
ways. Two review documents rewritten twice. Three merges that had to be
reasoned through by hand.

Overlap itself is not the problem: finding the same bug twice is a signal the
bug is real, and the two fixes disagreeing is where the interesting information
is. The problem is finding it twice *without knowing*, and losing one of the
two answers to whoever pushed last.

## The register

**Update this before you start, and when you finish.** It is the one mechanism
that prevents duplicate work, and it only works if it is current.

| Area | Owner | Status | Notes |
| --- | --- | --- | --- |
| Agent synchronization and review protocol | Codex | in progress | Branch `codex/agent-sync-protocol`; base and last inspected main `a960195`; 2026-09-19; documentation only |
| `experience.py`, the required-experience gate | Codex | done, merged | Deterministic years parsing, intern/new-grad override |
| `jsearch_queries.toml` query plan and tiers | Codex | done, merged | 36 queries, intern/new_grad/early_career/A |
| `jsearch_access.py` budget accounting | shared | done, merged | Codex's window counting, Claude's configuration |
| `ranking.py`, review bands and ordering | Claude | done, merged | |
| `evidence_title_patterns`, hard-reject audit | Claude | done, merged | |
| `docs/architecture.md` and the bug log | Claude | done, merged | Keep current with every change |
| VPS deployment and `--rescore` | Claude | done | `5937594` installed 2026-09-19 23:05 UTC; 41,073 postings rescored |
| Verifying the new query strings return results | unassigned | **pending** | First real test is the 2026-09-20 11:38 UTC pass |
| Confirming seen deduplication works | unassigned | **pending** | `seen_existing` has been 0 on every pass so far |

Claiming an area means writing your name in it before you write code. If the
area you want is already claimed and you think the owner is wrong, say so to
the user rather than building a second answer in silence.

## Rules

1. **Fetch before you plan, not before you push.** `git fetch origin` and
   `git log HEAD..origin/main` in the first minute. Also check for branches:
   `git ls-remote --heads origin`. Work is routinely parked on one.

2. **Never commit in `/opt/jobdisco/code`.** That is the production checkout the
   scheduled pass runs from, not a workspace. Committing there put two commits
   on a single disk, left the checkout thirteen commits ahead of its origin,
   and broke `install.sh`, which merges `--ff-only` and refuses to discard
   them. Work in a clone or a worktree.

3. **Push before you stop.** Work that exists on one machine is work that can
   vanish with it. A branch is enough; it does not have to be `main`.

4. **Branch, do not race `main`.** `codex/<topic>`, `claude/<topic>`. Two agents
   fast-forwarding `main` in turn is how one of two answers disappears without
   anyone reading it.

5. **When your work overlaps theirs, compare and test.** Do not quietly prefer
   your own. Find the point where the two disagree and settle it by running
   something. Then say what decided it. That comparison is the value being paid
   for here, and it has already corrected a confident wrong claim in both
   directions.

6. **Record fixed bugs in `docs/architecture.md`.** Without the log, a decision
   that was settled by evidence gets re-argued from scratch, and sometimes
   "fixed" back. The daily budget resetting at a UTC midnight looked like a
   design choice until the ledger was read; the cycle staying on UTC looks like
   the same bug until you know a test already guards it.

7. **Say which claims were tested.** "Tested on the VPS as ubuntu: it copies all
   41,029 postings" and "a read-only WAL connection should need write access to
   -shm" are different kinds of statement. This repository has already shipped a
   wrong one of the second kind stated as the first.

## Telling the two apart

Author fields distinguish them in history:

| Author | Agent |
| --- | --- |
| `TanoZhang <132003493+TanoZhang@...>` | Codex |
| `TanoZhang <tanozhang@users.noreply.github.com>` | Claude Code |

When you commit work the other agent wrote, say so in the message, because the
field will not.

## When they collide anyway

1. Get both lines somewhere durable first. `git bundle create` over SSH, or a
   branch push. Preserve before you reconcile.
2. Find the merge base and read both sides of the divergence in full.
3. Resolve by property, not by authorship: for each overlapping piece, decide
   which is better and why, and say so in the merge message.
4. Run the whole suite on the merged result before pushing.
