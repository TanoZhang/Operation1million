# Agent protocol

This document answers one startup question: who is changing what now? Completed
work belongs in the newest handoff, the architecture bug log, and Git history.

## Active claims
```text
Owner: codex
Scope: Continue offline Review/eligibility audit and measure behavior-preserving code-size, structure and algorithm improvements; no database or behavior changes.
Files: docs/review-audit-round2-2026-09-23.md, docs/review-audit-repro-round2-2026-09-23.py, docs/review-benchmark-2026-09-23.py, docs/{agent-protocol,handoff}.md; architecture HTML report in OS temp directory
Base commit: 8f95b07f2cf21a9f985983b105278f36a7d0516f (application source b2c9340)
Last inspected main: b2c9340f84dbe5f7fb020301c2d724af32587424
Branch: local codex/review-audit, published to standing remote codex
Date: 2026-09-23 UTC
Status: done
Next: Review R4-R7 and three improvement candidates in docs/review-audit-round2-2026-09-23.md. Four new defects reproduce; 43 existing tests pass with isolated optimization prototypes. Description reuse measures 1.90x faster; sort caching depends on input reuse. Application source and real databases are unchanged.
```

```text
Owner: codex
Scope: Offline audit of the latest PhD eligibility, description refresh and Review display changes; reproducible findings only.
Files: docs/review-audit-2026-09-23.md, docs/review-audit-repro-2026-09-23.py, docs/{agent-protocol,handoff}.md
Base commit: b2c9340f84dbe5f7fb020301c2d724af32587424
Last inspected main: b2c9340f84dbe5f7fb020301c2d724af32587424
Branch: local codex/review-audit, published to standing remote codex
Date: 2026-09-23 UTC
Status: done
Next: Review three reproduced defects: empty HTML refresh loses the teaser, null teaser retains obsolete requirements, conditional PhD wording rejects. Existing 177 focused tests pass; six-case reproducer has three failures and three passing controls. No application code changed or deployed.
```

```text
Owner:   claude
Scope:   Review detail shows the paid description beside qualification-only
         fields instead of hiding it; add deploy/local/open-review.bat.
Files:   src/jobdisco/job_text.py, tests/test_review_description.py,
         deploy/local/open-review.bat, docs/{agent-protocol,handoff}.md
Base commit: 78c8f8e
Status:  done -- pushed to main, not deployed
Next:    Deploy with deploy/vps/install.sh when wanted.
```

```text
Owner:   claude
Scope:   PhD-only wording that is really a preference (desirable, advantage,
         encouraged, ideal, "Ph.D. Preferred", preference headings after a
         required section); stale teaser surviving a full-description update;
         "If selected for a role that requires..." read as a firm citizenship
         requirement.
Files:   src/jobdisco/{degree,store,jsearch}.py, tests/{test_degree,
         test_store,test_review_rules}.py, docs/{agent-protocol,architecture,
         handoff}.md
Base commit: 583bfd7
Status:  done -- pushed to main, not deployed
Next:    Deploy with deploy/vps/install.sh when wanted. Local index: zero
         verdict changes over 38,193 open postings.
```

```text
Owner: codex
Scope: Validate, commit and push accumulated audit fixes to main, then deploy and verify the VPS.
Files: Current eleven-file audit patch; deployment status documentation.
Base commit: c1a322edddd54aaa0a34edff8cded252cce2d99d
Status: done
Next: Release cc8bd4a pushed and deployed; 639 local tests (nine skips), 178 VPS tests passed, live queue and detail HTTP 200. Sync deployment-record commit.
```

```text
Owner: codex
Scope: Preserve nested qualification objects and arrays in Review details.
Files: src/jobdisco/job_text.py, tests/test_review_description.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: c1a322e plus current working tree
Status: done
Next: Review nested qualification fix; new HTTP regression red before fix, all 132 focused tests green after. Not deployed.
```

```text
Owner: codex
Scope: Preserve unique teasers, qualification section meaning and literal type names beside HTML entities.
Files: src/jobdisco/{store,job_text,review}.py, tests/{test_store,test_review_description}.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: c1a322e plus six-fix working tree
Status: done
Next: Review follow-up patch. All 131 focused storage and HTTP/payload tests pass. Not deployed.
```

```text
Owner: codex
Scope: Fix six post-location audit findings: stale HTML, structural dedupe, citizenship clause scope, empty descriptions, qualification display and malformed raw payloads.
Files: src/jobdisco/{store,job_text,jsearch,applications,review}.py, tests/test_review_description.py, tests/test_review_rules.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: c1a322e
Status: done
Next: Review patch on c1a322e. Full offline suite: 635 discovered, 626 passed, nine environment skips. Not deployed.
```

