---
name: gh-issues
description: GitHub issue lifecycle — list, view, create, comment via integration_call.
version: "1.0.0"
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
    description: Create an issue.
    args_overview: "<repo> --title T [--body B] [--label L] [--assignee U]"
  - path: scripts/issue_comment.py
    description: Comment on an issue.
    args_overview: "<repo> <issue_number> --body B"
---

# gh-issues skill

Issue lifecycle scripts over **`integration_call`** (``issues.*`` methods; list/create
use ``legacy_gh_repo_integration_kwargs`` aliases where applicable).

Set **`SEVN_WORKSPACE`**, **`SEVN_PROXY_URL`**, and **`SEVN_SESSION_TOKEN`**. GitHub auth
is **`integration.github.token`** (or **`GITHUB_TOKEN`**) on the proxy, not in the gateway.
