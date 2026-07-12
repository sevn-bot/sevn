---
name: gh-pr
description: Pull request lifecycle — list, view, create, merge, close, reviewers via integration_call.
version: "1.0.0"
see_also:
  - integration_call
  - github-manager
scripts:
  - path: scripts/pr_list.py
    description: List pull requests.
    args_overview: "<repo> [--state open|closed|all]"
  - path: scripts/pr_view.py
    description: View one pull request.
    args_overview: "<repo> <pr_number>"
  - path: scripts/pr_create.py
    description: Create a pull request.
    args_overview: "<repo> --title T --body B --head BR [--base main] [--draft]"
  - path: scripts/pr_merge.py
    description: Merge a pull request.
    args_overview: "<repo> <pr_number> [--method squash|merge|rebase]"
  - path: scripts/pr_close.py
    description: Close a pull request.
    args_overview: "<repo> <pr_number>"
  - path: scripts/pr_reviewers.py
    description: Add or remove PR reviewers.
    args_overview: "<repo> <pr_number> [--add USER] [--remove USER]"
---

# gh-pr skill

Pull request lifecycle scripts delegating to **`integration_call`** GitHub REST methods
(``pulls.*``). Compose with **`sandbox_exec`** for local git push steps before
**``pr_create.py``** when the head branch is not yet on the remote.

Set **`SEVN_WORKSPACE`**, **`SEVN_PROXY_URL`**, and **`SEVN_SESSION_TOKEN`**. Store
**`integration.github.token`** (or **`GITHUB_TOKEN`**) on the egress proxy via
`sevn secrets` — the gateway never holds the PAT.
