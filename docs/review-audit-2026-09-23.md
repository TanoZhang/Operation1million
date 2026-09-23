# Review and eligibility audit - 2026-09-23 UTC

Status: three defects reproduced offline; no application fixes or deployment.
Inspected source: `b2c9340f84dbe5f7fb020301c2d724af32587424`.
Last fetched main: the same SHA, checked again before publishing this report.
Both other standing branch histories were inspected: Claude has no unmerged
commits; Codex carries this audit's documentation. Remote references cannot
reveal another machine's uncommitted work.

Scope: the two latest changes (`78c8f8e`, `b2c9340`) and their storage,
eligibility and Review consumers. Synthetic fixtures only. This is not a
complete repository audit or a measurement of production incidence.

## Reproduce

Run from this checkout:

```powershell
python docs/review-audit-repro-2026-09-23.py
```

The harness prints its imported source path, creates temporary SQLite/log/
ledger files and uses the real storage, queue and loopback detail endpoint.
Expected on the inspected source: six tests, three failures, three passing
controls, exit code 1. Assertions express the intended behavior so these can
become regression tests when the defects are fixed.

Existing focused tests all pass: degree (17), Review descriptions (20),
Review rules (46), storage (94), for 177 total. These do not cover the
three failing boundaries below.

## R1 - Empty HTML refresh deletes the only readable description (P2)

Location: `src/jobdisco/store.py:664`, `merge_raw`.

1. Store an RTL posting with only
   `descriptionTeaser: "RTL design role requiring 5 years of experience."`.
2. Refresh the same identity with `description: "<p></p>"`, omitting the teaser.

Expected: preserve the readable teaser, show it in Review, and continue to
exclude the posting for its five-year requirement.

Actual: the teaser is removed; the detail endpoint returns an empty description;
the posting enters the pending queue. Observed tuple of teaser, detail text and
pending count: `(None, '', 1)` instead of `(original, original, 0)`.

Cause: the new guard checks the raw string's `.strip()`, so nonempty tags count
as a full description and authorize deleting the old teaser. The data is already
gone before `slim` or the Review renderer runs. It is absent from the new stored
snapshot; older append-only history is not erased.

This is a regression introduced in `78c8f8e`: executing the prior `merge_raw`
from `583bfd7` on the same values preserves the teaser. Supplying the teaser
alongside the empty HTML also passes, explaining why the existing empty-HTML
test does not catch a refresh that omits it.

Suggested correction: require readable description content before retiring
previous teaser fields. Preserve the existing empty-HTML and supplied-teaser
controls, and test through two storage writes.

## R2 - A null teaser preserves an obsolete rejection (P2)

Location: `src/jobdisco/store.py:669`, `merge_raw`.

1. Store the same five-year teaser.
2. Refresh with a full description requiring one year and
   `descriptionTeaser: null`.

Expected: the obsolete five-year teaser no longer governs eligibility; Review
shows the current one-year requirement and includes the posting.

Actual: the old teaser remains beside the new description. Eligibility returns
`required_experience_over_2_years`, the HTTP detail includes the obsolete text,
and the queue has zero pending postings. Omitting the teaser key with the same
new description correctly yields one pending posting.

Cause: key presence prevents the stale-teaser removal, then the update loop
ignores `None` and retains the previous value. The new stale-text fix therefore
does not cover the common JSON distinction between an absent key and a null
value. This residual behavior predates the latest patch.

Suggested correction: distinguish a current readable teaser from an absent/null
teaser when a readable full description supersedes it. Do not globally change
null handling for unrelated provider metadata.

## R3 - A conditional PhD instruction becomes a mandatory degree (P2)

Location: `src/jobdisco/degree.py:160`, `description_only`.

Trigger, under the title `RTL Design Engineer`:

> Build RTL blocks. If you are pursuing a PhD, you must return to your degree
> program after the internship.

Expected: this conditional instruction does not establish that only PhD
applicants may apply, so it must not cause a `phd_only` rejection.

Actual: `phd_only` returns `True`, the shared eligibility entry point returns
`phd_only`, and the persisted posting disappears from the pending queue.

Cause: `STATED` matches the substring `pursuing a PhD`; the decision never
checks whether that statement is conditional. Preference and negation guards
do not cover it. A positive control, `Candidates must be pursuing a PhD in EE.`,
still rejects as intended. This is an existing coverage gap, not attributed to
the latest preference-word additions.

Suggested correction: recognize conditional scope around a degree statement
without letting an unrelated condition suppress an unconditional requirement.
Retain the positive control and add mixed-clause cases before implementing.

## Investigation checks

The storage hypotheses were (in order) a merge eligibility/value-presence
error, deletion by `slim`, and reinterpretation by Review. The first wins:
calling `merge_raw` alone already produces both wrong payloads, and the real
store/HTTP/queue path reproduces their consequences. The PhD false rejection
is present both in the degree predicate and the shared consumer. No production
data, collection requests, paid queries or application decisions were used.
