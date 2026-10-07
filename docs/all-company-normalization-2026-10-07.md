# All-company normalization follow-up

The previous alias list covered only part of the company catalog. On base
7ec7bee, the new regression suite reproduces split identities for Renesas,
NXP, Quadric, Astera Labs, onsemi, Intel legal entities and HPE. Twenty-four
catalog labels lacked an explicit canonical display. Unknown-company case
variants also lacked a shared queue-wide display choice.

The repair registers every catalog employer and confirmed observed aliases:
60 canonical brands and 102 normalized alias keys. Queue labeling chooses one
deterministic display per identity across pending, backlog, applied and skipped,
including employers outside the catalog. Manual intake and CSV/XLSX use that
same boundary. Alias collisions now fail validation instead of silently
assigning an alias to the last brand. Tests protect distinct businesses from
substring merges and preserve punctuation in unknown names.

The fresh read-only production inventory contains 448 name/key rows, 443 unique
raw labels and 395 identities under these rules. This is an inventory audit,
not a claim that every uncertain legal entity has been identified. Ambiguous
names remain separate until evidence supports an alias. Raw provider records,
requisition keys and durable decisions are unchanged.

## Further optimization opportunities

These are proposals, not implemented speedups. The earlier five measured
opportunities remain in the [original audit](company-identity-audit-2026-10-07.md).

- Cache parsed links and outcomes using their file fingerprints. An offline
  harness issuing ten unchanged `current_queue()` requests observed ten reads
  of each ledger even with the queue cache warm. Validate invalidation on
  append, replacement and concurrent edits before introducing this cache.
- Expose canonical employer identity separately from the display label in
  downstream analytics. Presentation changes should not force consumers to
  rebuild company groupings; immutable source/requisition keys must remain.
- Produce an alias audit after collection, using official employer domains
  as evidence for review. This would reveal new legal-entity labels instead
  of relying on users to notice them. Do not auto-merge similar spellings or
  job-board domains. Catalog coverage and conflicting-alias tests are already
  implemented in this patch.

Private measurements and inventories remain ignored under
`.local/all-companies/`. No paid collection was invoked.