```text
Owner: codex
Scope: Separate degree text preparation from qualification policy and improve documentation navigation; preserve behavior.
Files: src/jobdisco/degree.py, docs/{agent-protocol,handoff,architecture}.md
Base commit: feda989aa91d407408f2df1d21e6f5eb8f985407
Status: done
Next: Review structure-only refactor. All 89 focused tests pass; 38,302 local postings have identical before/after degree verdicts.
```

```text
Owner: codex
Scope: Normalize coding practices and withdraw export/field-removal changes following the user's lossless-only clarification.
Files: src/jobdisco/{degree,jsearch}.py, docs/{coding-standards,agent-protocol,handoff}.md
Base commit: feda989aa91d407408f2df1d21e6f5eb8f985407
Status: done
Next: Continue measured lossless storage design under docs/coding-standards.md. All 89 focused tests pass; no deployment.
```

```text
Owner: codex
Scope: Fix PhD-only preference and structured-section boundary errors; centralize hard eligibility checks; no deployment.
Files: src/jobdisco/{degree,jsearch,applications}.py, tests/{test_degree,test_review_rules}.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: feda989aa91d407408f2df1d21e6f5eb8f985407
Status: done
Next: Review local patch; latest alternative-scope fix and regex reuse pass all 89 focused tests. Not deployed.
```

```text
Owner:   claude
Scope:   Review queue filters and order at the user's direction, 2026-09-22:
         screened and merged codex (B68-B84, answer bank, sort, domain lists),
         and deployed each step to the VPS.
Files:   src/jobdisco/{applications,review,jsearch,experience,ranking,
         location,degree,store,job_text}.py, review_static/, data/config/
         jsearch_queries.toml, deploy/, tests/, docs/
Base commit: 5e78ae8
Status:  done -- main and the VPS at 886e375
Next:    See the newest handoff. Filter changes must be measured on the live
         queue and their removals read before deploying.
```

```text
Owner: codex
Scope: Add the user's eight explicit domain exclusions; no deployment.
Files: data/config/jsearch_queries.toml, tests/test_review_rules.py, docs/{blocked-recruitment-domains,agent-protocol,architecture,handoff}.md
Base commit: b9c7d90970300a864a9675b3acc36a337d2161d0; fetched main remains d9aed44
Status: done
Next: Review codex domain additions. All 35 offline Review rules tests pass, covering all 21 domain entries. Not deployed.
```

```text
Owner: codex
Scope: Evidence-backed recruitment domain blocklist; preserve preference blocks; no deployment.
Files: data/config/jsearch_queries.toml, src/jobdisco/jsearch.py, tests/test_review_rules.py, docs/{blocked-recruitment-domains,agent-protocol,architecture,handoff}.md
Base commit: d9aed44 (fetched and fast-forwarded before editing)
Status: done
Next: Review codex evidence-backed blocklist. All 134 offline Review/filter tests pass. No deployment or production measurement.
```

```text
Owner: codex
Scope: Review UI defaults to descending Fit with selectable original ordering; no deployment.
Files: src/jobdisco/review_static/{app.js,index.html,style.css}, docs/{agent-protocol,architecture,handoff}.md
Base commit: ef978587e19c0ca99d670ef6bef0ea23d9cbb808 (origin/main de12047 merged before editing)
Status: done
Next: Review codex Fit ordering. Node behavior checks passed; full suite 584 discovered, 574 passed, 10 environment skips. Not deployed.
```

```text
Owner: codex
Scope: Enforce position context for imported job-specific autofill answers; local personal data stays ignored.
Files: src/jobdisco/answer_bank.py, tests/test_answer_bank.py, docs/{answer-bank,agent-protocol,architecture,handoff}.md
Base commit: 53b51452ed64ef365879cb78d5bde958a9342497
Status: done
Next: Review codex position-context guard. Seventeen offline tests pass; 27 local imported answers verified, two require the matching position. No browser submission or deployment.
```

```text
Owner: codex
Scope: Local reusable answer bank, scoped question learning and extensible personal fields; no browser filling or deployment.
Files: src/jobdisco/answer_bank.py, tests/test_answer_bank.py, pyproject.toml, docs/{answer-bank,agent-protocol,architecture,handoff}.md
Base commit: bcfe9533292e5c6fb0f2c1327b4af6de88574319
Status: done
Next: Review codex answer-bank implementation. Local empty bank created; 16 focused tests pass; full suite 569 discovered, 559 passed and 10 environment skips. Browser reader/filler is a separate integration step.
```

