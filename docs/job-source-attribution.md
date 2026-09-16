# Job Source Attribution Notes

> Historical research: the five companies below were removed from SQL/SQLite.
> The historical script is also preserved in the external `Operation1million-archive` directory.
> None of these experimental connectors is called by the active pipeline.
> The current no-CAPTCHA-bypass policy supersedes any historical runtime advice.
> See [current collector documentation](job-source-collection.md).

This file records third-party implementation references used while building
special-case company source connectors. It is intentionally separate from
the source configs so the access method and attribution stay visible.

## Scope

Only the SQL/SQLite company sources are covered here. The TOML source files
are out of scope for this pass.

## Implemented Sources

| Company | Connector in this repo | Status | Attribution |
|---|---|---|---|
| Ampere Computing | `research/recover_hard_sources.py` `ampere` | Implemented | Current site is a Talemetry/TTC career site behind Cloudflare. Access uses `curl_cffi` browser TLS impersonation and parses public search-result HTML. GitHub searches found stale Jobvite references only; no third-party code was copied. |
| ByteDance | `research/recover_hard_sources.py` `bytedance` | Implemented | Current endpoint was derived from the live `joinbytedance.com` Next.js bundle: `https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts`. Older GitHub implementation in `HA7CH/job-pro` is MIT licensed but used the retired `/api/v1/search/job/posts` endpoint, so no code was copied. Reference: https://github.com/HA7CH/job-pro |
| MediaTek | `research/recover_hard_sources.py` `mediatek` | Implemented | Current endpoint was derived from the live MediaTek Next.js bundle: `/api/trpc/job.getJobs` with SuperJSON-shaped query input. No third-party code was copied. |
| Meta | `research/recover_hard_sources.py` `meta` | Implemented | Current endpoint uses the public Meta careers GraphQL surface and `doc_id=9114524511922157`. The doc ID and request shape were cross-checked against public GitHub examples. Many examples were unlicensed, so this repo keeps only the endpoint/parameter notes, not copied code. References include `maciej-makowski/are-they-hiring` docs and `kbhujbal/go-get-jobs` code search results. |
| Tesla | `research/recover_hard_sources.py` `tesla` | Blocked without extra runtime | `kalil0321/ats-scrapers` is MIT licensed and documents the current Tesla endpoint pair: `/cua-api/apps/careers/state` and `/cua-api/careers/job/{id}`. This repo records that approach and includes a probe, but direct HTTP still hits Akamai challenge responses here. A challenge-capable browser session such as that project's `cloakbrowser` path plus suitable network configuration is required before this can run automatically. Reference: https://github.com/kalil0321/ats-scrapers |

## License Handling

The current implementation does not vendor or copy substantial third-party
source files. Where GitHub projects were used, they were used as endpoint
research and behavioral references. If a future change vendors code from an
MIT-licensed repository, copy the license notice into this file or into a
dedicated `THIRD_PARTY_NOTICES.md` section before committing.

