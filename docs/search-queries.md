# Search configuration

## Active executable plan

`data/config/jsearch_queries.toml` defines the 35 nationwide functional queries,
page allocations, request defaults, budget, and conservative title filters.
See [JSearch daily discovery](jsearch.md) for behavior and commands.

`data/config/sources_search.toml` defines the transport endpoint and header name.
Credentials stay in the environment or ignored `.env.local`.

## No other keyword list

The legacy SQLite `search_queries` catalog (18 templates, `job-queries`,
migration 001) was removed on 2026-10-16; nothing executed it. A fresh
`job-store --bootstrap` no longer creates the table, and an existing index
keeps an unread copy. Do not maintain competing executable keyword lists.

No query configuration stores credentials, pagination progress or run results.
Per-query outcomes belong in daily manifests; job identities and source state
are reconstructed from the shared private event history.
