# Application autofill framework

Local source work on base `9d3e5ae9138116033a8271fa8172b3a8abd00404`, including
the prior Codex DOM fixes. First implementation: 2026-10-01 America/Los_Angeles.
The user requested Workday, Greenhouse and Lever first, and automatic filling of
every known compatible answer. Final application submission remains manual.

## Runtime responsibilities

| Module | Responsibility |
| --- | --- |
| `extension/ats-adapters.js` | Host-bound ATS registry, native field wrappers, label and control metadata. Workday, Greenhouse and Lever have entries; other hosts use the generic scanner. Host matching checks domain boundaries. |
| `extension/content.js` | Native text/number/select/radio controls; accessible single-choice listboxes with `aria-controls`/`aria-owns`; bounded option waits, exact option selection, sequential filling and post-click verification. Rechecks the question/position snapshot before mutation. |
| `extension/answer-engine.js` | Pure known-answer assessment, canonical basic-question definitions, approved aliases, control compatibility, actual option translation, scope/context checks and explanations. No DOM, network, secrets or model dependency. |
| `extension/popup.js` | Profile loading/learning, scan orchestration, per-position work route, automatic known-answer filling and a question-by-question matching report. |
| `extension/profile.{html,js,css}` | Browser-local onboarding, separate education fields, context-specific answers, explicit seed import and user-confirmed mappings for unknown wording. |

The education schema separates current and previous school, major, degree,
graduation month and year. Structured `profile.education` records retain the
confirmed full history. Bare repeated "School" or "Degree" questions require a
confirmed row-specific mapping; the engine does not assign a university by DOM
order or merge a degree name into a major. Settings show all canonical fields
separately. The saved canonical school name is preferred over an abbreviation;
approved aliases are considered only when the exact canonical option is absent.
Repeated sections receive transient row-local identities. Mapping one row never
binds a second row, and replacing a row invalidates its mapping. They require a
fresh association on a newly rendered page until a provider-specific stable
education-record adapter is available.

## What counts as a known answer

`assessKnownAnswer(profile, question, positionId, context)` returns the canonical
field, `known_answer`, status, proposed answer, match provenance and explanation.

1. Match an existing explicit mapping or a complete exact approved alias.
   Preserve negation, country and time qualifiers. An ambiguous match stays empty.
2. Check site and position restrictions. Missing/different context withholds the
   answer. Identity fields under emergency-contact sections are not assumed to
   describe the applicant.
3. Verify a supplied answer and compatible control type. Missing values remain
   missing; no personal answers are seeded in tracked files.
4. Translate to an actual option using the canonical value first, then approved
   aliases. An absent or ambiguous option is not selected.
5. For a dynamically populated listbox, return `verify_options`: the meaning is
   known, but the content script must read and verify the actual option before
   selection. Typeahead searches with the canonical full name; it does not pick
   the first or closest result. Filling is sequential, with bounded waits and
   displayed-value/expanded-state verification after clicking.

Current work authorization, current sponsorship, future sponsorship and
"now or in the future" sponsorship are separate questions. Confirmed conditional
answers use `field.context_answers`; a per-position `work_route` chooses the
confirmed branch. Unknown route is `context_required`, not an inferred Yes/No.
The engine records user-supplied answers and does not infer immigration answers
from a visa label. Personal facts are in ignored local files and private browser
storage, not this document or repository.

The user's automatic-fill preference defaults to enabled, including answers
whose stored policy was previously `review`. A settings switch restores the
individual checklist. This authorization does not expand a saved answer's site
or position scope. Unknown mappings can be linked to a compatible existing field
in the setup page; mapping requires a supplied valid answer and actual native
options where available. Learned conflicts preserve the existing answer.

## Usage

Reload the unpacked extension after updating to 0.5.0, and refresh any application
page holding its previous content script. Open the popup, choose **Set up your
answers**, and fill the unanswered basics. If a browser profile already exists,
**Import answers saved on this computer** imports confirmed nonempty seed fields,
retaining learned fields/mappings and avoiding blank-value erasure. Use **CPT** or
**Other / non-CPT** for the current position when an answer depends on it.

The popup explains every recognized question. Custom controls lacking an owned
accessible option model, cross-origin embedded forms, file uploads and automatic
multi-step navigation are not implemented by this version. ATS detection is not
proof that every variant of that provider's application form is supported.

## Declared field identity (0.5.1, 2026-10-02)

Added by Claude at the user's request, on Codex's 0.5.0 framework. A label is
not the only exact statement of a field's meaning: each ATS gives its standard
applicant fields fixed identifiers, and HTML's `autocomplete` attribute lets a
page name a field outright. `ats-adapters.js` now reports such a field as
`declared_field`, and `answer-engine.js` treats it as one more exact alias:

