# Issue Tracker: GitHub

Issues and PRDs for this repo live in GitHub Issues for `TanoZhang/Operation1million`.

Use the `gh` CLI for issue operations. When run inside this clone, `gh` can infer the repository from `git remote -v`; if inference fails, pass `--repo TanoZhang/Operation1million`.

## Conventions

- Create an issue: `gh issue create --repo TanoZhang/Operation1million --title "..." --body "..."`
- Read an issue: `gh issue view <number> --repo TanoZhang/Operation1million --comments`
- List issues: `gh issue list --repo TanoZhang/Operation1million --state open`
- Comment on an issue: `gh issue comment <number> --repo TanoZhang/Operation1million --body "..."`
- Apply a label: `gh issue edit <number> --repo TanoZhang/Operation1million --add-label "..."`
- Remove a label: `gh issue edit <number> --repo TanoZhang/Operation1million --remove-label "..."`
- Close an issue: `gh issue close <number> --repo TanoZhang/Operation1million --comment "..."`

## Skill Behavior

When a skill says "publish to the issue tracker", create a GitHub issue.

When a skill says "fetch the relevant ticket", run `gh issue view <number> --repo TanoZhang/Operation1million --comments`.