```text
Owner: codex
Scope: Implement and regression-test B68-B84 from audits 13-15; no deployment.
Files: deploy/local/, deploy/vps/backup-snapshot.py, deploy/vps/compact-history.sh, deploy/vps/daily-pass.sh, src/jobdisco/{collection_policy,collector,validate_sources,jsearch,query_catalog,store,review}.py, tests/, docs/{agent-protocol,architecture,handoff,vps-deployment}.md
Base commit: 34a77f6d0b8694b71d5582cf43aac388254c90a2
Status: done
Next: Review and integrate codex. B68-B84 fixed with offline regressions; 544 tests discovered, 535 pass, nine environment skips. No deployment. See newest handoff and architecture bug log.
```

```text
Owner: codex
Scope: Fifteenth offline audit: source identity moves, snapshot replay, interrupted sharded writes, and Review cache dependencies; findings only.
Files: docs/file-audit-round15-2026-09-21.md, docs/audit-repro-round15-2026-09-21.py, docs/agent-protocol.md
Base commit: 4064c55
Inspected main: 5e78ae814514115866532bf96f8397d0331354d2
Status: done
Next: User reviews B81-B84, remaining R02 and B23/B27 paths, and measured O10 in docs/file-audit-round15-2026-09-21.md. All offline cases pass; 193 existing tests pass without skips. Next: provider response-shape and pagination contracts. No business-code edits.
```

```text
Owner: codex
Scope: Fourteenth offline audit: complete source validator, query catalog, credential loader, and configuration validation contracts; findings only.
Files: docs/file-audit-round14-2026-09-21.md, docs/audit-repro-round14-2026-09-21.py, docs/agent-protocol.md
Base commit: 74bec6a61db21250f4d86fb746c2182f16853dbc
Inspected main: 5e78ae814514115866532bf96f8397d0331354d2
Status: done
Next: User reviews B74-B80 in docs/file-audit-round14-2026-09-21.md. Seven offline cases and adapter/credential controls pass; 118 existing tests pass without skips. Validator, legacy query catalog and credential loader function inventories complete. No provider probing or business-code edits.
```

```text
Owner: codex
Scope: Thirteenth offline audit: deployment, backup and workflow scripts, function by function; findings only.
Files: docs/file-audit-round13-2026-09-21.md, docs/audit-repro-round13-2026-09-21.py, docs/agent-protocol.md
Base commit: 5e78ae814514115866532bf96f8397d0331354d2
Status: done
Next: User reviews B68-B73 in docs/file-audit-round13-2026-09-21.md. Six offline cases pass; 52 existing tests discovered, 44 executed and 8 platform skips. Complete deployment/workflow inventory recorded. Next: configuration/catalog validation and local credentials. No production requests or business-code changes.
```

```text
Owner:   claude
Scope:   B63-B67 from the twelfth audit, and deployment of main to the VPS.
Files:   src/jobdisco/{jsearch,collection_policy,ledger_guard}.py,
         deploy/vps/daily-pass.sh, tests/, docs/
Base commit: 72e93e00436601c22404043c8087713cd2670928
Status:  done
Next:    Deployed. Watch the 11:38 UTC pass: it rebuilds the index from the log
         and reads every Eightfold board in full, once.
```

```text
Owner:   claude
Scope:   B58-B62 from the eleventh audit: teaser descriptions, batch order of a
         moved requisition, shard size, superseded paid descriptions, and a day
         that seals mid-pass.
Files:   src/jobdisco/{store,collector,jsearch}.py, tests/test_store.py, docs/
Base commit: ca501dc41640a09c0650d92bcb12ddddbf2025ca
Status:  done
Next:    Merged into main; 515 offline tests pass.
```

```text
Owner:   claude
Scope:   B50-B57 from the tenth audit and the direct-intake half of B45: HiBob
         batch preparation, Eightfold incremental reconciliation, page-scoped
         validators, links built from missing ids, rejected pages read as
         repeats, --no-store, partial JSON-LD, and sitemap detail text.
Files:   src/jobdisco/{collector,store}.py, data/config/migrations/006_source_full_pass.sql,
         tests/, docs/
Base commit: 79fe1690dee09a7c8d4afc11e1679eb7ae24a6cd
Status:  done
Next:    Merged into main; 509 offline tests pass. Install runs migration 006, and
         the first pass reads every Eightfold board in full. Corrects a false B26
         claim about stored validators.
```

```text
Owner: codex
Scope: Twelfth offline audit: quota, pacing, ledger comparison and workflow cursor recovery, function by function; findings only.
Files: docs/file-audit-round12-2026-09-21.md, docs/audit-repro-round12-2026-09-21.py, docs/agent-protocol.md
Base commit: 6dc9a0510d2088baa7db28c9b8ee1f19402a2e11
Inspected main: ca501dc41640a09c0650d92bcb12ddddbf2025ca
Status: done
Next: User reviews B63-B67 in docs/file-audit-round12-2026-09-21.md. Four-module function inventory complete; five offline cases and recovery control pass, 121 existing tests pass. B67 combines executed filesystem simulation with traced VPS caller code. Next: full deployment/configuration audit. No business-code edits.
```

