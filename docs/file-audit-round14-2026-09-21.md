# File audit, round 14: source validation and configuration

## Scope and evidence

Inspected main `5e78ae814514115866532bf96f8397d0331354d2`, with the existing
round-13 audit documents preserved on the audit branch. Read every function in
`validate_sources.py`, `query_catalog.py` and `local_config.py`; then traced
their request, pause, CLI and configuration consumers. Also reviewed the whole
`jsearch.load_plan` validation path and the search-catalog migration SQL.

Seven new findings are B74-B80. No business-code changes, provider probes,
production database access, paid calls, real credential reads or deployments.
All fixtures and databases are temporary. Claims below are offline evidence,
not assertions that a provider currently sends the demonstrated HTML.

Reproducer: `docs/audit-repro-round14-2026-09-21.py`.

```powershell
D:/Operation1million/.venv/Scripts/python.exe D:/Operation1million-file-audit/docs/audit-repro-round14-2026-09-21.py
```

It explicitly imports the source beside the report, mocks HTTP and sleeps,
uses real pause databases and parsers, and asserts the defective outcomes.
Request-builder, JSON-adapter, XML/HTML and synthetic credential controls pass.
Any unmocked robots HTTP request raises instead of accessing the network.

## B74 - A malformed source configuration aborts the whole validation run

**Location:** `src/jobdisco/validate_sources.py:240-255`, especially the
`request_for(source)` call at line 241 before the exception boundary.

**Trigger:** An enabled Workday row has `tenant` but lacks `site`. Source field
JSON can be syntactically valid while missing this required field. The helper
raises `KeyError` before `validate` reaches its source-level error handler.

**Executed result:** Run the actual `main` with three sources: valid, malformed,
valid. Only the first source reaches the mocked transport. The second raises
`KeyError('site')`, the third is never examined, and no new CSV is written. An
existing report still contains its previous contents, with none of the first
probe's new evidence.

**Expected:** Record a configuration failure for that source and continue,
or validate all configurations before starting any probes and fail with an
explicit catalog error. The current ordering does neither.

**Fix direction:** Bring request construction inside the source error boundary
and initialize the result before it, or add a complete preflight pass before
transport. Keep source identity and missing-field details in the report.

## B75 - An empty enabled catalog truncates the previous report, then crashes

**Location:** `src/jobdisco/validate_sources.py:362-363`.

**Trigger:** Both source tables have no enabled rows. The catalog reader returns
an empty list, which is a valid result when sources have all been disabled.

**Executed result:** Start with a nonempty prior report and make `load_sources`
return `[]`. `main` opens the output in write mode, truncating the file, then
reads `rows[0]` for CSV fieldnames and raises `IndexError`. The old report is now
zero bytes. No transport is invoked.

**Expected:** A clear empty-catalog outcome and a valid header-only report, or
preservation of the prior report if the command refuses to run.

**Fix direction:** Define report columns independently of the first result.
Write to a temporary file and replace the prior report only after the entire
report is successfully serialized. Add an explicit zero-source control.

## B76 - Apple validator loses titles containing normal nested markup

**Location:** `src/jobdisco/validate_sources.py:170-191`.

The first regex alternative matches a `job-title` opening anchor without
capturing its href or title. The fallback only captures titles containing no
`<` character. Together these accidentally support plain text but reject a
title wrapped in a span.

**Executed input:**

```html
<a class="job-title" href="/en-us/details/200123456/rtl-engineer"><span>RTL Engineer</span></a>
```

With the span removed, `apple_items` returns one job. With it present, the
validator returns zero and reports `download_ok_needs_extractor`. The existing
production `collector.html_items` returns the same one job in the nested case.

**Expected:** Adding inline markup to a readable title must not make a working
extractor appear unavailable.

**Fix direction:** Reuse the production HTML extraction path or parse anchors
with the existing HTML parser. If retaining a regex, fix the alternation and
capture href/title for both class variants, including nested title markup.

## B77 - A harmless CDN reference creates a persistent 24-hour pause

**Location:** `src/jobdisco/validate_sources.py:206-219` and `:325-332`.

