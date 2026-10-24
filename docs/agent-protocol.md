# Agent protocol

This document answers one startup question: who is changing what now? Completed
work belongs in the newest handoff, the architecture bug log, and Git history.

## Active claims
```text
Owner: claude
Scope: User request (2026-10-23): Japan's big employers read directly -- 16
       HRMOS boards, Hitachi and Subaru on jposting, Infineon (Eightfold), ADI
       and Microchip (Workday); a large no-store collection, debugging what
       fails.
Files: data/config/migrations/012_japan_more_direct.sql,
       data/config/{schema.sql,japan_employers.toml,jsearch_queries.toml},
       src/operation1million/{store,collector,employers}.py,
       tests/{test_collect_sql_sources,test_japan_boards,test_japanese_postings}.py,
       docs/{agent-protocol,handoff}.md
Base commit: f9571e0
Status: done -- no-store 21/21 complete; suite 1,316 run, 13 skipped, pass;
        pushed, not installed (the user, 2026-10-23: no VPS).
Next: Install when the user says; then the readers the survey names
      (jposting HTML lists, sonar, axol, ZOOKEEP, Rapidus).
```

```text
Owner: claude
Scope: User request (2026-10-19): Obsidian notes over WebDAV on the VPS at
       /notes/; Review by password alone; fail2ban.
Files: deploy/vps/{Caddyfile,notes-route.caddy,operation1million-notes.service,
       notes-password.sh,review-password.sh,install.sh,fail2ban/*},
       src/operation1million/{review,review_login}.py, tests/test_review_proxy.py,
       docs/{agent-protocol,handoff,vps-deployment}.md
Base commit: e8424ee
Status: done in code; live once the user runs review-password.sh, then
        notes-password.sh.
Next: The user sets both passwords and connects Remotely Save.
```

```text
Owner: claude
Scope: User request (2026-10-18): merge the rotation branch; Gmail preview;
       unrelated titles with no JD not offered; closure fuse, TSMC, Qualcomm;
       log size.
Files: src/operation1million/{applications,collection_policy,gmail_outcomes,
       job_details,store}.py, tests/{test_review_rules,test_ranking,
       test_gmail_outcomes,test_job_details,test_store}.py,
       docs/{agent-protocol,handoff,collection-rules}.md
Base commit: f1cef5a
Status: done -- suite 1,288 run, 13 skipped, pass; pushed and installed.
Next: None -- stale postings retired on the VPS (308 SanDisk, 1,936
      Microsoft); day logs slimmed (handoff, "Day logs under 50 MB").
```

```text
Owner: claude
Scope: User request (2026-10-17): two-day query rotation, a per-query run
       record, the plan chosen by measurement (general queries back, STA
       kept, timing/custom layout/FPGA design dropped), accelerator, AI/car
       and jd_text trials.
Files: data/config/jsearch_queries.toml, src/operation1million/{jsearch,
       jsearch_access,collector,workflow_state,store}.py, tests/test_jsearch.py,
       deploy/vps/{daily-pass,data-sync}.sh,
       docs/{jsearch,handoff,agent-protocol}.md
Base commit: ee0b847
Status: done -- 1,275 run, 13 skipped, pass. Not installed.
Next: Install; measure spend and the trial tiers from jsearch_query_runs.ndjson.
```

```text
Owner: claude
Scope: User request (2026-10-17): Gmail Passed/Declined reads -- a SharkNinja
       reply identified wrong; invitations told as instructions, courtesy
       conditions, short-title and sender-domain matching, --explain.
Files: src/operation1million/gmail_outcomes.py, tests/test_gmail_outcomes.py,
       docs/{agent-protocol,handoff}.md
Base commit: 99e2016
Status: done -- 9000354, c44f2c6 (legal footer), then "continue to apply"
        and unstarring a reply no longer read Passed; 1,266 run, 13 skipped, pass.
Next: Install on the VPS; the next Gmail pass re-reads every cached email
      under the new rules and clears the wrong mark by itself.
```

```text
Owner: claude
Scope: User request (2026-10-16, external review): remove three features that
       cannot run -- company fallback search (company_fallbacks = []), the
       legacy search_queries catalog, and the newest-first incremental
       strategy (MONOTONIC_NEWEST_FIRST empty since #317). No behavior change.
Files: src/operation1million/{collector,jsearch,store,query_catalog}.py,
       data/config/{schema.sql,discovery_queries.toml,migrations/001_search_queries.sql},
       pyproject.toml, tests/{test_search_queries,test_audit_recovery,
       test_collect_sql_sources,test_collection_policy,test_jsearch,test_store}.py,
       docs/{agent-protocol,handoff,architecture,search-queries,jsearch}.md
Base commit: d2b80e7
Status: done -- committed with round four of the review (the user, 2026-10-17:
        merge everything, push, deploy); --bootstrap matches d2b80e7's except
        the removed table.
Next: None.
```

