# Portable autofill memory

Version 0.6.0 keeps the existing version 1 answer profile and wraps it in a
portable JSON document. The public schema is in
`application-autofill/schema/memory.schema.json`. This is our documented format,
not a Meta standard or an automatic Muse connection. All personal values stay
in private extension storage or a user-selected local file, outside Git.

## Update loop

Open **Set up your answers**. Use **Continuously save to a memory file**, choose
a private `autofill-memory.json` outside the public checkout, and leave this tab
open. The extension writes its latest profile and pending final-value captures
when local storage changes. Reconnect after closing/reloading this tab or
restarting the browser. Browsers without File System Access can use
**Export latest memory JSON**. No background task or server is installed.

The file picker explicitly grants access to this one output file. Writes are
serialized and use the browser's writable-file commit on close. A failed write
is reported and does not discard browser storage. Another assistant should
write proposed updates to a DIFFERENT file: this output is owned by the browser.
The extension does not watch or automatically ingest externally edited files.

New trusted final values are captured while the extension is active on a page.
Opening the popup absorbs captures into its answer profile. Exports include
pending captures too; they are observations, not confirmed global facts. Editing
answers, confirming mappings, scans and absorbed captures add revision history.
Conflicting manual answers preserve the current value and record the alternative.
Existing browser-learning and exact scope rules still apply.

## Import and conflicts

**Import confirmed memory JSON** accepts the wrapper or a legacy version 1
profile. Validate before writing. It merges missing fields/questions and fills
empty compatible answers; it never overwrites existing answers, mapping scopes,
settings or existing education records. Conflicts remain in
`profile.memory.conflicts`. Source documents, including unknown extensions,
history and pending captures, remain in `profile.memory.imports` for recovery.
Incoming pending captures are archived, not authorized as facts or replayed.
Unknown imported properties remain in the source archive. To resolve a conflict,
edit the confirmed answer in settings and save; the alternative stays recorded.
Only import a file after checking its facts and mappings.

`profile.memory.history` stores revision, time, source and before/after
collections. This is personal data too. There is no automatic history deletion.
Full snapshots favor lossless recovery; large histories increase export size.
The authoritative runtime remains browser storage; importing/exporting does not
update Python `answers.json` or VPS application decisions.

## Instructions to give Muse or another assistant

Attach the exported JSON and provide this task text:

> Read this jobdisco-autofill-memory version 1 document. Use confirmed answers
> only within their site, position, time and work-route constraints. Do not infer
> eligibility or sponsorship. Pending captures and conflict alternatives are
> observations, not replacements for confirmed facts. Ask me for missing facts.
> Preserve all original keys and records. Add confirmed facts to profile.fields
> with stable keys, label, type, policy, answer and updated_at. Keep school,
> degree, major and graduation separate. Education and employment may be arrays
> of records with stable IDs. Do not assign a record to a repeated form row from
> its order. Return an updated JSON file under a new filename, plus the changed
> facts and unresolved questions. Fill forms using confirmed matching answers;
> leave existing values untouched and leave final submission to me.

Muse's official product introduction describes browser form filling and
background tasks: https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/.
Direct access to this computer's file/extension storage is not established.
Hand the file to Muse through its supported upload/file tools. Autonomous
execution and scheduling belong to Muse's own account setup, not this extension.

## Expanded basics

The settings editor adds LinkedIn, GitHub, portfolio, address line 2, current
GPA and its scale, available start date, internship duration, preferred work
locations, relocation, languages and technical skills. Answers default to empty;
no personal values are inferred. Exact approved wording is required. Arbitrary
additional fields and education/employment arrays can be imported. Job-specific
open-ended drafts should remain separately scoped and require confirmation.
