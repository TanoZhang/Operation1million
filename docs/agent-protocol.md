# Agent protocol

This document answers one startup question: who is changing what now? Completed
work belongs in the newest handoff, the architecture bug log, and Git history.

## Active claims
```text
Owner: codex
Scope: Reproduce the reported Zipline software-validation false positive;
       user clarified all software titles must have VLSI JD evidence before
       automatic admission, including generic and chip-named software titles.
Files: src/operation1million/{jsearch,applications}.py,
       data/config/jsearch_queries.toml, tests/{test_software_validation,test_review_rules,
       test_bulk_application_rules}.py, docs/{agent-protocol,architecture,handoff}.md;
       ignored .local/software-validation-audit/ private evidence only.
Base commit: d130962
Status: done -- 07b58ed installed; 66 focused tests pass on that exact commit.
Next: Automatic discovery and Review enforce current software JD evidence;
      missing-JD software waits for actual prose. No additional paid pass.
```

```text
Owner: codex
Scope: User-requested increase of all current three-page nationwide trials
       to ten pages per query, retaining the 400-credit daily ceiling.
Files: data/config/jsearch_queries.toml, tests/test_jsearch.py,
       docs/{agent-protocol,handoff,jsearch,collection-rules}.md
Base commit: 34260e6
Status: done -- 855898b installed; 117 focused offline tests pass.
Next: October 6 04:38 Pacific scheduled pass uses ten-page trials;
      daily ceiling remains 400 and no extra paid pass was started.
```

```text
Owner: codex
Scope: User-requested 400-credit daily budget, remove all state-split searches,
       expand nationwide VLSI title coverage, validate and deploy the scheduled plan.
Files: data/config/jsearch_queries.toml, tests/test_jsearch.py,
       docs/{agent-protocol,handoff,jsearch,collection-rules}.md
Base commit: f399d6d
Status: done -- e30c79c installed; 1,128 offline tests accounted for, 13 skips;
        live plan is 170 queries / 400 daily credits, no state splits.
Next: Scheduled October 6 04:38 Pacific pass measures the expanded plan.
      No extra paid collection was started; today remains at 201 credits.
```

```text
Owner: codex
Scope: User-requested Gmail matching/classification fixes and star every Passed round once; retain Passed/Declined outcomes and manual overrides.
Files: src/operation1million/gmail_outcomes.py, tests/test_gmail_outcomes.py, docs/{agent-protocol,architecture,application-review,handoff}.md
Base commit: b4923c1
Status: done -- eight regressions red before fix; 85 focused offline tests pass.
Next: Commit/push; deploy separately. No live mailbox writes or historical outcome repair.
```

```text
Owner: claude
Scope: At the user's request (2026-10-05): rename everything named operation1million to
       operation1million -- package, imports, OPERATION1MILLION_* variables, systemd
       units, VPS user/group, /opt and /etc paths, docs. Not the SQLite file
       (job_discovery.sqlite) or the CLI command names (job-*), which never
       carried the name. Codex worktrees (last commits 2026-09-20..23) predate
       this and will conflict if revived.
Files: every tracked file naming operation1million; src/operation1million -> src/operation1million;
       deploy/vps/operation1million-* -> deploy/vps/operation1million-*
Base commit: f1bdd40
Status: active
Next: Push, then migrate the VPS in place (usermod/groupmod keep the uid,
      mv /opt and /etc, rebuild the venv, swap the units) before the 11:38 UTC pass.
```

```text
Owner: claude
Scope: At the user's request (2026-10-05): mark an applied position Passed
       or Declined in Review; passed ones are highlighted. Kept beside the
       ledger in operational/application_outcomes.ndjson, append-only.
Files: src/operation1million/{applications,review,manual_intake}.py, review_static/*,
       deploy/vps/{backup-applications,daily-pass,data-sync}.sh,
       tests/test_application_outcomes.py, docs/{agent-protocol,application-review}.md
Base commit: 63e98a1
Status: active -- marks renamed Passed / Declined; adding the Gmail reader
        (src/operation1million/gmail_outcomes.py, deploy/vps/operation1million-gmail.*,
        install.sh, local_config.py) at the user's request.
        Installed 1080d2b (install.sh run twice: the first run executes the old
        script); operation1million-gmail.timer active, idle until GMAIL_* are filled in.
Next: User adds a Gmail app password to /etc/operation1million/env; verify a live run.
```