```text
Owner: claude
Scope: User request (2026-10-16): every Applied entry has a JD -- list the
       ones without for the user to ask Muse, read what Muse supplies; merge
       a decided import with the queue's listing of the same opening.
Files: src/operation1million/{applied_jd (new),export,review,manual_intake}.py,
       review_static/app.js, deploy/vps/{daily-pass,data-sync,backup-applications}.sh,
       tests/test_applied_jd.py (new), docs/{agent-protocol,handoff,application-review}.md
Base commit: d2b80e7
Status: done -- committed from a separate worktree (another session was
        editing the main checkout); suite 1,265 run, 14 skipped, pass.
Next: Install; give Muse operational/applied-missing-jd.json after the next pass.
```

```text
Owner: claude
Scope: External review (2026-10-16): run the offline suite in GitHub Actions
       on every push and pull request to main, on Ubuntu. Then (the user,
       2026-10-17, "you decide"): the nightly pass runs the suite only
       under --preflight.
Files: .github/workflows/tests.yml, deploy/vps/daily-pass.sh,
       tests/test_prelaunch_fixes.py,
       docs/{agent-protocol,architecture,github-actions,vps-deployment}.md
Base commit: d2b80e7
Status: done -- CI merged (PR #2, ubuntu-24.04: 1,256 run, 1 skipped);
        nightly change pushed, not installed.
Next: Install on the VPS when the user asks; run a preflight after it.
```

```text
Owner: claude
Scope: User request (2026-10-16): three rounds of an external review --
       bugs, compaction, the "Third-party site" meaning (job-board apply),
       and skip reasons on the Skipped tab.
Files: data/config/migrations/011_jobs_requisition.sql, .github/workflows/collect-backup.yml,
       src/operation1million/{store,manual_intake,applications,gmail_outcomes,
       jsearch,jsearch_access,location,collector,export,experience,ranking,
       review,apple,collection_policy,job_details}.py,
       src/operation1million/review_static/{app.js,index.html,style.css},
       tests/{test_external_review,test_review_export,test_manual_intake,
       test_workflow_state,test_apple_details,test_collect_sql_sources}.py,
       tests/review-company-tab.cjs, tests/test_{jsearch_access,ledger_guard,prune,
       queue_snapshot,review_payload,store,validator_resources,jsearch}.py,
       docs/{agent-protocol,handoff,architecture,application-review}.md
Base commit: 7c7ff44
Status: done -- d2b80e7 pushed, not installed (the user, 2026-10-16); fourth round
        (jsearch_access, quiet tests) in the working tree; suite 1,258 run, 13 skipped, pass.
Next: Install on the VPS when the user asks; the "Not done" list
      in the newest handoff.
```

```text
Owner: claude
Scope: User request (2026-10-16): fill the JDs missing from Applied entries
       (mostly Muse submissions) -- the detail pass also reads postings with a
       decision, whatever their title; and Muse's daily-new files.
Files: src/operation1million/{collector,job_details,manual_intake,export}.py,
       deploy/vps/daily-pass.sh,
       tests/{test_job_details,test_manual_intake,test_review_export}.py,
       docs/{agent-protocol,handoff,application-review}.md
Base commit: 1fc276c
Status: done -- pushed and installed on the VPS (2026-10-16); Windows suite 1,237 run, 13 skipped, pass.
Next: Check the next pass reads the ~272 applied postings and writes daily-new files.
```

```text
Owner: claude
Scope: User request (2026-10-16): last cycle's applications and credits; many
       more Japan phrases for the closing sweep; the role photo's titles;
       slim code, tests and docs without changing behavior. Also removed the
       finished claims from this file (their record is in handoff and Git) and
       closed claude's own stale "active" rename and outcome claims.
Files: data/config/jsearch_queries.toml, deploy/vps/daily-pass.sh,
       src/operation1million/{collector,jsearch,ledger_guard,ranking,store}.py,
       tests/{test_jsearch,test_applications,test_application_outcomes,
       test_ledger_guard,test_ranking,test_collection_policy}.py, docs/{agent-protocol,handoff,jsearch}.md,
       docs/file-audit-*.md and docs/audit-repro-*.py (removed)
Base commit: 0a57754
Status: done -- pushed, not installed (the user, 2026-10-16); Windows suite 1,234 run, 13 skipped, pass.
Next: Install on the VPS when the user asks; measure the 2026-11-12..14 sweep.
```

