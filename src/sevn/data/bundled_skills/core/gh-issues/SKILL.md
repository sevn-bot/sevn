---
name: gh-issues
description: >-
  GitHub issue lifecycle — templated create via authenticated gh CLI (proxy
  fallback), authenticated view/watch/track with cron notify on changes, plus
  list/comment via integration_call.
version: "1.2.0"
see_also:
  - integration_call
  - gh-pr
scripts:
  - path: scripts/issue_list.py
    description: List repository issues.
    args_overview: "<repo> [--state open|closed|all] [--label L]"
  - path: scripts/issue_view.py
    description: View one issue via gh --json (includes comment bodies).
    args_overview: "[repo] <issue_number> [--repo owner/repo]"
  - path: scripts/issue_create.py
    description: Create an issue from a template via gh CLI (proxy fallback).
    args_overview: >-
      [--repo owner/repo] --title T [--template feature|bug|chore]
      [--summary S] [--context C] [--acceptance A] [--source SRC]
      [--label L] [--assignee U]
  - path: scripts/issue_comment.py
    description: Comment on an issue.
    args_overview: "<repo> <issue_number> --body B"
  - path: scripts/issue_watch.py
    description: Diff one issue vs last-seen state under .sevn/gh-watch/.
    args_overview: "[repo] <issue_number> [--repo owner/repo]"
  - path: scripts/issue_track.py
    description: Add/remove/list tracked issues in .sevn/gh-watch/tracked.json.
    args_overview: "--add N | --remove N | --list [--repo owner/repo]"
---

# gh-issues skill

## Create (single call, preferred)

`issue_create.py` renders `templates/{feature,bug,chore}.md` (default **`feature`**)
with structured fields, then runs:

```text
gh issue create --repo <owner/repo> --title <t> --body-file <rendered.md> …
```

- **`--repo` omitted** → defaults from workspace `my_sevn.repo_url` (never `git remote`).
- **Prerequisite:** GitHub CLI (`gh`) installed and authenticated (`gh auth login`, `repo` scope).
- **Fallback:** if `gh` is absent from `PATH`, create goes through the existing
  `integration_call` / egress proxy path.
- **Errors** are precise (`gh not authenticated (run: gh auth login)`,
  `repository not found: <slug>`, `label does not exist: <l>`) — never a bare
  `proxy status 404`.
- **Success envelope data:** `{url, number, repo}`.

Placeholders in templates: `{{title}}`, `{{summary}}`, `{{context}}`,
`{{acceptance_criteria}}`, `{{source}}`, `{{labels}}`.

## View (authenticated, comment bodies)

`issue_view.py` prefers:

```text
gh issue view <n> --repo <owner/repo> --json number,title,state,url,updatedAt,labels,assignees,comments
```

Comment objects include **bodies**. Falls back to the proxy path only when `gh`
is missing from `PATH`.

## Watch / track / cron notify

1. **`issue_track.py`** — `--add N` / `--remove N` / `--list` maintains
   `.sevn/gh-watch/tracked.json`.
2. **`issue_watch.py`** — fetches live state via `gh`, diffs against
   `.sevn/gh-watch/<owner>/<repo>/<n>.json` (`state`, `updatedAt`,
   `comment_count`, `last_comment_id`, `labels`), emits **only changes**, then
   writes the new snapshot.
3. **Cron scope** — job id `gh-issue-watch` (default `*/15 * * * *`) runs
   watch over the tracked set; on any diff it calls the `message` tool to ping
   the operator (`sevn.triggers.issue_watch_cron.ISSUE_WATCH_CRON_JOB_ID` /
   `run_issue_watch_cron`, `notify_issue_watch_diff`).

## List / comment

These scripts still use **`integration_call`** (`issues.*` / legacy
`gh_repo_*` aliases). Set **`SEVN_WORKSPACE`**, **`SEVN_PROXY_URL`**, and
**`SEVN_SESSION_TOKEN`**. GitHub auth for the proxy path is
**`integration.github.token`** (or **`GITHUB_TOKEN`**) on the proxy, not in the gateway.