```text
Owner: codex
Scope: Delete the abandoned autofill component and local copies, without an archive; inspect but leave Muse's private job-applications records unchanged per user clarification.
Files: application-autofill/, src/operation1million/answer_bank.py, autofill/answer-bank tests and docs, packaging/deploy references; obsolete ignored local autofill copies.
Base commit: 003d067 (public), 0dc63ad (private)
Status: done -- obsolete component and local data removed, no archive; private repository unchanged. Full suite checked; updated deployment tests pass.
Next: Push public code; the user deploys separately.
```

```text
Owner: codex
Scope: Add the user's fifteen title-synonym trials at three pages each on top of Claude's merged caps and co-op plan.
Files: data/config/jsearch_queries.toml, tests/test_jsearch.py, docs/{agent-protocol,handoff,jsearch}.md
Base commit: 3451171
Status: done -- 113 offline tests pass; all 47 existing queries and caps preserved.
Next: Push the merged 62-query plan; deployment and paid collection are separate.
```

```text
Owner: claude
Scope: At the user's request (2026-10-04): two AGENTS.md invariants from the
       search-v2 cursor bug; hunt for bugs of the same class (collection that
       silently reads less than it should, fixtures that encode an assumption).
       Then, at the user's request, one entry per job across sources (#319).
       Codex is out until 20:33; small edits in its files, each noted here:
       store.py (MONOTONIC_NEWEST_FIRST only, #317), applications.py
       (unify_copies and its call, #319).
Files: AGENTS.md, docs/{agent-protocol,bug-tracker}.md, src/operation1million/{store,prune,applications}.py,
       deploy/vps/daily-pass.sh, tests/{test_store,test_prune,test_unify_copies}.py
Base commit: c3923f6
Status: done -- 31687ba and 1215ea4 pushed and installed. 6,476 open postings
        restored on the VPS (data commit 1a52b6b); Muse's applications
        reconciled. 1215ea4: looser JSearch caps, co-op queries, Review batches.
Next: Measure the next pass's credit use and yield under the new caps.
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
Owner: claude
Scope: Data repository with two writers (bug #315): every VPS writer fetches and
       replays its unpushed commits onto origin/main before pushing; append-only
       ledgers merge line by line. muse (laptop, GitHub API) writes only
       job-applications/. The daily pass no longer stops on a failing test,
       a ledger behind or a plan preview error; paid search always runs (#316).
Files: deploy/vps/{data-sync.sh,backup-applications.sh,daily-pass.sh,install.sh},
       tests/test_prelaunch_fixes.py, docs/{bug-tracker,handoff,agent-protocol}.md
Base commit: 755e7d0
Status: done -- pushed to main, not deployed
Next: Deploy with deploy/local/deploy-vps.bat.
```

```text
Owner: claude
Scope: Ten direct sources at the user's request: Anthropic, xAI, OpenAI,
       SambaNova, d-Matrix, Quadric, KLA, Applied Materials, GlobalFoundries,
       Lam Research.
Files: data/config/schema.sql, tests/test_collect_sql_sources.py,
       docs/{collection-rules,handoff,agent-protocol}.md
Base commit: b175f3a
Status: done -- pushed to main, not deployed
Next: Deploy; the next pass rebuilds the index and reads the new boards.
```

```text
Owner: claude
Scope: At the user's request (2026-10-03), the JSearch plan is the user's own
       43-query list: caps may total more than the daily budget (the guard
       stops the day at 320), deeper early-career caps, eight early-career
       trials. Replaces the 2026-09-27 re-set and codex's 2026-10-02/03 query
       trials; the user stopped codex's keyword work and the VPS timer.
Files: src/operation1million/jsearch.py, data/config/jsearch_queries.toml,
       tests/{test_jsearch,test_bulk_application_rules}.py,
       docs/{jsearch,collection-rules,handoff,agent-protocol}.md
Base commit: 4e6789e
Status: done -- pushed to main, not deployed
Next: Deploy, then enable operation1million-collect.timer without starting the service.
```