`html_signal` searches raw markup for `akamai`, treating any occurrence as a
verification challenge. That includes nonvisible script URLs and metadata.
Unlike a false report alone, this writes the same source cooldown ledger that
the collector uses.

**Executed input:** A normal Careers page contains an external script whose
path is `/akamai/metrics.js`, with visible text `Careers and open positions`.
There is no challenge text or challenge element. On a generic HTML source,
`validate` returns `paused` and writes a retry time approximately 86,400 seconds
in the future. A new real `SourcePolicy` instance then refuses collection.

**Expected:** CDN branding or an asset reference is not sufficient evidence of
an access challenge and must not create durable refusal state.

**Fix direction:** Detect explicit visible challenge text and known challenge
elements, sharing the logic already used in `Collector.fetch`. Keep actual
HTTP refusal and rate-limit handling intact. This finding is distinct from
B78: it creates a pause from evidence that is not a challenge.

## B78 - Successful extraction bypasses an explicitly detected challenge

**Location:** `src/jobdisco/validate_sources.py:275-332`, especially the Apple
and Achronix early returns before `html_signal`.

**Trigger:** An HTTP 200 HTML document has visible `Human verification` text
and retains a parseable job link, for example inside the page template.

**Executed result:** The detector alone rejects the fixture as a challenge.
The actual `validate` function instead extracts the one Apple link, returns
`usable`, and writes no pause. The source pause table remains empty.

**Expected:** A detected access challenge must stop validation before successful
extraction can declare the route usable. A retained link does not establish
that the page is accessible without the verification step.

**Fix direction:** Perform the shared challenge check before any HTML extractor
can return success. Test both a clean page with jobs and a challenge page that
still contains parseable jobs. This is the converse of B77, with a separate
control-flow cause: valid refusal evidence is never consulted.

## B79 - A scalar regex setting silently becomes a list of one-letter filters

**Location:** `src/jobdisco/jsearch.py:122-127`, then `any_of`, `excluded` and
the other pattern consumers.

`load_plan` compiles every item in each pattern group but does not first check
that the group is a list of strings. TOML allows a string at that location, so
the validator iterates and compiles its characters. The runtime consumers also
iterate the string character by character.

**Executed comparison:**

```toml
# Control: RTL Engineer remains eligible under this exclusion.
[filter]
exclude_title_patterns = ["senior"]
```

```toml
# Defect: accepted by load_plan, but interpreted as s|e|n|i|o|r.
[filter]
exclude_title_patterns = "senior"
```

Both plans load successfully. The scalar form incorrectly hard-rejects
`RTL Engineer` and `FPGA Intern`; the array control does not reject the RTL
title. No paid transport is needed to demonstrate the changed decision.

**Expected:** Reject an incorrectly typed filter before collection or review
uses it. A simple missing pair of brackets must not silently broaden an
unconditional rejection rule.

**Fix direction:** Validate the filter table and every pattern group as an
array of strings before compiling expressions. Include scalar strings, tables,
mixed element types, and a valid one-element array in regression coverage.
The same shape error can affect scoring and keep/evidence groups, so fix the
shared validation boundary rather than only the exclusion consumer.

## B80 - Query migrations for different --db paths collide on one backup file

**Location:** `src/jobdisco/query_catalog.py:11-24` and the `--db` option in
`main` at line 36.

The migrator accepts an explicit database path but always stores its first
backup at one repository-global filename. A backup made for database A then
blocks the unrelated first migration of database B.

**Executed result:** Create two independent legacy catalogs, `first.sqlite`
and `second.sqlite`, each with a company table and no search-query table.
Migrating the first succeeds and exposes 18 query rows. Migrating the second
raises `FileExistsError` because A's backup exists. B remains unmigrated.
The original backup is preserved; no data-loss claim is made for this case.

**Expected:** Each `--db` target has its own pre-migration backup identity.
Refusing to overwrite a backup of the same target is sensible, but a backup
of a different database should not prevent the requested migration.

