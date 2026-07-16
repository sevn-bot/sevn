---
name: gh-issues
description: >-
  GitHub issue lifecycle — templated create via authenticated gh CLI (proxy
  fallback), plus list/view/comment via integration_call.
version: "1.1.0"
see_also:
  - integration_call
  - gh-pr
scripts:
  - path: scripts/issue_list.py
    description: List repository issues.
    args_overview: "<repo> [--state open|closed|all] [--label L]"
  - path: scripts/issue_view.py
    description: View one issue.
    args_overview: "<repo> <issue_number>"
  - path: scripts/issue_create.py
    description: Create an issue from a template via gh CLI (proxy fallback).
    args_overview: >-
      [--repo owner/repo] --title T [--template feature|bug|chore]
      [--summary S] [--context C] [--acceptance A] [--source SRC]
      [--label L] [--assignee U]
  - path: scripts/issue_comment.py
    description: Comment on an issue.
    args_overview: "<repo> <issue_number> --body B"
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

## List / view / comment

These scripts still use **`integration_call`** (`issues.*` / legacy
`gh_repo_*` aliases). Set **`SEVN_WORKSPACE`**, **`SEVN_PROXY_URL`**, and
**`SEVN_SESSION_TOKEN`**. GitHub auth for the proxy path is
**`integration.github.token`** (or **`GITHUB_TOKEN`**) on the proxy, not in the gateway.
