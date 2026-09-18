# Publication Policy

## Repository boundary

| Repository | Visibility | Purpose |
| --- | --- | --- |
| TanoZhang/Operation1million | Private | Implementation, operating configuration, history, research, and future scheduled discovery |
| TanoZhang/Operation1million-overview | Public | Reviewed explanation of the idea and proposed architecture |

The public repository starts with independent Git history. Do not change the
operating repository to public or mirror its Git refs: earlier commits contain
SQLite and CSV data. Removing files from the latest commit does not remove them
from history. Private repository access must be restricted to trusted people.

## Public content

The reviewed publication source is `docs/public-overview/`. Its current allowlist
contains only `README.md` and `.gitignore`. The public README describes the
concept, data flow, privacy boundary, and implementation status. It contains no
real job records, source catalogs, keyword lists, personal profile, or run reports.

Publish explicit files from this allowlist into an independently initialized
repository. Do not recursively copy the workspace, use a private repository as
a public template, or automatically publish generated files. Review the exact
staged files and commit history before each public push. Adding public content
beyond conceptual documentation requires a new scope decision from the user.

## Private content

- API credentials stay in ignored local credential files and Actions Secrets
  in the private operating repository. Never publish their values.
- Keep downloaded responses, job records, personal information, search/filter
  settings, SQLite files, run exports, and operational logs private. Durable
  job history uses daily `.ndjson.gz` files and manifests; SQLite is derived
  locally and must not return to Git.
- Run scheduled collection in the private repository. The public
  overview repository has Actions disabled and receives no secrets.
- Public Actions logs and artifacts are not private storage. A login requirement
  to download an artifact is not a per-user privacy boundary.
- Preserve job identity, sync progress, cooldowns, and request quota state in
  private durable storage across runs. The enabled daily workflow restores and
  checkpoints this state in the private data repository; do not replace it with
  an ephemeral runner or an evictable cache.
- Keep the public overview free of links that expose private reports or public
  download URLs for operating data. Synthetic examples must be labeled.

## Current deployment status

The implementation and existing history remain in the private repository.
`JSEARCH_API_KEY` is an Actions Secret in that repository. The public repository
is documentation only. Daily hosted discovery is enabled in the private
repository with private restore, checkpoint, and output handling.

## References

- [GitHub repository visibility](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility)
- [GitHub Actions artifacts and read access](https://docs.github.com/en/rest/actions/artifacts)
- [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## Code and data separation compatibility

The collector supports `JOBDISCO_STORE` pointing to a separate private data
checkout. A future clean code repository may contain source, tests, schemas,
configuration examples and workflow definitions, without real records. This
integration does not publish those files or change the existing repositories.
Use independent reviewed history; never expose the old operating history.
