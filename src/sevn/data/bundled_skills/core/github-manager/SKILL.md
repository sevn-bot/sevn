---
name: github-manager
description: Advanced GitHub operations — branches, Actions, CI/CD secrets, environments, deployments via integration_call.
version: "1.0.0"
see_also:
  - integration_call
  - gh-pr
  - gh-issues
scripts:
  - path: scripts/branch_list.py
    description: List repository branches.
    args_overview: "<repo>"
  - path: scripts/branch_create.py
    description: Create a branch from a ref.
    args_overview: "<repo> --branch NAME --from-ref REF"
  - path: scripts/branch_delete.py
    description: Delete a branch ref.
    args_overview: "<repo> --branch NAME"
  - path: scripts/actions_list_workflows.py
    description: List GitHub Actions workflows.
    args_overview: "<repo>"
  - path: scripts/actions_run.py
    description: Trigger a workflow dispatch.
    args_overview: "<repo> --workflow-id ID --ref REF [--input KEY=VAL]"
  - path: scripts/actions_logs.py
    description: Fetch workflow run metadata and jobs.
    args_overview: "<repo> --run-id ID"
  - path: scripts/cicd_secrets.py
    description: List or upsert repository Actions secrets.
    args_overview: "<repo> --action list|upsert [--name NAME --encrypted-value VAL]"
  - path: scripts/cicd_vars.py
    description: List or upsert repository Actions variables.
    args_overview: "<repo> --action list|upsert [--name NAME --value VAL]"
  - path: scripts/cicd_environments.py
    description: List or upsert deployment environments.
    args_overview: "<repo> --action list|upsert [--name NAME [--wait-timer MIN]]"
  - path: scripts/deploy.py
    description: Trigger a deployment.
    args_overview: "<repo> --ref REF --environment NAME [--description TEXT]"
---

# github-manager skill

Advanced GitHub write/management recipes over native **`integration_call`** with
``service: github`` and REST-shaped ``method`` / ``args`` (see
``legacy_gh_repo_integration_kwargs`` for historic ``gh_repo_*`` aliases).

Use **`load_skill`** + **`run_skill_script`**. Set **`SEVN_WORKSPACE`** and ensure
**`SEVN_PROXY_URL`** + **`SEVN_SESSION_TOKEN`** are injected. Configure
**`integration.github.token`** on the egress proxy (`sevn secrets`) for authenticated calls.
