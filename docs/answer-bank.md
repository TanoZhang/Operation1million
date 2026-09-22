# Local autofill answer bank

One canonical field owns one answer. Observed website questions point to that
field; they never copy its answer. Editing the answer changes every subsequent
resolution of its confirmed synonyms. This module prepares answers locally; it
does not read browser tabs, fill forms, accept agreements, or submit applications.

## Storage and ownership

The default directory is `.local/autofill` under the code checkout. Set
`JOBDISCO_ANSWERS` or pass `--directory` to choose a stable workstation directory
across worktrees. This personal store is separate from the VPS application
decision ledger and from the disposable job index.

- `answers.json`: authoritative fields, answers and observed-question mappings.
  Back up this file privately. It contains personal information once populated.
- `answers.sqlite`: derived relational view, refreshed after each successful
  source write. Tables: `fields`, `aliases`, `questions`, `metadata`.
- `answers.lock`: coordinates local writers. Writes replace the JSON atomically
  after fsync. A failure refreshing SQLite does not undo the saved JSON; close
  SQLite viewers holding the file and run `reindex` to recover the view.

The files are plain text/unencrypted SQLite, ignored by Git under `.local/`.
They are not included in the existing VPS backup. Do not commit personal answers
or put them in collected job records. No real answers are seeded. SQLite is a
view, not a second writer: direct SQL edits are lost on the next refresh.

## Matching contract

`observe(label, site=..., section=..., kind=..., options=...)` records a question
and returns its ID, canonical field, status and an answer only when ready.
Repeated observations increment a count instead of adding duplicates. Full
URLs and their query strings are not retained; the site origin is stored.

Built-in exact aliases cover first/given name, last/family name/surname, legal
full name, preferred name, email and phone. They apply to text controls in the
general/contact/applicant sections only. Normalization ignores case, whitespace
and trailing required-marker punctuation; it does not remove negation or use
fuzzy similarity to authorize an answer. `Name`, `Full name` and `Formal name`
remain pending until their meaning is confirmed. Legal and preferred names
remain distinct fields.

Learned mappings are scoped to origin, section, normalized wording, control
kind and exact option set. A different company, section, negation or option set
creates a new pending question. Record the complete actual option list for a
choice control; never substitute guessed Yes/No values. Option order alone
does not invalidate a mapping. Labels are display text, not website option IDs.
A future browser adapter must translate and verify the selected DOM option.

Status values:

| Status | Meaning |
| --- | --- |
| `unknown` | New wording needs a confirmed field mapping. |
| `missing_answer` | Meaning is known, but no answer has been supplied. |
| `incompatible_control` | Stored answer type does not match the control. |
| `option_mismatch` | The exact answer is absent from the observed options. |
| `requires_review` | This field requires confirmation for each use; no answer is emitted. |
| `position_context_required` | A job-specific mapping requires its exact position ID; no answer is emitted for missing or different context. |
| `ready` | A compatible answer can be proposed; this is not permission to transmit it. |

Personal fields default to `review`. Do not create reusable automatic consent
answers for agreements. Countries, dates, employment eligibility, sponsorship
and time-dependent availability should use distinct, context-specific fields.
An unknown question can remain pending indefinitely without blocking unrelated
known fields. There is no automatic semantic learning from a guessed answer.

## Commands

Run from an environment with this checkout installed, or pin `PYTHONPATH` to
its `src`. All examples below use fictional labels and values.

```text
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill init
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill observe "Formal name" --site https://example.test/apply --section "Contact Information"
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill pending
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill bind QUESTION_ID name.legal_full
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill set-answer name.legal_full --file D:/private/full-name.json
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill resolve QUESTION_ID
python -m jobdisco.answer_bank --directory D:/Operation1million/.local/autofill reindex
```

The answer file contains a JSON value, for example `"Example Person"`, `2028`,
`false`, or `["Austin", "San Diego"]`. JSON `null` clears an answer. Answers are
read from a file to avoid putting them into command history; keep that file
private too. `resolve`/`observe` can print ordinary ready answers to the terminal.
The installed console command is `job-answers`.

For an answer that depends on a particular internship or recruiting cycle,
bind with `--position-id JOB_ID`. Pass the same `--position-id` to `resolve`
or `observe`. Omitting it or supplying a different ID withholds the answer.
Rebinding without the option does not remove the restriction. The SQLite
questions table includes `required_position_id` for downstream consumers.
Browser adapters must get the current position ID from the page, not copy it
from the stored answer. Confirmed local fields may use `fill` when the user
authorizes automatic reuse; built-in personal-field defaults remain `review`.

Extend personal questions without changing code:

```text
job-answers add-field personal.us_work_authorization "US work authorization" --type choice --policy review
job-answers observe "Can you verify your legal right to work in the US?" --site https://example.test --section "Position Specific Questions" --kind select --options Yes No
job-answers bind QUESTION_ID personal.us_work_authorization
```

Supported field types are `text`, `integer`, `boolean`, `choice`, and
`multi_choice`. Bindings reference keys, so values stay single-source. Duplicate
field creation or rebinding to a different field fails instead of overwriting
existing knowledge. First version has a Python API and CLI, not a management UI
or a browser watcher; the future Chrome adapter should call `observe` for each
encountered control and act only on compatible, authorized answers.
