# Debug report, round 7 - 2026-09-20 Pacific

Three additional experience-filter defects reproduced through paid collection and Review. No priority labels and no business-code changes.

## Evidence

Audit base: `1e42525`, claim `4f18bc3`. Remote main/claude inspected at `ef6d4b3db5edd81cbfb0c86c67b334caf748b3e1`. All cases pass as defect reproductions with imports from both the audit worktree and `D:/Operation1million/src` (the user's staged and unstaged fixes). The working `experience.py` SHA256 is `2D1B2E269D5DFAD8173CC53FA35C9E0CDBE411FF4478BA69EBBC5A86C634E038`.

Each fixture runs `collector.main` using synthetic paid HTTP responses, followed by `applications.queue`. All four problematic descriptions are accepted, persisted and shown as pending. `entry_override` is false; `effective_experience_years` is null. Controls run through the same path: five mandatory years are rejected, five preferred years and two mandatory years are accepted. This demonstrates parser misses, not a disabled filter or an internship override.

All state is temporary. External transport is blocked or mocked. No provider calls, paid charges, production data edits, deployment or full-suite run. These are synthetic examples of explicit requirements, not claims about their frequency in live postings.

## B31: An optional skill erases a mandatory experience requirement in the same sentence

Location: `src/jobdisco/experience.py`, clause splitting and `OPTIONAL.search(clause)`.

Input: `5 years experience required, FPGA knowledge preferred.`

Expected: the explicitly required five years remain mandatory; FPGA knowledge alone is preferred.

Actual: comma splitting only recognizes a following number. The optional skill therefore stays in the same clause as the required experience. Finding `preferred` causes the entire clause to be discarded. The posting reaches pending Review with unknown required years.

Suggested direction: bind requirement/preference markers to their corresponding clauses instead of allowing any optional marker to override all requirements in the sentence. Preserve the existing valid behavior of `5 years experience, preferred`; indiscriminately splitting every comma would break it. Test both orderings of required experience and optional skills.

## B32: A required heading does not make the following experience bullet mandatory

Location: `src/jobdisco/experience.py`, heading handling and the candidate check using `EXPERIENCE`, `REQUIRED`, `DEGREE` or standalone years.

Input:

```text
Required qualifications:
3 years of RTL design.
```

Expected: three years of the named work are required under the explicit heading.

Actual: the heading only resets `optional_section`; it does not retain a positive required-section context. The next line lacks the literal words `experience`, `required` or a degree, and is not just a bare years expression. Its three years are discarded, and Review shows the posting.

Suggested direction: track required-section context and use it when interpreting subsequent work-duration bullets. Keep safeguards for non-work durations such as roadmaps, degrees and programs, and define where section scope ends. Include both plain-text and HTML/structured qualification inputs.

## B33: Explicit mandatory numeric formats are treated as unknown

Location: `src/jobdisco/experience.py`, `NUMBER` and `YEARS` patterns.

Two examples demonstrate the format gap:

| Input | Expected minimum | Actual |
| --- | --- | --- |
| `Minimum 3-year experience in RTL design.` | 3 | null, accepted |
| `Minimum 2.5 years of professional experience.` | 2.5 | null, accepted |

The year pattern requires whitespace before `year`, and the numeric pattern only supports integers. The decimal guard prevents matching the trailing 5 as a separate number, correctly avoiding a wrong value but leaving the explicit 2.5 requirement unrecognized.

Suggested direction: support hyphenated year units and fractional explicit experience bounds while preserving non-work exclusions. Do not truncate 2.5 to 2; that changes whether it exceeds the two-year threshold. Add controls for `2-year degree`, `5-year roadmap`, optional fractional years and exactly two required years. These two formats are grouped as one numeric-format finding rather than separate bug counts.

## Reproduction

```powershell
$env:PYTHONPATH='D:/Operation1million/src'
& 'D:/Operation1million/.venv/Scripts/python.exe' docs/audit-repro-round7-2026-09-20.py
```

Run from the audit worktree. The script reuses the adjacent round-5 transport harness. Select `D:/Operation1million-file-audit/src` to check the older committed application source. Assertions capture current defects; promote corrected expectations into regression tests when fixing them.