- Workday: form-kit paths (`name--legalName--firstName`, `phoneNumber--phoneNumber`,
  `address--city`, ...) and the older automation ids (`legalNameSection_firstName`,
  `phone-number`, `addressSection_city`, ...). Workday labels such as "Given
  Name(s)" and "Family Name" matched no alias before. Local-script names
  (`...firstNameLocal`) and the phone extension are different fields and stay unbound.
- Greenhouse: `first_name`, `last_name`, `email`, `phone`, and the
  `job_application[...]` names of the older boards.
- Lever (`name`, `email`, `phone`) and Ashby (`_systemfield_name`,
  `_systemfield_email`, `_systemfield_phone`). Both ask for one full name, which is
  the legal full name field.
- Any site: `given-name`, `family-name`, `name`, `email`, `tel`, `street-address`,
  `address-line1`, `address-level1/2`, `postal-code`, `country-name`. A
  `section-`, `shipping` or `billing` token is not taken.

Only exact identifiers count, and only on the provider's own hosts. A wrapper's
identifier counts only when it holds that one control. A label naming a
different field makes two candidates, which is ambiguous, so nothing is filled.
A provider identifier needs no section check, because it names the applicant's
own field by definition; an autocomplete token gets the same section check as
a label, so an emergency contact's "given-name" is not the applicant's.
Repeated sections still never auto-bind. Tests: `tests/autofill-ats-fields.cjs`
(eight fixture cases, red on 0.5.0 where the behaviour is new).

Sources, read for identifiers only; no code is copied:
[Greenhouse application fields](https://github.com/grnhse/greenhouse-api-docs/blob/master/source/includes/job-board/_applications.md),
[Ashby form definition](https://developers.ashbyhq.com/docs/creating-a-custom-careers-page),
Workday paths as rendered in
[application-autofiller](https://github.com/Jamalfox85/application-autofiller) and
[Workday_Automater](https://github.com/chetaniitbhilai/Workday_Automater),
selector tables in [JustHireMe](https://github.com/vasu-devs/JustHireMe) and
[jobSearch](https://github.com/Mayhopar/jobSearch) (`_systemfield_phone`), and
[jobops-copilot #289](https://github.com/Taleef7/jobops-copilot/issues/289)
(Greenhouse/Lever/Ashby/Workday ids). Where two sources disagreed (Ashby `name`
against `_systemfield_name`), the provider's documentation decided.

## Research evidence

Reviewed 2026-10-01; no third-party source code is copied or vendored.

- [Lever's official Postings API](https://github.com/lever/postings-api): job and
  hosted application URLs, and the documented limitation that custom application
  questions are not exposed. Discovery APIs therefore cannot replace DOM reading.
- [Greenhouse's official Job Board API](https://docs.greenhouse.io/job-board.html):
  provider metadata and application-question model. Collection and applicant form
  interaction remain separate responsibilities.
- [Job App Filler](https://github.com/berellevy/job_app_filler): inspected its
  Workday field-wrapper selectors, simple/searchable dropdown implementations and
  Greenhouse native/custom control separation. Our adapters and sequential
  verified listbox filling are independently written for this extension.
- [Little AI Helper](https://github.com/ritsth/job-autofill-extension): inspected
  its documented per-ATS adapter architecture and profile workflow.
- [ApplyAI](https://github.com/muhammad-saadd/applyai): inspected its documented
  detect/extract/plan/fill workflow. No LLM or API key is added to our matching path.
- [ats-autofill-engine](https://github.com/ebenezer-isaac/ats-autofill-engine): its
  repository tree currently supplies design plans, so it is a design reference
  rather than a runtime dependency or proof of working platform coverage.
- [Simplify's public GitHub organization](https://github.com/SimplifyJobs) and
  [Copilot product page](https://simplify.jobs/copilot): no public Copilot
  implementation was found in this research. Public job-list repositories are
  not the extension's source.

## Validation

Offline Node/jsdom fixtures run actual extension scripts against fictional forms
and answers. They cover known/unknown/ambiguous questions, scope and negation,
degree/major separation, native enum aliases, custom and searchable dropdowns,
failed-search restoration, conditional sponsorship, local setup/import and manual
question binding. The earlier ten DOM regressions continue to run.
See `application-autofill/README.md` for installation of the optional test runtime.
These are fixture results, not live Workday/Greenhouse/Lever application evidence.

Results: 38 focused autofill tests passed. Full suite on the base SHA above plus
the local work ran 942 tests: 933 passed, nine environment skips. A subsequent
profile-page contextual-binding follow-up passed all 15 framework cases. Code is
local and uncommitted; it has not been pushed, deployed or verified on a real
applicant page.
