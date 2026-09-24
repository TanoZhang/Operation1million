# Job store and incremental runs


Each pass writes into the shared `jobs` table and checkpoints `source_state`.
On a fresh machine, restore private history under `JOBDISCO_STORE` (default
`data/store`) and bootstrap the derived database:

```powershell
.\.venv\Scripts\python.exe -m jobdisco.store --bootstrap
```

`first_seen` is our own observation and exists for every board. `posted_at` only
exists where the board publishes an absolute date, which is about half of them;
Workday states only relative text such as `Posted 7 Days Ago`, kept verbatim in
`posted_relative`. The store never converts it; the review queue derives a
display date from it and the pass that read it (`ranking.relative_day`).
Anything that reports "new today" must key off `first_seen`, not `posted_at`.

`source_state` is empty before the first run, so the first pass downloads every
board in full. Later passes pick the cheapest safe strategy per source:

| Strategy | Chosen when | Effect |
| --- | --- | --- |
| `conditional` | the board returned an `ETag` | one probe; `304` ends the source |
| `since` | the board lists strictly newest-first | stop paginating past the last complete pass |
| `lastmod` | the sitemap carries `<lastmod>` | refetch only changed detail pages |
| `full` | anything else | read the whole board |

`full` is the default on purpose: a board that merely trends newest-first, or
whose dates are relative, is read completely rather than guessed at. Only a
`complete` pass advances a source's watermark. Only a complete inventory pass
may retire a posting; a since-window scan, search, capped, paused or failed pass
never closes a job it simply did not reach.

