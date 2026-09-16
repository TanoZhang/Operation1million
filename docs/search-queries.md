# Search query catalog

`data/db/job_discovery.sqlite` is the single source of truth for keyword
templates. Existing company and source tables remain unchanged. The 18 original
TOML keywords were migrated without adding new job preferences.

## Columns

| Column | Purpose |
| --- | --- |
| query_key | Stable identifier, independent of keyword edits |
| keyword | Search phrase, such as RTL design engineer |
| location | Location included in query text |
| country | Lowercase two-letter API country code |
| tier | 1 for core roles, 2 for adjacent roles |
| sort_order | Stable ordering within a tier |
| enabled | 1 to use, 0 to pause without deleting |
| notes | Human explanation of intent |
| created_at, updated_at | UTC creation and edit timestamps |

The collector reads enabled rows ordered by tier, sort_order, and query_key.
It combines each template with a company alias, and forwards country separately.
Company aliases remain in `data/config/discovery_queries.toml`; keyword lists were removed
from that file to avoid two competing catalogs. Existing exclusion defaults are
not applied as API filters by this change.

## Initialization

Run `.venv/Scripts/python.exe -m jobdisco.query_catalog --migrate` for an existing
catalog. The first migration backs up the catalog under ignored `.local/backups`.
Rerunning the migration preserves edits, disabled rows, and deleted templates.
New databases built using schema.sql include the same table and seed rows.
Run the command without --migrate to list enabled templates without network use.

## Scope

These rows describe search intent, not execution state. A future collection-run
table should track company, query, provider, actual request parameters, attempt
time, result count, and completion. A single last_searched_at on a reusable
keyword would incorrectly mix multiple company searches. Pagination cursors also
belong to an individual query execution, not to a keyword template.

This change does not implement scheduling, query rotation, job persistence,
or new date-window behavior. The collector still takes the first configured
number of keywords per invocation and the first page per keyword. No API calls
are required to initialize or edit this catalog.