```text
Owner: codex
Scope: Reconcile user-supplied applied and closed-position statuses with the private VPS decision ledger; leave collection and JSearch configuration stopped/unchanged.
Files: private VPS operational/application ledgers only; docs/agent-protocol.md for claim status.
Base commit: 4e6789e
Status: done
Next: Private Review ledger and live queue were verified; no collector or JSearch change, and no public-code deployment is needed.
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
Owner: codex
Scope: User clarification: restore pre-expansion JD-based embedded/VLSI rules; examine equivalent VLSI names only.
Files: data/config/jsearch_queries.toml, src/operation1million/ranking.py, tests, docs/{agent-protocol,architecture,handoff,jsearch}.md
Base commit: 81b378a
Status: done -- exact eaa6bc4: 1,112 tests pass (11 skips), deployed/rescored; live queue restored to all 5,261 original groups.
Next: Refresh Review. Six VLSI synonym queries run on schedule; 153 embedded/firmware groups retained.
```

```text
Owner: codex
Scope: Record-driven broadening of adjacent engineering title/score/query vocabulary for bulk applications.
Files: data/config/jsearch_queries.toml, src/operation1million/ranking.py, tests/test_review_rules.py,
       tests/{test_bulk_application_rules,test_jsearch,test_store,test_sixth_bug_hunt}.py, docs/{agent-protocol,architecture,handoff,jsearch}.md
Base commit: e456c97
Status: done -- exact d4a7986 passes 1,114 tests (11 skips), installed; durable rescore/verify complete; queue HTTP 200.
Next: Refresh Review. 117 new pending/backlog groups (13 early-career), no prior group removed; query trials run on schedule.
```

```text
Owner: codex
Scope: User-requested virginiacommons.com publisher block.
Files: data/config/jsearch_queries.toml, tests/test_review_rules.py, docs/{agent-protocol,handoff,blocked-recruitment-domains}.md
Base commit: 876f78a
Status: done -- 64 focused tests and targeted checks pass; installed cd3e3ca.
Next: Review rebuilds its queue after this configuration change.
```

```text
Owner: codex
Scope: Broaden bulk-application relevance threshold and restore account-based Dice/Wellfound sources.
Files: data/config/jsearch_queries.toml, tests/test_account_walled.py, docs/{agent-protocol,architecture,handoff,blocked-recruitment-domains}.md
Base commit: d74e89a
Status: done -- installed 52c1b1b; queue HTTP 200, 0.128 seconds; 230 focused tests pass.
Next: Refresh Review; scheduled collection uses restored sources within existing budget.
```

```text
Owner:   claude
Scope:   #311 at the user's request (2026-10-02): an RTX posting needing U.S.
         citizenship reached Review. Pasted jobs skip every filter; apply the
         employer, title and citizenship hard rejects to them.
Files:   src/operation1million/{manual_intake,review}.py, tests/test_twelfth_bug_hunt.py,
         docs/{agent-protocol,architecture,handoff,bug-tracker,application-review}.md
Base commit: de2add0
Status:  done -- installed at fcee2bd; Review restarted, HTTP 200
Next:    Ctrl+F5 Review.
```

```text
Owner: codex
Scope: Persist validated derived Review queue cache to avoid full restart builds; simplify preparing message.
Files: src/operation1million/{review,queue_snapshot}.py, review_static/app.js, tests/test_queue_snapshot.py,
       docs/{agent-protocol,handoff,architecture}.md
Base commit: a9f4299
Status: done -- 1806349 installed; private cache created, restart queue GET HTTP 200 in 0.175s.
Next: Ctrl+F5. Cold preparation is neutral and retrying; unchanged restarts restore cache.
```

```text
Owner: codex
Scope: Select all positions within a Review section (recent 72 hours/backlog).
Files: review_static/{app.js,style.css}, tests/review-selection.cjs, docs/{agent-protocol,handoff}.md
Base commit: 3cb16f0
Status: done -- ca47d3c installed; DOM verifies section-only and unexpanded selection.
Next: Ctrl+F5; checkbox beside New in the last 72 hours selects that section.
```