```text
Owner: codex
Scope: Eleventh offline audit: complete store.py function inventory, identity, persistence, replay and recovery; findings only.
Files: docs/file-audit-round11-2026-09-21.md, docs/audit-repro-round11-2026-09-21.py, docs/agent-protocol.md
Base commit: e5c9440ff707eadc44a679d63de5beafcaf48542
Inspected main: 79fe1690dee09a7c8d4afc11e1679eb7ae24a6cd
Status: done
Next: User reviews B58-B62 in docs/file-audit-round11-2026-09-21.md. Full store function inventory recorded; five defects reproduced on baseline and concurrent user fixes, 175 existing baseline tests passed. Next: quota/pacing and ledger/workflow recovery. No business-code edits.
```

```text
Owner: codex
Scope: Tenth offline audit: function-by-function collector.py inspection, provider adapters, pagination and failure-to-store contracts; findings only.
Files: docs/file-audit-round10-2026-09-21.md, docs/audit-repro-round10-2026-09-21.py, docs/agent-protocol.md
Base commit: 79fe1690dee09a7c8d4afc11e1679eb7ae24a6cd
Status: done
Next: User reviews B50-B57 and the remaining direct-intake B45 instance in docs/file-audit-round10-2026-09-21.md. Complete collector function inventory recorded; all cases and 19 positive adapter controls reproduced offline, 119 existing tests passed. Next module is store.py; no business-code changes.
```

```text
Owner: codex
Scope: Ninth offline audit, complete function inventory of jsearch.py and concrete intake, filtering and cursor failure cases; findings only.
Files: docs/file-audit-round9-2026-09-20.md, docs/audit-repro-round9-2026-09-20.py, docs/agent-protocol.md
Base commit: 5166930b284bb070f38865685ec279c7d545de2f
Status: done
Next: User reviews B44-B49 in docs/file-audit-round9-2026-09-20.md. Full JSearch function inventory recorded; six root causes reproduced offline, existing 90 JSearch tests pass. Next module is collector.py. No paid requests or business-code edits.
```

```text
Owner:   claude
Scope:   B44-B49 from the ninth audit: provenance read as prose, records emptied
         by cleaning, joined filter patterns, the backfill cursor on an
         unreadable last page, link selection, and field order in structured
         payloads.
Files:   src/jobdisco/{jsearch,experience,collector}.py, tests/test_jsearch.py, docs/
Base commit: 1aa84564c7a22311f6ce51b5bb9d8cb9e446b9c0
Status:  done
Next:    Merged into main; 498 offline tests pass. After install, run
         `job-store --rescore`: stored scores include the search phrase.
```

```text
Owner:   claude
Scope:   Bug check of the review path and the store CLI: the outstanding B27
         instance (a replacement requisition inheriting a decision through a
         provider move), the review queue cache missing a pass that is still
         running (WAL sidecar), `--ranked 0` printing nothing, and `--verify`
         creating the index it checks. Plus the first run of review_static/app.js
         in a JavaScript runtime, confirming B41-B43 behaviourally.
Files:   src/jobdisco/{applications,review,store}.py,
         tests/{test_applications,test_store}.py, docs/
Base commit: 5166930
Status:  done
Next:    On branch claude/bug-check-8k1k7r; 491 offline tests pass, one skip.
         Each new test is red against the code before its fix. Not deployed:
         `deploy/vps/install.sh` has not run. The app.js harness is not
         committed -- it needs an npm install and the suite is offline -- so
         that measurement is made here and is not repeated by the suite.
```

```text
Owner:   claude
Scope:   B31-B43 from the seventh and eighth audits -- the experience parser's
         unreadable requirements, title cleaning, the paid rejection record, the
         Review description panel and the page's dates, refresh and skip dialog --
         and seven equivalent optimizations measured before and after.
Files:   src/jobdisco/{experience,job_text,jsearch,review,applications,collector,
         store}.py, review_static/app.js, pyproject.toml, tests/, docs/
Base commit: 005766e / 182aa65
Status:  done
Next:    Merged into main; 485 offline tests pass. Three of the page's defects and
         two of the page optimizations are covered by contracts on the source, not
         by running it: this checkout has no JavaScript runtime. The audit harness
         has one, and that is where their behaviour should be confirmed.
```

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
Last inspected main: 005766ee0630464f99fe815e42e472ef0740e379
Status: done
Next: User reviews B34-B43 and outstanding B27 in docs/file-audit-round8-2026-09-20.md. Six-file function inventory completed with synthetic and loopback tests; remaining module sequence recorded. No business-code edits.
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
