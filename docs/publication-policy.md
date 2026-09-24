# Publication policy

| Repository | Visibility | Holds |
| --- | --- | --- |
| TanoZhang/Operation1million | Public | Code, tests, configuration, docs |
| TanoZhang/Operation1million-data | Private | Event log, manifests, credit and cooldown ledgers, application decisions |

## Never in the public repo

- API keys and `.env.local`. Keys live in `/etc/jobdisco/env` on the VPS and in ignored local files.
- Job records, run exports, SQLite files, logs.
- Application decisions, answer-bank content, personal details.
- Commit identities other than `TanoZhang <tanozhang@users.noreply.github.com>` and the agents' noreply addresses.

History is public as well. Anything committed by mistake needs a history rewrite, not a follow-up delete.