```text
Owner: codex
Scope: Reset paste form after successful add/applied save; preserve failed input.
Files: review_static/app.js, tests/review-selection.cjs, docs/{agent-protocol,handoff}.md
Base commit: 5f90e8b
Status: done -- 9c64fe0 installed; browser interaction fixture passed.
Next: Ctrl+F5; successful paste clears inputs, failures preserve them.
```

```text
Owner: codex
Scope: Replace Applied card/detail top classification chips with applied date.
Files: review_static/app.js, tests/review-selection.cjs, docs/{agent-protocol,handoff}.md
Base commit: 5fceb6b
Status: done -- 6e3802a installed; DOM verifies date above company on card/detail.
Next: Ctrl+F5. Live script contains both topBadge placements.
```

```text
Owner: codex
Scope: Per-tab Excel selection; bounded queue loading; Applied-specific paste and visible applied dates.
Files: review.py, review_static/*, tests/{review-selection.cjs,test_manual_intake.py}, docs/{agent-protocol,handoff,application-review}.md
Base commit: 1b9b149 (production queue currently HTTP 200 in 0.188s)
Status: done -- 9727d4a installed; 106 Review and 10 intake/loading tests passed.
Next: Ctrl+F5. Live JS/CSS and prompt cold-queue Preparing/503 verified.
```

```text
Owner: codex
Scope: Block JobMesh.io; add explicit user-pasted job intake and applied-link
       reconciliation. Manual records bypass discovery eligibility by user request,
       retain relevance ranking, durable provenance and conservative identity matching.
Files: src/operation1million/manual_intake.py, src/operation1million/review.py, review_static/*,
       data/config/jsearch_queries.toml, tests/test_manual_intake.py,
       deploy/vps/{backup-applications,daily-pass}.sh, tests/test_prelaunch_fixes.py,
       docs/{agent-protocol,handoff,architecture,application-review}.md
Base commit: 085cd6f (deployed; live selected XLSX download HTTP 200 verified)
Status: done -- implementation b15b226 pushed and installed; offline and POSIX tests pass.
Next: Ctrl+F5. Paste a link to add/score or mark applied; confirm company link
      when replacing a third-party match. JSON-LD or supplied details are supported.
```

```text
Owner: codex
Scope: Make Excel button download in browser; mark third-party listings except
       LinkedIn and Handshake, consistently in Review and Excel; deploy release.
Files: src/operation1million/{review,export}.py, review_static/*, tests/test_review*.py,
       tests/{review-selection.cjs,test_manual_intake.py}, docs/{agent-protocol,handoff,application-review}.md
Base commit: b8123d3 plus the completed staged patches
Status: done -- release 085cd6f pushed and installed; live selected XLSX HTTP 200
Next: Ctrl+F5 in the browser. Live ZIP, site marker column and Normal style verified.
```

```text
Owner: codex
Scope: Review checkbox selection and browser download of selected Excel rows.
Files: src/operation1million/{review,export}.py, src/operation1million/review_static/*,
       tests/{test_review_export.py,review-selection.cjs},
       docs/{agent-protocol,handoff,application-review,architecture}.md
Base commit: b8123d3 plus completed staged deployment fix
Status: done -- selection DOM fixture and Review tests pass; Normal style regression
        failed before fix, independent workbook reader passes after fix
Next: Deploy the local patch and refresh Review. The user's specific Excel symptom
      is still awaiting clarification; no real Excel application validation claimed.
```

```text
Owner: codex
Scope: Fix deployment staging omitting new autofill source files; reduce expected
       test-output noise and pin text line endings without changing runtime logic.
Files: deploy/local/deploy-vps.bat, .gitattributes, tests/test_deploy_autofill.py,
       docs/{agent-protocol,handoff,architecture}.md
Base commit: b8123d3
Status: done -- two regressions red before fix, full suite 1071 tests, ten skips
Next: Re-run deploy-vps.bat to ship missing public autofill files and this fix.
      Current validation is local on b8123d3 plus the staged patch, not deployed.
```

```text
Owner: codex
Scope: Initialize private split autofill data from existing local profiles;
       provide schema, Muse instructions and a reproducible extension export.
Files: application-autofill/data-files.py, .local/autofill/data/*,
       tests/test_autofill_data_files.py, docs/{agent-protocol,handoff}.md
Base commit: 4936abf plus completed 0.6.0 patch
Status: done -- private split initialized, originals preserved; two offline tests pass
Next: Muse can edit the private data folder; run data-files.py export and explicitly
      import into the browser. No automatic browser/file synchronization added.
```

