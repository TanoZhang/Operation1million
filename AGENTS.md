# Working alongside another agent

Claude Code and Codex both work this repository, sometimes at the same time and
sometimes on the same problem. That is deliberate: the point is a second
independent reading, so two agents reaching the same fix is a signal the fix is
real, and two agents disagreeing is where the interesting information is. This
file is the shared rulebook for both; `CLAUDE.md` only points here.

Overlapping work is therefore expected and is not waste. Losing one of the two
answers is.

- **Fetch before you plan, not before you push.** `git fetch origin main` in the
  first minute, and check `git log HEAD..origin/main`. The other agent pushes
  small commits while you work, and a session that reads the repository once
  and then works for four hours is working from a snapshot that has since
  stopped being true. This has already cost a whole feature built twice.
- **Never touch changes you did not make.** Uncommitted edits in the tree may
  belong to a session that is still running. No `stash`, `checkout --`, `reset`
  or `merge` over a file you did not modify; that file is someone's live work.
  If it blocks you, work in a separate worktree (`git worktree add -b <name>
  ../<dir>`) and say so.
- **Do not push to `main` while the other agent is active.** Branch from a named
  base commit and leave the merge to a moment when both sides can be seen at
  once. Two agents fast-forwarding `main` in turn is how one of the two answers
  disappears without anyone reading it.
- **When your work overlaps theirs, compare; do not quietly prefer your own.**
  Read their version, find the point where the two disagree, and settle it by
  testing rather than by reasoning about it. Then report the difference and what
  decided it. The disagreement is the output being paid for.
- A claim believed confidently is not a tested claim. A snapshot command was
  documented here as requiring `sudo` because a read-only WAL connection "has
  to" take a read mark in the `-shm` file. Running it as `ubuntu` on the VPS
  copied all 41,029 postings and took five seconds to find out.
- Author fields tell the two apart in history: Codex commits as
  `Daichi Zhang <132003493+TanoZhang@...>`, Claude Code as
  `TanoZhang <tanozhang@users.noreply.github.com>`. When you commit work the
  other agent wrote, say so in the message, because the field will not.

# Project Language and Encoding

- Conversation may use the user's preferred language. Use English for all authored project artifacts.
- Use English for code, comments, configuration, UI text, logs, reports, tests, and filenames.
- Do not add non-English text to project files without an explicit exception for that artifact.
- Write text files as UTF-8 and prefer ASCII punctuation in authored text.
- Preserve original provider data in raw records; do not translate or rewrite source evidence merely to enforce the authoring language policy.

## Collection operating rules

Read [docs/collection-rules.md](docs/collection-rules.md) before any network
collection, endpoint investigation, or change to daily discovery behavior.

- Prefer the verified public JSON list endpoints. Use Eightfold PCSX for Micron,
  Microsoft, and Qualcomm, and careers.amd.com/api/jobs for AMD. Do not restart
  legacy apply-v2, iCIMS, or GCS endpoint guessing for these companies.
- Use one collector process at a time. Microsoft has a dedicated source lock
  and a minimum 3-second interval; it must not reduce the configured worker pool
  for other companies. Other Eightfold sources use at least 2.5 seconds; other
  sources use at least 1 second. These are local conservative defaults, not
  provider guarantees or a promise against rate limiting.
- HTTP 429 stops that company for the current run. Preserve the persistent
  cooldown and wait at least 15 minutes or Retry-After, whichever is longer.
  Repeated throttling requires review and a longer pause, not repeated runs.
- Never bypass CAPTCHA, Human Verification, or access challenges. Do not rotate
  IPs, identities, or endpoints to evade a challenge; never disable TLS checks.
- JSearch is off by default. A direct page/job cap, malformed item, or a valid
  empty board must not trigger paid fallback. Test only with an explicit small
  request budget, starting at 1, and stop when the stated question is answered.
- Read [docs/jsearch.md](docs/jsearch.md) before changing paid discovery.
  Apply the configured employer exclusions before relevance scoring. Preserve exact employer/alias
  filtering for configured company fallbacks; query text is not a constraint.
  Reserve page credits, not HTTP counts; do not expand a fixed query plan.
- For a request to test one keyword over one week, use a temporary
  `--date-posted week` override with `--jsearch-only --jsearch-query` and one
  page/credit unless the user specifies another bound. Do not edit daily
  defaults, run the whole catalog, or increase pages automatically. Use
  `--no-store` for diagnostics and report the private output path and counts.
- Do not claim complete coverage from a single successful page. Keep Rivos
  marked as third-party data with unverified completeness.
- Daily incremental collection requires durable job identity and per-source
  progress. Do not stop on the first familiar job or trust posting dates alone.
  Persist through the shared daily gzip log. SQLite is derived and must not be
  committed. Never rewrite sealed daily logs or skip restoring private state.
- A complete inventory pass may retire at most 25% of the open jobs for its
  company/provider. A larger candidate closure must be blocked, downgraded to
  partial, and reported; never bypass this fuse when publishing private state.
- The authorized hosted schedule runs once daily at 04:38
  `America/Los_Angeles`. Scheduled runs execute the fixed JSearch plan; manual
  dispatches require an explicit paid-search toggle. Do not install a local
  startup task or create another schedule.

## Publication boundary

- Keep `TanoZhang/Operation1million` private, including its Git history, source
  catalog, downloaded records, databases, logs, and future discovery workflows.
- Publish only the reviewed conceptual overview to the separate public
  `TanoZhang/Operation1million-overview` repository with independent Git history.
- Keep credentials in local ignored files or private repository Actions Secrets.
  Never copy credentials, runtime state, or real records into public artifacts.
- Read [Publication Policy](docs/publication-policy.md) before publishing or
  changing repository visibility. The public repository has Actions disabled.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues for `TanoZhang/Operation1million`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default mattpocock/skills triage label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context project. See `docs/agents/domain.md`.
