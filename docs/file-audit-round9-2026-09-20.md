# File audit, round 9: JSearch

## Scope and evidence

Reviewed `src/jobdisco/jsearch.py` from configuration through final persistence,
including its nested functions, before moving to another module. Six new root
causes, B44-B49, are reproduced below. Variants sharing a cause are grouped.
No priority labels and no business-code changes.

Tested source: `D:/Operation1million`, clean main commit
`5166930b284bb070f38865685ec279c7d545de2f`. The audit worktree was fast-forwarded
to that commit before writing this report. `origin/claude` at inspection was
`1aa84564c7a22311f6ce51b5bb9d8cb9e446b9c0`; its pending changes to applications,
Review and storage were inspected for overlap but are not claimed tested here.
Its JSearch source matches the inspected main version.

All new cases use synthetic data, temporary databases and local mocked HTTP
responses. B44, B45, B46 and B49 also execute `collector.main`; B47 exercises
`collect` with real durable cursor state; B48 exercises normalization and
`collect`. No provider was contacted, no production records were examined and
no actual page credits were spent. A credit mentioned below is a reservation
in the temporary test ledger.

Reproducer: `docs/audit-repro-round9-2026-09-20.py`. It imports the reusable
`run` helper from `docs/audit-repro-round5-2026-09-20.py` without executing that
older report's defect assertions.

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round9-2026-09-20.py
D:/Operation1million/.venv/Scripts/python.exe -m unittest discover -s D:/Operation1million/tests -p test_jsearch.py
```

The reproducer passed. The existing JSearch suite passed: 90 tests, 43.115
seconds, exit 0, no skips. Passing existing tests does not establish that the
six new cases are correct; the reproducer explicitly demonstrates their current
incorrect outcomes.

## B44: Search provenance becomes evidence about the job

Locations: `jsearch.py:313`, `jsearch.py:421`, `jsearch.py:456`,
`jsearch.py:480`, `jsearch.py:675`.

`normalize_job` appends `raw.discovery_queries`. `description_text` then walks
that field as if it were employer prose. Both the experience gate and relevance
score consume it. This is not a publisher mentioning an internship: the word
was added by the collector itself.

Tested with an ordinary `RTL Engineer` requiring `5 years of experience`:

| Search phrase | Decision |
| --- | --- |
| `RTL` | `required_experience_over_2_years` |
| `RTL Intern` | accepted |
| `RTL New Grad` | accepted |

The last two phrases exist in the shipped plan. A complete mocked paid pass
using `RTL Intern` stores the role and leaves one pending Review group.

The same leak also fabricates domain evidence. An `RF Engineer` whose entire
description is `Maintain radio antennas.` scores 0 and is rejected with query
`RF`, but scores 38 and is accepted with `RF FPGA RTL ASIC`. This second phrase
is a synthetic manual-query example, not a claim about the shipped catalog.

Suggested correction: keep provenance in raw evidence but exclude it from
semantic extraction at every nesting level. Recheck stored rows because the
same extractor is used by Review. Add a property test that changing only
discovery provenance cannot change eligibility or confidence.

## B45: Invalid normalized fields crash a paid page, losing its valid sibling

Locations: `jsearch.py:304`, `jsearch.py:312`, `jsearch.py:668`,
`jsearch.py:784`; shared normalization in `collector.py:156`.

The item-level exception boundary only protects `normalize_job`. That function
can return a title which becomes empty after cleaning, or an object-valued
posting date. Neither is rejected at the item boundary. Both travel through
filtering into the page checkpoint, where SQLite raises outside that boundary.

Tested through `collector.main` with a page containing one valid job followed
by one malformed job:

| Malformed value | Result | Jobs stored, including valid sibling |
| --- | --- | ---: |
| `job_title = "   "` | `IntegrityError: CHECK constraint failed: length(trim(title)) > 0` | 0 |
| `job_posted_at_datetime_utc = {"date": "2026-09-20"}` | `ProgrammingError: type 'dict' is not supported` | 0 |

These are two violations of the same missing normalized-record contract, not
two separately numbered bugs. Current transaction rollback correctly prevents
partial index commits; the remaining defect is letting an invalid item abort
the page and collector instead of counting it as malformed.

Suggested correction: validate the cleaned title and normalized scalar types
before returning a row. Preserve original provider values in raw. Count the bad
item, retain its valid siblings, and report a partial page. Do not swallow
general database failures as if they were malformed provider records.

## B46: Regex alternation changes valid configured patterns

Locations: `jsearch.py:120`, `jsearch.py:318`, `jsearch.py:330`.

`load_plan` accepts each expression independently, but `any_of` combines them
into one regex. Noncapturing wrappers do not isolate captures inside each
expression.

Tested consequences:

- `['(director)', '(senior)\\s+\\1']` matches `senior senior RTL Engineer`
  when searched separately but does not match after joining: the second
  pattern's backreference now refers to the first pattern's group.
- Two separately valid patterns declaring `(?P<level>...)` pass `load_plan`
  but raise `re.error` when combined. The complete collector reproducer reserves
  one temporary credit, receives its synthetic page, and then aborts compiling
  the filter.

This is a configuration-contract defect. The report does not claim that the
currently shipped pattern list contains these constructs.

Suggested correction: retain separate compiled patterns for expressions whose
semantics cannot safely be combined, or explicitly restrict and validate the
supported syntax before any request. Include captures, named groups and inline
flags in equivalence tests rather than relying only on current catalog titles.

## B47: A malformed short page permanently settles the backfill cursor

Locations: `jsearch.py:670`, `jsearch.py:796`, `jsearch.py:800`.

The collector records normalization failures but decides exhaustion from the
original response length alone. A short response containing one malformed
record and no usable jobs becomes a completed sweep, even though its report
correctly says `partial`.

Tested with a real temporary `RequestGuard` cursor database:

1. Page 1 returns `[{"job_id": "lost"}]`, with `exhausted=True`.
2. No row is persisted; the malformed count is 1.
3. Cursor becomes `(2, True)`.
4. A second invocation can now supply the corrected job, but makes zero fetch
   calls because the stored cursor already says exhausted.

This affects the backfill sweep in the current billing period. A separate daily
pass may still rediscover the job; permanent loss across all collection modes
was not tested or claimed.

Suggested correction: do not make an unresolved malformed page irrevocably
complete. Either retain a bounded retry cursor for that page or durably
quarantine enough raw evidence for local recovery before advancing. Preserve
the existing safeguards against repeatedly buying the same unusable page.

## B48: Link selection neither validates candidates nor falls back after failure

Locations: `jsearch.py:300`, `jsearch.py:303`; URL check in `collector.py:156`.

The first truthy primary link wins before URL validation. With a valid
`job_google_link`, either `job_apply_link = " "` or `javascript:void(0)` causes
the whole job to be discarded as malformed. Setting that primary value to null
instead successfully uses the identical secondary link. The same ordering
also prevents reaching a usable `apply_options` candidate.

The validation itself checks only the scheme: `job_apply_link = "https://"`
is returned as the normalized job URL despite having no host and despite the
presence of the valid secondary link. This normalization outcome was tested;
no external URL was opened.

`collect` was also tested with a whitespace primary and valid secondary:
zero accepted rows and one malformed row.

Suggested correction: select the first structurally valid public HTTP(S)
candidate, requiring a host and a meaningful link. Check the primary, Google
and apply-options candidates in their intended order. Do not discard valid
alternate evidence solely because an earlier candidate is nonempty.

## B49: Sibling JSON field ordering changes required experience

Locations: `jsearch.py:447`, `jsearch.py:460`, `jsearch.py:474`.

Structured extraction emits a `preferred qualifications` heading, but does not
end its scope at that field's boundary. A following unrelated `job_description`
inherits the preferred section in the experience parser.

Tested two JSON objects with identical field/value pairs, differing only in
insertion order:

- `preferred_qualifications = "FPGA familiarity"` before
  `job_description = "5 years of experience."`: accepted, one pending group.
- The same two fields in reverse order: `required_experience_over_2_years`, zero
  pending groups.

Both outcomes were reproduced through `collector.main` and Review queue
construction. This is distinct from B44: it occurs with a plain `RTL` search
and no internship or fabricated domain term. It is also distinct from the
earlier single-clause parser cases: the lost boundary is between JSON fields.

Suggested correction: preserve field-local qualification scope while combining
structured evidence. Order-independent objects should produce the same
experience judgment. Test sibling field permutations and nested qualification
containers alongside ordinary headings inside a single description.

## Function coverage ledger

"Read" means traced source, not proof that every possible input was executed.
The entire module was read. Named test coverage below combines the new harness
with the existing 90-test JSearch suite; absence of a new finding is not a claim
of absence of bugs.

| Functions / methods | Inspection and executable evidence | New finding |
| --- | --- | --- |
| `Query.key` | Company scoping, page-independent identity, catalog uniqueness | none |
| `load_plan`, `validate_budget` | Config defaults, caps, clock validation, query validation, regex contract; suite config and budget tests | B46 |
| `fallback_plan` | Read alias construction, explicit company scope and page bounds; suite fallback path | none |
| `SearchFailure.__init__` | Read stop/budget distinction; suite failure and budget reporting | none |
| `page_identity` | Missing, repeated, duplicate and unhashable IDs; new controls and suite | none; B12 fix retained |
| `Client.__init__`, `close` | Read ownership and close path; no new lifecycle fault injected | none |
| `Client.fetch_page`, `fetch`, `fetch_batch` | Read endpoint/auth, parameter construction, page size, close-finally and exceptions; suite request, paging, timeout, throttle and credit tests | none |
| `normalize_job` | Employer lookup, raw preservation, links, ID and normalized field boundary | B44, B45, B48 |
| `any_of`, `excluded`, `needs_evidence`, `employer_excluded` | Read all match consumers; capture/backreference counterexamples and loader-to-paid-intake failure | B46 |
| `relevance` | Read title weighting, short circuit, score curve and supplied-prose path; provenance score counterexample | B44 |
| `description_text`, nested `walk` | Root/nested exclusions, lists, headings, markup and provenance; field-order permutation | B44, B49 |
| `experience_debug`, `rejection_reason`, nested `description` | Read hard-before-keep order, supplied score/prose, short/missing prose and experience mutation; main/queue cases | B44, B49 |
| `search_space`, `tier_rank`, `filter_fingerprint` | New fingerprint/order controls plus suite cursor namespace and tier tests | none |
| `collect`, nested `take` | Read every phase: resume, scheduling, budget/deadline, transport failure, normalization/filter, seen/checkpoint, cursor and final summary; suite and new malformed cases | B44-B49 through their respective paths |

## Continuation

This finishes the planned function inventory for `jsearch.py`. Next is the full
`collector.py` inventory, including each provider adapter and its pagination,
then the full store lifecycle, then quota/policies, ledger/workflow and deploy
configuration. Those files were followed where necessary for this report but
are not being marked fully audited here. Prior round findings are not counted
again. Pending Claude fixes and frontend runtime verification remain separate
from this JSearch module pass.

## Source fingerprints

SHA-256 of tested files, recorded after reproduction:

```text
jsearch.py      180D6C1AB2E81A1915ACD68D90D4C8C9AC4EB937A8A1DC14DADF20DC00C8531D
collector.py    FEA7CD2BF337E66629233CF32AB010E3E936773FA4CCA95880456E25E6963422
experience.py   0313CD7BB4962990E92EA3356D148D72F279C4C9554E9E0FE1541774A2EA8483
applications.py 9E5DE2E96A3FFEDC16172D9FF54AA0858B9497C881A95F072B87A4E8D76E28EF
store.py        C61A8726B5660F0BF0C479393AB95648DFAFE1A2A2913711BCAD073432ACE14A
```