```text
Owner: codex
Scope: Portable continuously updated browser answer memory with JSON schema,
       import/export, change history and cross-agent instructions; no submission.
Files: application-autofill/extension/{portable-memory,profile}.js,
       application-autofill/extension/profile.html, application-autofill/schema/*,
       tests/autofill-memory.cjs, tests/test_autofill_memory.py, docs/autofill-memory.md,
       docs/{agent-protocol,handoff}.md
Base commit: 4936abf
Status: done -- 0.6.0 local patch; 58 autofill and 18 answer-bank tests pass
Next: Reload extension; verify the browser's file picker and hand the private
      memory JSON to Muse. No account connection, live form or deployment tested.
```

```text
Owner:   claude
Scope:   #301-310 at the user's request (2026-10-02): defects in pasted-link
         intake (Codex's b15b226, claim done), measured on live postings, each
         with a reproducer red before its fix. The user has abandoned autofill
         (submission is done through Muse): no autofill work.
Files:   src/operation1million/{manual_intake,ranking}.py, tests/test_twelfth_bug_hunt.py,
         docs/{agent-protocol,architecture,handoff,bug-tracker,application-review}.md
Base commit: 1b9b149
Status:  done -- installed at fcee2bd; Review restarted, HTTP 200
Next:    Ctrl+F5 Review.
```

```text
Owner:   claude
Scope:   Autofill 0.5.1 at the user's request (2026-10-02): provider field ids
         (Workday, Greenhouse, Lever, Ashby) and HTML autocomplete tokens as
         exact aliases, from public sources. On Codex's 0.5.0; Codex owns the
         extension otherwise.
Files:   application-autofill/extension/{ats-adapters,answer-engine}.js, manifest.json,
         tests/{autofill-ats-fields.cjs,test_autofill_ats_fields.py},
         docs/{autofill-framework,agent-protocol}.md
Base commit: f8f38b7
Status:  done -- pushed to main; reload the unpacked extension
Next:    Codex: review the declared-field rule in aliasCandidates.
```

```text
Owner:   claude
Scope:   Fifth bug hunt at the user's request (2026-10-02): seventy-four
         defects, #227-300, each with a reproducer red before its fix; and
         forty behaviour-preserving structural improvements, each checked for
         identical output. Not the autofill extension.
Files:   src/operation1million/*, data/config/*, deploy/*, tests/*,
         docs/{agent-protocol,architecture,handoff,bug-tracker}.md
Base commit: bcc5b04
Status:  done -- #227-300 pushed (0b92f44); improvements 5-40 pushed on top
         of it (1-4 went out with the hunt); not deployed
Next:    Deploy with deploy-vps.bat, then job-store --rescore.
```

```text
Owner:   claude
Scope:   Review page, at the user's request (2026-10-01): sort by date
         (newest / oldest) and by fit then date; one key and a button that
         export the current view to one Excel file, rewritten in place.
Files:   src/operation1million/{review,export}.py, src/operation1million/review_static/*,
         tests/test_review_export.py, docs/{agent-protocol,application-review,handoff}.md
Base commit: 62b7ace
Status:  done -- pushed to main, not deployed
Next:    Deploy with the hunt above.
```

```text
Owner: codex
Scope: ATS-native autofill framework, known-answer assessment and browser-local basic-question onboarding.
Files: application-autofill/extension/*, application-autofill/README.md,
       tests/{autofill-runtime.cjs,test_autofill_runtime.py,test_autofill_framework.py},
       tests/autofill-framework.cjs, tests/test_autofill_extension.py,
       docs/{autofill-framework,answer-bank,agent-protocol,architecture,handoff}.md
Base commit: 9d3e5ae9138116033a8271fa8172b3a8abd00404 plus Codex's completed local DOM fixes
Status: done -- implementation 0.5.0 and ignored local seed ready; not pushed or deployed
Next: Reload extension, import saved local answers, verify a real ATS form. Offline:
      942 tests, 933 passed and nine skips; final contextual-binding follow-up passed all 15 framework cases.
```

