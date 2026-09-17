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
- Use one collector process at a time. Microsoft runs with one worker and a
  minimum 3-second interval; other Eightfold sources use at least 2.5 seconds;
  other sources use at least 1 second. These are local conservative defaults,
  not provider guarantees or a promise against rate limiting.
- HTTP 429 stops that company for the current run. Preserve the persistent
  cooldown and wait at least 15 minutes or Retry-After, whichever is longer.
  Repeated throttling requires review and a longer pause, not repeated runs.
- Never bypass CAPTCHA, Human Verification, or access challenges. Do not rotate
  IPs, identities, or endpoints to evade a challenge; never disable TLS checks.
- JSearch is off by default. A direct page/job cap, malformed item, or a valid
  empty board must not trigger paid fallback. Test only with an explicit small
  request budget, starting at 1, and stop when the stated question is answered.
- Preserve exact employer/alias filtering for JSearch. A company-name query is
  discovery text, not an employer constraint.
- Do not claim complete coverage from a single successful page. Keep Rivos
  marked as third-party data with unverified completeness.
- Daily incremental collection requires durable job identity and per-source
  progress. Do not stop on the first familiar job or trust posting dates alone.
  The incremental design in the rules document is pending implementation.
- Do not install startup tasks. A daily schedule needs an explicit time and
  user request; documenting daily collection is not authorization to schedule it.

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
