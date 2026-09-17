# Search configuration

## Active executable plan

`data/config/jsearch_queries.toml` defines the 52 nationwide functional queries,
page allocations, request defaults, budget, and conservative title filters.
See [JSearch daily discovery](jsearch.md) for behavior and commands.

`data/config/discovery_queries.toml` contains explicit company fallbacks and
reviewed employer aliases. These are separate from functional discovery.
`data/config/sources_search.toml` defines the transport endpoint and header name.
Credentials stay in the environment or ignored `.env.local`.

## Legacy catalog

The existing SQLite `search_queries` table and `jobdisco.query_catalog` helper
are retained for compatibility with the authored schema and old migrations.
The current collector does not execute these 18 legacy templates or multiply
functional queries by company aliases. Editing that table does not change the
daily JSearch plan. Do not maintain competing executable keyword lists.

No query configuration stores credentials, pagination progress or run results.
Per-query outcomes belong in daily manifests; job identities and source state
are reconstructed from the shared private event history.
