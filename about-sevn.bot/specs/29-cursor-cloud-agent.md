---
id: spec-29-cursor-cloud-agent
kind: spec
title: Cursor Cloud Agent — Spec
status: done
owner: Alex
summary: Let operators and agents launch, poll, and inspect Cursor Cloud Agents against
  any GitHub/GitLab repo when skills.cursor_cloud.enabled is true, returning PR URLs,
  dashboard links (remote desktop), and
last_updated: '2026-06-19'
fingerprint: sha256:99a185af444a73436b77fa1c7fb9312a557a45d4c300bb87ddf8d21ddb7e0f6f
related: []
sources:
- src/sevn/integrations/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-06-secrets
- spec-07-egress-proxy
- spec-12-skills-system
build_phase: null
interfaces:
- name: artifact_download_url
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: artifact_download_url
- name: create_cloud_agent
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: create_cloud_agent
- name: get_agent
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: get_agent
- name: get_run
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: get_run
- name: list_artifacts
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: list_artifacts
- name: parse_mcp_servers_json
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: parse_mcp_servers_json
- name: parse_subagents_json
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: parse_subagents_json
- name: refresh_job_status
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: refresh_job_status
- name: CursorCloudSettings
  file: src/sevn/integrations/cursor_cloud/config.py
  symbol: CursorCloudSettings
- name: load_cursor_cloud_settings
  file: src/sevn/integrations/cursor_cloud/config.py
  symbol: load_cursor_cloud_settings
- name: CursorCloudJob
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: CursorCloudJob
- name: get_job
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: get_job
- name: insert_job
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: insert_job
- name: list_workspace_jobs
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: list_workspace_jobs
- name: update_job
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: update_job
- name: github_integration_call
  file: src/sevn/integrations/github_skill/client.py
  symbol: github_integration_call
- name: github_integration_call_sync
  file: src/sevn/integrations/github_skill/client.py
  symbol: github_integration_call_sync
- name: github_legacy_call
  file: src/sevn/integrations/github_skill/client.py
  symbol: github_legacy_call
- name: parse_github_repo
  file: src/sevn/integrations/github_skill/client.py
  symbol: parse_github_repo
- name: comment_on_issue
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: comment_on_issue
- name: create_issue
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: create_issue
- name: list_issues
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: list_issues
- name: view_issue
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: view_issue
- name: close_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: close_pull_request
- name: create_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: create_pull_request
- name: list_pull_requests
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: list_pull_requests
- name: merge_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: merge_pull_request
- name: update_pull_request_reviewers
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: update_pull_request_reviewers
- name: view_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: view_pull_request
- name: create_branch
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: create_branch
- name: create_deployment
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: create_deployment
- name: delete_branch
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: delete_branch
- name: dispatch_workflow
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: dispatch_workflow
- name: list_branches
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_branches
- name: list_environments
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_environments
- name: list_repo_secrets
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_repo_secrets
- name: list_repo_variables
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_repo_variables
- name: list_workflows
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_workflows
- name: upsert_environment
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: upsert_environment
- name: upsert_repo_secret
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: upsert_repo_secret
- name: upsert_repo_variable
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: upsert_repo_variable
- name: workflow_run_logs
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: workflow_run_logs
- name: GithubSkillHooks
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: GithubSkillHooks
- name: integration_call_from_mapping
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: integration_call_from_mapping
- name: proxy_github_integration_call
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: proxy_github_integration_call
- name: resolve_github_skill_hooks
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: resolve_github_skill_hooks
- name: LitellmLapClient
  file: src/sevn/integrations/litellm_lap/client.py
  symbol: LitellmLapClient
- name: integration_post_async
  file: src/sevn/integrations/proxy_client.py
  symbol: integration_post_async
- name: integration_post_sync
  file: src/sevn/integrations/proxy_client.py
  symbol: integration_post_sync
specs: []
personas: []
---

## Purpose

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Purpose.

## Public Interface

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Public Interface.

## Data Model

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Data Model.

## Internal Architecture

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Internal Architecture.

## Behavior

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Behavior.

## Failure Modes

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Failure Modes.

## Test Strategy

Offline scaffold for Cursor Cloud Agent — Spec (spec-29-cursor-cloud-agent) — Test Strategy.