```text
Owner: codex
Scope: Analyze the previous 30-day JSearch billing cycle and current balance, raise the new cycle's target to 10,000 and resolve unused closing credits, assess the supplied role image without narrow paid keywords, mark the six referalble employers in Muse's private queue, and remove demonstrated redundant work.
Files: docs/{agent-protocol,handoff,application-review,jsearch}.md,
       data/config/jsearch_queries.toml,
       src/operation1million/{collector.py,export.py,review_static/app.js},
       deploy/vps/daily-pass.sh,
       tests/{test_jsearch,test_prelaunch_fixes,test_review_export}.py,
       .local/{september-audit,query-audit,profile-tests,photo-titles,muse-inspect,cycle-audit}.py,
       private data repository operational/review_queue.csv.
Base commit: 206cc08158cb3f4533fea64025665ac0247c8b2b
Status: done -- code commit 8720c37 passed the 1,311-test offline suite
        (14 skipped) and was installed on the VPS; private Muse data commit
        740517f contains 115 marked listings out of 1,929. The Review service
        is active and the current-cycle balance was verified read-only.
Next: Measure new-cycle query yield and final-day Japan-first/U.S. fallback
      when those scheduled runs occur.
```

```text
Owner: codex
Scope: Put open Tesla, TikTok, NVIDIA, Renesas, Cisco and Amazon Review positions together on one referalble tab, without duplicate open-tab listings.
Files: src/operation1million/review_static/{app.js,index.html,style.css}, tests/{review-company-tab.cjs,test_review_payload.py}, docs/{agent-protocol,handoff,application-review}.md
Base commit: ff0604f2d2a0fcc4554c852d85152c7b195d4bbc
Status: done -- 8f5acc6 passed the routing test and full offline suite
        (1,308 run, 14 skipped); installed on the VPS, Review service active,
        and the served page contains the referalble tab.
Next: None.
```

```text
Owner: claude
Scope: User request (2026-10-09): fix the VPS's failing offline tests (61
       failures, 5 errors on 6fee617) and the partial direct sources (Cisco,
       Qualcomm, Apple, Amazon, Rivos, Microsoft paused, SanDisk empty).
Files: deploy/vps/daily-pass.sh, src/operation1million/{jsearch,collector}.py,
       tests/{test_prelaunch_fixes,test_more_performance,test_collector*}.py,
       docs/{agent-protocol,handoff,collection-rules}.md
Base commit: 82b8856
Status: tests, Cisco, Apple, Qualcomm done -- 045f16e + 33fd72b installed
        (install.sh: Caddy's apt list answers 402). Daily-pass test step on
        the VPS: 1,268 run, 0 skipped, all pass.
Next: The user decides Amazon (partition, log size), SanDisk (Avature
      route; 308 old postings behind the fuse), Microsoft (429 / fuse),
      and whether a detail failure should stop closures.
```

```text
Owner: codex
Scope: Preserve first discovery for stable LinkedIn postings with rotating search IDs; suppress confirmed Workday copies by employer/title/requisition evidence; audit the latest query yield without changing the user's query plan.
Files: src/operation1million/{store,applications,jsearch,jsearch_access,workflow_state}.py, tests/{test_discovery_identity,test_jsearch,test_jsearch_plan_bugs,test_workflow_state}.py, docs/{agent-protocol,architecture,handoff,jsearch}.md
Base commit: 8a57617
Status: active
Next: Identity patch 57c2381 installed. One guarded paid probe proves search-v2 returns a cursor with five jobs; fix incorrect page-number/short-page termination, then verify duplicate consolidation and query yield.
```

```text
Owner: codex
Scope: Audit current JSearch page yield, restore VLSI analog interns, trial ten General-tier VLSI synonyms, and close request-level publisher gaps; preserve intern, new-grad and early-career query plans.
Files: src/operation1million/{jsearch,applications}.py, data/config/jsearch_queries.toml, tests/{test_jsearch,test_manual_intake,test_review_rules,test_twelfth_bug_hunt}.py, docs/{agent-protocol,architecture,blocked-recruitment-domains,collection-rules,handoff,jsearch}.md
Base commit: be17f1d
Status: halted at user request; installed 4e6789e, collector service and timer stopped, no paid pages on October 3.
Next: Do not resume or modify JSearch unless the user explicitly asks.
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
the deciding tests, and record what resolved the difference. Commit authors do
not tell the agents apart; the claim's `Owner` line does.
