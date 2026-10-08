# Title and Review cache optimization

Baseline fc6e628, preserving the concurrent Gmail fix. This follows the four
remaining opportunities in the [previous audit](performance-audit-2026-10-07.md).

## Changes and evidence

- Location patterns used by title cleanup are immutable and cached for at most
  2,048 normalized locations. Matching order and title cleanup rules are the
  same. Three different titles in one city previously repeated candidate
  construction three times; the regression now observes one call.
- Query plans are validated once per unchanged file and retained for at most
  four resolved paths. Callers receive deep copies of mutable configuration
  and a new query list. Modification, deletion, atomic replacement at equal
  size/mtime, and a change while parsing are covered. Invalid configuration
  raises instead of reusing an earlier valid plan.
- Review attaches links and outcomes once per unchanged queue and side-ledger
  identity. Every in-memory mutation invalidates attachment and response state.
- Each Review server retains one serialized queue response. The server's write
  and build locks protect mutation/serialization; sending bytes happens after
  releasing the locks. Tokens are server-local and are never persisted in the
  queue snapshot. Warm-up, decisions, outcomes, links, manual import, reopen,
  database/configuration/profile changes still flow through queue validation.

The original hot-HTTP regression observed five attachment passes and five slim
projections for five identical requests. It now observes one of each and a
fresh response after an external link update. An end-to-end HTTP regression
exercises apply, outcome, reopen, skip and manual import after warming the cache.

That regression additionally changes the resume profile while saving a manual
import. The pre-existing shortcut compared database/filter inputs but omitted
the resume-profile input, retaining an automatic listing rejected by the new
profile. Its comparison now includes the profile and any later queue inputs;
the fresh queue retains only the explicit manual import in that case. The
failure was reproduced before this repair; 23 related checks pass afterward.

## Measurements

Same private snapshot, local loopback HTTP, initial request plus 20 warm reads:

| Measurement | Baseline | Optimized |
| --- | ---: | ---: |
| Warm HTTP median | 133.814 ms | 7.020 ms |
| TOML parses | 42 | 1 |
| Slim projections | 21 | 1 |
| Attachment passes | 21 | 1 |
| Cleanup of 52,392 open inventory titles | 34.275 s | 16.495 s |

The parsed responses (excluding server token) and every cleaned title are
identical. The location cache remained bounded at 2,048 entries: 47,321 hits,
5,071 misses in the title replay.

The complete frozen queue also compares exactly equal: 7,210 groups, including
nested listing and decision fields. Its profiled build took 192.079 seconds;
the previous same-input build took 220.077 seconds. These local replay timings
overlapped other offline checks and include profiling overhead where noted;
they are not a production latency guarantee.

Private input, output and logs remain ignored under `.local/performance-next/`.
No application decisions or paid collection were triggered.

## Validation and deployment

Commit c36497e passed the full suite in a clean detached worktree: 1,233 tests,
1,219 passed and 14 skipped. The additional manual/profile invalidation fix
in 31a723f passed 89 related tests. The installer selected 5959b38, which also
contains Claude's subsequent Gmail condition fix; 136 related Review/Gmail
tests pass on that exact commit. The first Windows run selected the WSL bash
stub and failed the environment-file shell test; selecting installed Git Bash
resolved that runner issue without a source change.

Production returned HTTP 200 after warming. Twenty localhost warm requests
had a median of 177.776 ms before and 9.447 ms after (18.8x faster); the after
maximum was 12.445 ms. This measures server HTTP response, not browser/network
latency. Pending, backlog and skipped responses are identical. Applied differs
only in outcome/outcome_at/outcome_by for five existing groups, reflecting
concurrent durable outcome updates. Excluding those fields and the server
token, the entire response is identical. All four sections contain 250 company
identities with zero split display labels. No export refresh is needed for
these cache changes. Production evidence is ignored beside the offline logs.