```text
Owner: codex
Scope: Fix ten browser autofill boundary defects (#217-226); offline fixtures only.
Files: application-autofill/extension/{content,popup}.js,
       application-autofill/extension/manifest.json,
       application-autofill/README.md, tests/test_autofill_runtime.py,
       tests/autofill-runtime.cjs, docs/{agent-protocol,architecture,handoff,bug-tracker}.md
Base commit: 9d3e5ae9138116033a8271fa8172b3a8abd00404
Status: done -- local fixes, no push or deployment
Next: Reload extension 0.4.1 and refresh existing pages. Offline suite: 927 tests,
      918 passed, nine environment skips; all twelve DOM runtime cases executed.
```

```text
Owner:   claude
Scope:   Fourth bug hunt at the user's request (2026-10-01): twenty defects in
         src/operation1million, #197-216, each with a reproducer red before its fix.
         Not the autofill extension (Codex's claim).
Files:   src/operation1million/*, data/config/*, tests/test_tenth_bug_hunt.py,
         docs/{agent-protocol,architecture,handoff,bug-tracker}.md
Base commit: 9d3e5ae
Status:  done -- #197-216 fixed in remote main 62b7ace; not deployed
Next:    deploy/vps/install.sh, then job-store --rescore.
```

```text
Owner:   claude
Scope:   Third bug hunt at the user's request: twenty more defects, each with a
         reproducer red before its fix; and, as the user decided, BS/MS paths
         listed apart (comma, bullet or sentence) count as alternatives.
Files:   src/operation1million/*, data/config/jsearch_queries.toml, tests/*,
         docs/{agent-protocol,architecture,handoff}.md
Base commit: c0d6e3b
Status:  done -- #1-160 fixed and pushed (docs/bug-tracker.md), plus the
         account-walled publisher change; not deployed
Next:    deploy/vps/install.sh, then job-store --rescore.
```

```text
Owner:   claude
Scope:   Second bug hunt at the user's request: twenty defects found, each
         with a reproducer red before its fix (heading detection, R5,
         filters, location, ranking, store, review).
Files:   src/operation1million/*, tests/*, docs/{agent-protocol,architecture,handoff}.md
Base commit: d7be20e
Status:  done -- forty fixed in two rounds, pushed to main, not deployed
Next:    Deploy with deploy/vps/install.sh, then job-store --rescore.
```

```text
Owner: claude
Scope: Codex R6 (experience: a short preference sentence opens a Preferred
       section) and R7 (degree: an inline Required heading cannot end one).
Files: src/operation1million/{experience,degree}.py, tests/{test_experience,test_degree}.py,
       docs/{architecture,handoff,agent-protocol}.md
Base commit: fb0c18a
Status: done -- merged to main (4a8a03f), not deployed
Next: Deploy with deploy/local/deploy-vps.bat. R5 from the same audit remains open.
```

```text
Owner: claude
Scope: Experience gate misreads found from an NXP new-grad posting and a read
       of real Workday postings; block learn4good, and block JobLeads,
       Jobrapido and learn4good by publisher name as well as by domain.
Files: src/operation1million/experience.py, data/config/jsearch_queries.toml,
       tests/{test_experience,test_review_rules}.py,
       docs/{blocked-recruitment-domains,architecture,handoff,agent-protocol}.md
Base commit: c10f6c2193c568ee39d2a4554641ba96d008f5f3
Status: done -- main at b06f0e6, not deployed (no VPS key in this session)
Next: Run deploy/local/deploy-vps.bat or deploy/vps/install.sh. Direct-board
      rows are re-judged at queue time; paid rows refused at intake kept no
      description and are not recovered by this.
```

```text
Owner: claude
Scope: Block two more publisher domains at the user's request: JobLeads
       (jobleads.com) and Jobrapido (jobrapido.com).
Files: data/config/jsearch_queries.toml, tests/test_review_rules.py,
       docs/{blocked-recruitment-domains,architecture,handoff,agent-protocol}.md
Base commit: c10f6c2193c568ee39d2a4554641ba96d008f5f3
Status: done -- merged to main (b06f0e6), not deployed
Next: Deploy with the claim above. Full offline suite 690 tests, 2 environment skips
      (data/db/job_discovery.sqlite absent). Not deployed.
```

