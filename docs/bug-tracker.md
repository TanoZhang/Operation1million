# Bug tracker, 2026-09-27 bug hunt

One row per defect found and fixed in the bug hunt the user asked for on
2026-09-27. Each has a regression test that was red on the commit before its
fix. The user asked for 100 more after #60; the target is #160. Details and
reasoning per batch are in `docs/architecture.md` ("Bugs found and fixed").

No production index was available in this session: every case below is a
wording fed to the rules offline, and how many live postings each changes is
not measured. Nothing here is deployed until `deploy/vps/install.sh` runs;
title-rule changes also need `job-store --rescore`.

| Batch | Tests | Red on | Fixed in |
| --- | --- | --- | --- |
| 1 (#1-20) | `tests/test_second_bug_hunt.py` | d7be20e | 9dfc8b4 |
| 2 (#21-40) | `tests/test_third_bug_hunt.py` | 9dfc8b4 | c0d6e3b |
| 3 (#41-60) | `tests/test_fourth_bug_hunt.py` | 411c6ab | 40dd87b |
| 4 (#61-80) | `tests/test_fifth_bug_hunt.py` | 1bd0645 | 9451fbe |
| 5 (#81-100) | `tests/test_sixth_bug_hunt.py` | 9451fbe | see git log |

Direction: **removed** = a posting was wrongly hidden; **kept** = a posting that
should go was shown; **display** = wrong text, date or grouping.

| # | Area | Symptom | Direction | Fix |
| --- | --- | --- | --- | --- |
| 1 | experience | "Ideally you know Python." opened a Preferred section | kept | heading = colon or all heading words |
| 2 | degree | same sentence hid "PhD required" | kept | shared `is_heading` |
| 3 | experience | colonless "Must Have", "Job Requirements" headings lost (R6 regression) | kept | heading vocabulary |
| 4 | experience | inline "Preferred: Python" made the rest of the list optional | kept | inline head marks its line only |
| 5 | degree | same through R7's inline head | kept | inline preference not a section |
| 6 | jsearch | `requirements` field had no heading (Codex R5) | kept | `HEADING_KEY` |
| 7 | jsearch | `job_required_skills` key no longer a heading after R6 | kept | field headings end in ":" |
| 8 | location | "West Jordan, UT", "Poland, OH", "Peru, IN" read as abroad | removed | country name in the town part |
| 9 | location | "Albuquerque, New Mexico 87101" read as Mexico | removed | ZIP stripped from parts |
| 10 | location | "Remote - US" unplaced; beside Toronto read as abroad | removed | capital "US" is the U.S. |
| 11 | experience | "4+ years with a BS, or 2+ years with an MS" lost the MS path | removed | `DEGREE_AFTER` |
| 12 | experience | "...; or Master's and 1+ years" split at the semicolon | removed | join "; or" |
| 13 | experience | "Five to seven years" read as 7 | removed | spelled ranges |
| 14 | experience | "Seven plus years" read as nothing | kept | "plus" in `NUMBER` |
| 15 | experience | "3+ YOE" read as nothing | kept | YOE unit |
| 16 | degree | "Masters students are not eligible. PhD required." kept | kept | `_RULED_OUT` |
| 17 | job_text | "Engineer, Austin, TX" left "Engineer," | display | comma separator |
| 18 | ranking | "NCG" not early career | display | NCG |
| 19 | experience | "explore our internship opportunities" made a senior posting entry level | kept | `POINTER` |
| 20 | ranking | "Senior Manager, Campus Recruiting" on Early career | display | `SENIOR` |
| 21 | title rules | "Low-Energy Bluetooth SoC" excluded as energy | removed | hyphen lookbehind |
| 22 | title rules | "(Up to Senior Level)" excluded | removed | `(?<!up to )senior` |
| 23 | citizenship | "citizenship or permanent residency is required" missed | kept | pattern |
| 24 | citizenship | "US Citizens or Green Card holders only" missed | kept | pattern |
| 25 | citizenship | "Required: U.S. Citizenship" missed | kept | pattern |
| 26 | citizenship | "...or authorized to work in the US" hard-passed | removed | `WORK_AUTHORIZATION` |
| 27 | ranking | "2 hours ago", "a day ago", "2 weeks ago" undated | display | `RELATIVE_DAY` |
| 28 | ranking | "Sept 7, 2026", "Sep. 7, 2026" undated | display | `month_text` |
| 29 | collector | "Posted on Sep 7, 2026", "7 September 2026" undated | display | `posted_from_text` |
| 30 | job_text | en/em dash before location left on title | display | `SEPARATOR` |
| 31 | job_text | "Posted Sep. 7, 2026" left on title | display | `POSTED_SUFFIX` |
| 32 | job_text | "- Austin, TX" kept when location was "Austin, TX, US" | display | location without country |
| 33 | experience | "desirable", "beneficial", "helpful" not optional | removed | `OPTIONAL` |
| 34 | experience | "you will gain 3 years of experience" a requirement | removed | `OFFERED` |
| 35 | experience | "3 years OR a Master's degree" asked years of an MS | removed | `MASTERS_INSTEAD` |
| 36 | experience | "at least 18 years old" an 18-year requirement | removed | `AGE_OR_SCHOOLING` |
| 37 | experience | "at least 3 years of college" a requirement | removed | `AGE_OR_SCHOOLING` |
| 38 | degree | "MS students ... also welcome" removed as PhD-only | removed | `_WELCOMES` |
| 39 | experience | "4 years (BS) or 2 years (MS)" lost the MS path | removed | bracket in `DEGREE_AFTER` |
| 40 | experience | "BSEE + 5 years or MSEE + 3 years" read as nothing | kept | `SHORT_FORMS` |
| 41 | experience | "36 months of experience" read as nothing | kept | `MONTHS` |
| 42 | experience | "(or 1+ with Master's)" lost the MS path | removed | `UNITLESS` |
| 43 | experience | "Exp: 3+ yrs" read as nothing | kept | "exp" |
| 44 | citizenship | "Active TS/SCI clearance required" missed | kept | clearance patterns |
| 45 | degree | "Currently a PhD student", "for PhD students" missed | kept | `STATED` |
| 46 | ranking | "Graduate RTL Engineer", "(Grad)", "Class of 2027" not early career | display | `EARLY_CAREER` |
| 47 | ranking | apprentices not early career | display | `EARLY_CAREER` |
| 48 | location | "Austin, TX & Toronto, ON" read as abroad | removed | split on & / and |
| 49 | job_text | "RTL Engineer in Austin, TX" left "RTL Engineer in" | display | "in"/"at" separator |
| 50 | job_text | "(Austin, TX)" left on title | display | bracketed location |
| 51 | job_text | "Posted on 09/07/2026" left on title | display | numeric date |
| 52 | experience | Staff title made entry level by internship boilerplate | kept | `SENIOR_TITLE` |
| 53 | experience | "Must-Haves", "Nice-to-Haves" headings unread | both | hyphen/plural |
| 54 | experience | "Pluses", "a big plus" unread | removed | `OPTIONAL` |
| 55 | experience | Qualcomm's ". OR Master's ..." split at the full stop | removed | join ". OR" |
| 56 | citizenship | "citizen of the United States" missed | kept | pattern |
| 57 | citizenship | "USA/American citizenship", "US-citizen" missed | kept | patterns |
| 58 | citizenship | "not open to non-U.S. citizens" missed | kept | patterns |
| 59 | ranking | "Posted: 3 days ago", "Reposted ...", "3 days ago" undated | display | `RELATIVE_DAY` |
| 60 | job_text | "Reposted ..."/"Posted: ..." left on title | display | `POSTED_SUFFIX` |
| 61 | experience | "5 yrs. of experience" read as nothing | kept | drop the point |
| 62 | degree | "PhD holders only", "Only PhD candidates" missed | kept | `STATED` |
| 63 | degree | "PhD (required)", "PhD - required", "PhD: required" missed | kept | `STATED` |
| 64 | degree | "Required: Ph.D." missed | kept | bare `DEGREE_LINE` |
| 65 | degree | "PhD in EE is a must" missed | kept | `STATED` |
| 66 | degree | "This role requires a PhD" missed | kept | `STATED` |
| 67 | title rules | "Head, Silicon Engineering" not excluded | kept | head pattern |
| 68 | title rules | "Technical Leader", "Team Leader" not excluded | kept | leader |
| 69 | title rules | "Supervisor, ASIC" not excluded | kept | supervisor |
| 70 | experience | "The ideal candidate has 5+ years" a requirement | removed | `OPTIONAL` |
| 71 | experience | "less than 5 years ... will not be considered" read as nothing | kept | `TURNED_AWAY` |
| 72 | experience | "5 years or less", "Maximum 5 years" read as a floor | removed | `UPPER_AFTER` |
| 73 | location | "Bay Area", "Silicon Valley", "DFW" unplaced | removed | US regions |
| 74 | location | "APAC", "EMEA" unplaced | kept | foreign regions |
| 75 | employers | "L3 Harris", "L-3" not excluded | kept | pattern |
| 76 | employers | "Science Applications International Corp" not excluded | kept | pattern |
| 77 | employers | Collins Aerospace, Pratt & Whitney (RTX) not excluded | kept | patterns |
| 78 | job_text | "Austin,TX" without a space left on title | display | flexible comma |
| 79 | job_text | "Job ID 12345", "(Req #12345)" left on title; copies grouped apart | display | `REQUISITION_SUFFIX` |
| 80 | degree | curly "Master’s degree" no alternative; posting removed | removed | apostrophe normalized |
| 81 | queue | first_seen ahead of the server clock: posting in neither tab | removed | no upper bound on the recent window |
| 82 | title rules | "Low Power Design Engineer" soft-blocked by "power" | removed | `low power` hardware term |
| 83 | title rules | "Analog Mixed Signal Verification Engineer" blocked | removed | AMS/mixed-signal verification keep |
| 84 | title rules | "Technical Recruiter - Silicon" kept by "silicon" | kept | recruiter, talent acquisition excluded |
| 85 | title rules, ranking | "SOC Analyst", "Cybersecurity SOC Engineer" kept as system-on-chip | kept | security operations excluded |
| 86 | experience | full-width "５＋ years" read as nothing | kept | NFKC |
| 87 | citizenship | "U.S.&nbsp;citizenship is required" missed | kept | unescape + NFKC |
| 88 | location | "Gdańsk", "Timișoara", "Iași" unplaced | kept | accents stripped |
| 89 | location | Pyeongtaek, Giheung, Taoyuan, Wuxi, Xiamen, Cyberjaya, Rousset unplaced | kept | cities |
| 90 | experience | "3~5 years" read as 5 | removed | `RANGE` |
| 91 | experience | "3 through 5 years" read as 5 | removed | `RANGE` |
| 92 | experience | "three-to-five years" read as 5 | removed | `RANGE` in `SPELLED` |
| 93 | experience | "2 or 3 years", "2/3 years" read as 3 | removed | `RANGE` |
| 94 | experience | "Years experience: 3+", "Experience (years): 3" read as nothing | kept | `LABELLED_SHORT` |
| 95 | citizenship | "Some/Certain/Most positions require U.S. citizenship" a hard pass | removed | `OTHER_POSITIONS` |
| 96 | citizenship | "For positions requiring ..." a hard pass; "U.S." dots cut the lead of every match | removed | `OTHER_POSITIONS`, `ABBREVIATION` mask |
| 97 | citizenship | "... is required for positions supporting government contracts" a hard pass | removed | `OTHER_SCOPE` |
| 98 | ranking | "Campus Network Engineer" early career | display | campus as the opening only |
| 99 | job_text | "- San Jose, California" kept when the location says "CA" | display | state name/code variants |
| 100 | citizenship | "... or hold a valid work visa", "or H-1B holder" a hard pass | removed | `WORK_AUTHORIZATION` |

## Not bugs, recorded so they are not re-found

- "BS with 5 years, MS with 2 years" read five years until the user decided on
  2026-09-27 that paths listed apart are alternatives (batch 3).
- Staff titles are not excluded by design (`docs/collection-rules.md`).
- "Kfar Saba, IL", "Indore, IN": an unknown city beside an ambiguous code is
  read as the state, which keeps the posting -- deliberate.
- A company's "About us" naming BS/MS/PhD graduates keeps a PhD posting --
  deliberate (`degree` docstring).
- Discovered employers are keyed by `employer_name.casefold()`, so "Acme Inc."
  and "Acme, Inc." are two keys and a paid listing's copies under both do not
  group. Changing the key would re-key stored rows; left as a known gap.
- Other defense contractors (Booz Allen, ManTech, Kratos, Mercury, SNC,
  Huntington Ingalls) are not on the user's employer list; suggested, not added.

## Related change (not counted)

Account-walled third-party sites (Dice, Wellfound, Handshake, Ladders) are
blocked and every blocked publisher is excluded from JSearch requests
(1bd0645, `tests/test_account_walled.py`, `docs/blocked-recruitment-domains.md`).
