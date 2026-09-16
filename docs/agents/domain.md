# Domain Docs

This repo uses a single-context domain documentation layout.

## Before Exploring

Engineering skills should read these files when they exist:

- `CONTEXT.md` at the repo root
- `docs/adr/` for architectural decision records that touch the area being changed

If these files do not exist, proceed silently. Do not create them just because they are absent.

## File Structure

Expected single-context layout:

```text
/
|-- CONTEXT.md
|-- docs/
|   `-- adr/
`-- src/
```

## Vocabulary

When output names a domain concept in an issue title, refactor proposal, hypothesis, or test name, use the term as defined in `CONTEXT.md`.

If the needed concept is not in the glossary yet, either reconsider whether the term belongs in this project or note the gap for a future domain-docs session.

## ADR Conflicts

If output contradicts an existing ADR, surface that conflict explicitly instead of silently overriding the decision.