```text
Owner: claude
Scope: Review page: To review splits into Early career (intern / NG / early
       career titles) and To review (the rest).
Files: src/operation1million/{ranking,applications,review}.py,
       src/operation1million/review_static/{app.js,index.html},
       tests/test_review_{rules,payload}.py,
       docs/{application-review,architecture,handoff,agent-protocol}.md
Base commit: 82e8a81
Status: done -- committed on branch claude-early-career-tab, not pushed
Next: Push to main, then deploy with deploy/vps/install.sh.
```

```text
Owner: claude
Scope: Review page: less related postings get their own tab; Remaining and
       the To review and Backlog tabs exclude them.
Files: src/operation1million/review_static/{app.js,index.html}, tests/test_review_payload.py,
       docs/{application-review,architecture,handoff,agent-protocol}.md
Base commit: b6422c9
Status: done -- pushed to main, not deployed
Next: Deploy with deploy/vps/install.sh.
```

```text
Owner: codex
Scope: ATS-independent standalone Chrome/Edge autofill MVP with automatic
       final-value learning, conservative fill controls and regression tests. Never
       submit applications, accept agreements, solve challenges, or store data
       in the public repository.
Files: src/operation1million/answer_bank.py, application-autofill/*,
       tests/test_{answer_bank,autofill_extension,autofill_profile}.py,
       docs/{answer-bank,agent-protocol,architecture,handoff}.md
Base commit: c10cfcb4ace8eae88b68c11fb5f7b87e3bec14da
Status: done
Next: Reload the unpacked extension once and verify version 0.4.0 on a benign
      HTTPS form. Focused 29 and full 688 tests pass on the base plus this tree.
```

```text
Owner:   claude
Scope:   Bug hunt across the package at the user's request: find, test and
         fix defects (filter rules, location, experience, ranking, store,
         review, collector). Each fix gets a reproducer red before it.
Files:   src/operation1million/*, data/config/jsearch_queries.toml, tests/*,
         docs/{agent-protocol,architecture,handoff}.md
Base commit: b2c9340
Status:  done -- pushed to main, not deployed
Next:    Run deploy/vps/install.sh on the VPS (this session has no SSH
         access to it).
```

```text
Owner:   claude
Scope:   Review detail shows the paid description beside qualification-only
         fields instead of hiding it; add deploy/local/open-review.bat.
Files:   src/operation1million/job_text.py, tests/test_review_description.py,
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
Files:   src/operation1million/{degree,store,jsearch}.py, tests/{test_degree,
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
Files: src/operation1million/job_text.py, tests/test_review_description.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: c1a322e plus current working tree
Status: done
Next: Review nested qualification fix; new HTTP regression red before fix, all 132 focused tests green after. Not deployed.
```

```text
Owner: codex
Scope: Preserve unique teasers, qualification section meaning and literal type names beside HTML entities.
Files: src/operation1million/{store,job_text,review}.py, tests/{test_store,test_review_description}.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: c1a322e plus six-fix working tree
Status: done
Next: Review follow-up patch. All 131 focused storage and HTTP/payload tests pass. Not deployed.
```

```text
Owner: codex
Scope: Fix six post-location audit findings: stale HTML, structural dedupe, citizenship clause scope, empty descriptions, qualification display and malformed raw payloads.
Files: src/operation1million/{store,job_text,jsearch,applications,review}.py, tests/test_review_description.py, tests/test_review_rules.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: c1a322e
Status: done
Next: Review patch on c1a322e. Full offline suite: 635 discovered, 626 passed, nine environment skips. Not deployed.
```

```text
Owner: codex
Scope: Separate degree text preparation from qualification policy and improve documentation navigation; preserve behavior.
Files: src/operation1million/degree.py, docs/{agent-protocol,handoff,architecture}.md
Base commit: feda989aa91d407408f2df1d21e6f5eb8f985407
Status: done
Next: Review structure-only refactor. All 89 focused tests pass; 38,302 local postings have identical before/after degree verdicts.
```

