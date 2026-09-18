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
  Functional discovery has no employer blacklist. Preserve exact employer/alias
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
- The authorized hosted schedule runs once daily at 06:17
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