**Fix direction:** Derive the backup location from the canonical database path
or accept an explicit per-target backup path, keeping the no-overwrite check.
This affects the legacy `job-queries --db ... --migrate` tool. Per project
documentation, the production paid collector executes TOML queries and does
not execute this legacy SQLite catalog; do not attribute production paid
discovery omissions to this finding.

## Coverage inventory and controls

| File / function | Evidence |
| --- | --- |
| `validate_sources.Source`, `load_sources` | Read both table queries, enabled filtering, field decoding and connection lifetime. Existing success/decode-error resource tests pass. |
| `workday_request`, `oracle_request`, `phenom_request`, `request_for` | Read all construction branches; five valid routing controls pass, including both Workday host styles. B74 exercises missing required fields through CLI main. |
| `json_items` | Read every supported provider branch. Eight valid payload controls pass. Unknown-provider fallback is not claimed to validate arbitrary JSON. |
| `xml_items` | Read provider gate, URL matching and title derivation; simple sitemap extraction control passes. No live sitemap coverage claim. |
| `apple_items`, `achronix_items` | Read both Apple regexes and Achronix title/link extraction. B76 plus positive plain-title and table-link controls. |
| `html_signal` | Read block terms, generic signals and fallback. B77 and B78 demonstrate raw-text and ordering problems. |
| `validate` | Read request construction, pause/pacing, transport, status handling, XML/JSON/HTML branches and exception outcomes. Real temporary pause persistence for B77-B78; no live HTTP. |
| `main` | Read catalog/session setup, report directory, all probes, CSV write, counts and exit. B74-B75 drive main directly; existing report-directory control passes. |
| `query_catalog.migrate`, `load_queries`, `main` | Read target existence, backup, SQL execution, readonly query and CLI. B80 uses real SQLite files; existing migration idempotence and fresh-schema equivalence tests pass. |
| `001_search_queries.sql` | Read table constraints, update trigger, initial seed guard and transaction. The existing tests verify preserved edits/deletions and fresh-schema parity. |
| `local_config.load_credentials` | Read the whole loader. Controls verify absent file, UTF-8 BOM, quoted synthetic value, ignored unsupported key and preexisting environment precedence. No real secret file was read. No new finding in this function. |
| `jsearch.load_plan`, `validate_budget`, `fallback_plan` | Read full configuration validation and fallback construction; B79 targets a silent acceptance rather than an error that already fails closed. Other JSearch functions were traced where needed, not claimed as a new complete module audit this round. |

Not promoted to findings: unsupported dotenv shell syntax is not a documented
contract; unknown query-tier fallback may be deliberate compatibility; a
missing catalog raising an error is not by itself a silent collection bug.
Previous B09 output-directory creation remains fixed.

## Verification record

All seven defect assertions and the adapter/credential controls passed against
the inspected source. Existing suites: 118 tests, no skips, no failures:

| Suite | Tests | Seconds |
| --- | ---: | ---: |
| `test_validator_resources.py` | 2 | 0.008 |
| `test_search_queries.py` | 2 | 0.003 |
| `test_collection_policy.py` | 15 | 0.246 |
| `test_jsearch.py` | 99 | 53.581 |

The JSearch CLI usage error printed by its negative test is expected; the
suite exited 0. The final synchronization check found no changes to main during this
audit. No business source or another agent's work was modified.

SHA-256 of checked-out source files, including their local line endings:

| File | SHA-256 |
| --- | --- |
| `validate_sources.py` | `F14847714F85B55D4E7C356E11B100D834A2638E42AB289427DE178C30701B25` |
| `query_catalog.py` | `4A2E804045719BC407CDF6C4E2D77D813B6C49F888A624E1AC7FC7D17BBF8B09` |
| `local_config.py` | `4BDFB7E2C80106AE82EDE1DD9E15789069ECD4D68E7A5D659F4D020509D95E03` |
| `jsearch.py` | `D43193482563CEC8B0D143E9C792C1ECF7616C4AC9495A9311CDFC724E913E33` |

Next scope: revisit cross-module recovery and provider-specific contracts
against the fixes now on main, with complete function inventories and concrete
offline counterexamples rather than repeating already fixed findings.