```text
Owner: codex
Scope: Normalize coding practices and withdraw export/field-removal changes following the user's lossless-only clarification.
Files: src/operation1million/{degree,jsearch}.py, docs/{coding-standards,agent-protocol,handoff}.md
Base commit: feda989aa91d407408f2df1d21e6f5eb8f985407
Status: done
Next: Continue measured lossless storage design under docs/coding-standards.md. All 89 focused tests pass; no deployment.
```

```text
Owner: codex
Scope: Fix PhD-only preference and structured-section boundary errors; centralize hard eligibility checks; no deployment.
Files: src/operation1million/{degree,jsearch,applications}.py, tests/{test_degree,test_review_rules}.py, docs/{agent-protocol,architecture,handoff}.md
Base commit: feda989aa91d407408f2df1d21e6f5eb8f985407
Status: done
Next: Review local patch; latest alternative-scope fix and regex reuse pass all 89 focused tests. Not deployed.
```

```text
Owner:   claude
Scope:   Review queue filters and order at the user's direction, 2026-09-22:
         screened and merged codex (B68-B84, answer bank, sort, domain lists),
         and deployed each step to the VPS.
Files:   src/operation1million/{applications,review,jsearch,experience,ranking,
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
Files: data/config/jsearch_queries.toml, src/operation1million/jsearch.py, tests/test_review_rules.py, docs/{blocked-recruitment-domains,agent-protocol,architecture,handoff}.md
Base commit: d9aed44 (fetched and fast-forwarded before editing)
Status: done
Next: Review codex evidence-backed blocklist. All 134 offline Review/filter tests pass. No deployment or production measurement.
```

```text
Owner: codex
Scope: Review UI defaults to descending Fit with selectable original ordering; no deployment.
Files: src/operation1million/review_static/{app.js,index.html,style.css}, docs/{agent-protocol,architecture,handoff}.md
Base commit: ef978587e19c0ca99d670ef6bef0ea23d9cbb808 (origin/main de12047 merged before editing)
Status: done
Next: Review codex Fit ordering. Node behavior checks passed; full suite 584 discovered, 574 passed, 10 environment skips. Not deployed.
```

```text
Owner: codex
Scope: Enforce position context for imported job-specific autofill answers; local personal data stays ignored.
Files: src/operation1million/answer_bank.py, tests/test_answer_bank.py, docs/{answer-bank,agent-protocol,architecture,handoff}.md
Base commit: 53b51452ed64ef365879cb78d5bde958a9342497
Status: done
Next: Review codex position-context guard. Seventeen offline tests pass; 27 local imported answers verified, two require the matching position. No browser submission or deployment.
```

```text
Owner: codex
Scope: Local reusable answer bank, scoped question learning and extensible personal fields; no browser filling or deployment.
Files: src/operation1million/answer_bank.py, tests/test_answer_bank.py, pyproject.toml, docs/{answer-bank,agent-protocol,architecture,handoff}.md
Base commit: bcfe9533292e5c6fb0f2c1327b4af6de88574319
Status: done
Next: Review codex answer-bank implementation. Local empty bank created; 16 focused tests pass; full suite 569 discovered, 559 passed and 10 environment skips. Browser reader/filler is a separate integration step.
```

```text
Owner: codex
Scope: Implement and regression-test B68-B84 from audits 13-15; no deployment.
Files: deploy/local/, deploy/vps/backup-snapshot.py, deploy/vps/compact-history.sh, deploy/vps/daily-pass.sh, src/operation1million/{collection_policy,collector,validate_sources,jsearch,query_catalog,store,review}.py, tests/, docs/{agent-protocol,architecture,handoff,vps-deployment}.md
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
Files:   src/operation1million/{jsearch,collection_policy,ledger_guard}.py,
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
Files:   src/operation1million/{store,collector,jsearch}.py, tests/test_store.py, docs/
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
Files:   src/operation1million/{collector,store}.py, data/config/migrations/006_source_full_pass.sql,
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
Files:   src/operation1million/{jsearch,experience,collector}.py, tests/test_jsearch.py, docs/
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
Files:   src/operation1million/{applications,review,store}.py,
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
Files:   src/operation1million/{experience,job_text,jsearch,review,applications,collector,
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
Files:   src/operation1million/{collector,store,applications,review,jsearch,collection_policy,
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
the deciding tests, and record what resolved the difference. Commit authors do
not tell the agents apart; the claim's `Owner` line does.
