# Coding and lossless optimization

Follow these conventions for new and edited code; preserve surrounding style
instead of reformatting unrelated files.

- Use English, descriptive snake_case names, and small functions with one
  responsibility. Use a function instead of a stateless wrapper class.
- Document inputs, return values, side effects, and invariants at shared
  boundaries. Add type annotations where the contract is known; do not claim
  stricter types than providers actually supply.
- Keep policy in one shared entry point. Callers must not independently
  maintain the same eligibility checks or their precedence.
- Reuse parsing and matching results within an operation. Add caches only
  with explicit invalidation and bounded memory.
- Optimize measured costs. Record the baseline, output equality, and measured
  improvement. Readability is more useful than shortening variable names or
  minifying source files.

## Storage requirement

The user's current requirement is lossless storage optimization: preserve all
content and existing functionality, including company-values text and both
CSV and JSONL export interfaces. Do not achieve savings by deleting fields,
caches, databases, logs, or backup generations. Compression and deduplication
must reconstruct the original values and preserve existing consumers.

Before introducing a storage representation, test round-trip reconstruction,
legacy reads, interrupted writes, and recovery. Measure peak migration disk
space as well as final size. Never rewrite sealed event logs or change durable
decision/operational records as a routine optimization.

For bug fixes, demonstrate the failing case and its corrected result. For
behavior-preserving refactors, verify relevant existing contracts. Report the
tested base commit and working-tree changes separately from deployment.
