---
id: spec-29-cursor-cloud-agent
kind: spec
title: Cursor Cloud Agent — Spec
status: scaffold
owner: Alex
summary: Let operators and agents launch, poll, and inspect Cursor Cloud Agents against
  any GitHub/GitLab repo when skills.cursor_cloud.enabled is true, returning PR URLs,
  dashboard links (remote desktop), and
last_updated: '2026-07-18'
fingerprint: sha256:3fb2199482e9a93a5ed9df335adc9b12ede0bf3e14fe95171d4ac91b1a47d020
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
- name: GhCliMissingError
  file: src/sevn/integrations/github_skill/gh_cli.py
  symbol: GhCliMissingError
- name: create_issue_via_gh
  file: src/sevn/integrations/github_skill/gh_cli.py
  symbol: create_issue_via_gh
- name: map_gh_cli_error
  file: src/sevn/integrations/github_skill/gh_cli.py
  symbol: map_gh_cli_error
- name: run_gh
  file: src/sevn/integrations/github_skill/gh_cli.py
  symbol: run_gh
- name: view_issue_via_gh
  file: src/sevn/integrations/github_skill/gh_cli.py
  symbol: view_issue_via_gh
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
- name: IssueWatchDiff
  file: src/sevn/integrations/github_skill/watch.py
  symbol: IssueWatchDiff
- name: fetch_issue_state
  file: src/sevn/integrations/github_skill/watch.py
  symbol: fetch_issue_state
- name: load_tracked
  file: src/sevn/integrations/github_skill/watch.py
  symbol: load_tracked
- name: run_tracked_watch
  file: src/sevn/integrations/github_skill/watch.py
  symbol: run_tracked_watch
- name: save_tracked
  file: src/sevn/integrations/github_skill/watch.py
  symbol: save_tracked
- name: snapshot_from_issue
  file: src/sevn/integrations/github_skill/watch.py
  symbol: snapshot_from_issue
- name: tracked_path
  file: src/sevn/integrations/github_skill/watch.py
  symbol: tracked_path
- name: watch_issue
  file: src/sevn/integrations/github_skill/watch.py
  symbol: watch_issue
- name: watch_state_path
  file: src/sevn/integrations/github_skill/watch.py
  symbol: watch_state_path
- name: LitellmLapClient
  file: src/sevn/integrations/litellm_lap/client.py
  symbol: LitellmLapClient
- name: integration_post_async
  file: src/sevn/integrations/proxy_client.py
  symbol: integration_post_async
- name: integration_post_sync
  file: src/sevn/integrations/proxy_client.py
  symbol: integration_post_sync
- name: build_capabilities_matrix
  file: src/sevn/integrations/social_media/capabilities.py
  symbol: build_capabilities_matrix
- name: site_skill_hints
  file: src/sevn/integrations/social_media/capabilities.py
  symbol: site_skill_hints
- name: validate_config_cycle_mutation
  file: src/sevn/integrations/social_media/cycle_validation.py
  symbol: validate_config_cycle_mutation
- name: allowed_media_for_site
  file: src/sevn/integrations/social_media/medium.py
  symbol: allowed_media_for_site
- name: resolve_social_medium
  file: src/sevn/integrations/social_media/medium.py
  symbol: resolve_social_medium
- name: build_social_media_readiness
  file: src/sevn/integrations/social_media/readiness.py
  symbol: build_social_media_readiness
- name: build_social_media_readiness_sync
  file: src/sevn/integrations/social_media/readiness.py
  symbol: build_social_media_readiness_sync
- name: format_browser_session_hint
  file: src/sevn/integrations/social_media/readiness.py
  symbol: format_browser_session_hint
- name: platform_readiness_fields
  file: src/sevn/integrations/social_media/readiness.py
  symbol: platform_readiness_fields
- name: site_login_probe
  file: src/sevn/integrations/social_media/readiness.py
  symbol: site_login_probe
- name: twexapi_key_configured
  file: src/sevn/integrations/social_media/readiness.py
  symbol: twexapi_key_configured
- name: cookie_bridge_log_safe
  file: src/sevn/integrations/social_media/x_ops_dispatch.py
  symbol: cookie_bridge_log_safe
- name: cookies_for_twexapi
  file: src/sevn/integrations/social_media/x_ops_dispatch.py
  symbol: cookies_for_twexapi
- name: envelope
  file: src/sevn/integrations/social_media/x_ops_dispatch.py
  symbol: envelope
- name: resolve_content_root
  file: src/sevn/integrations/social_media/x_ops_dispatch.py
  symbol: resolve_content_root
- name: run_op
  file: src/sevn/integrations/social_media/x_ops_dispatch.py
  symbol: run_op
- name: smm_cfg
  file: src/sevn/integrations/social_media/x_ops_dispatch.py
  symbol: smm_cfg
- name: pack_advanced_search_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_advanced_search_body
- name: pack_auto_cookie_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_auto_cookie_body
- name: pack_create_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_create_body
- name: pack_delete_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_delete_body
- name: pack_empty_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_empty_body
- name: pack_follow_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_follow_body
- name: pack_hashtags_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_hashtags_body
- name: pack_quote_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_quote_body
- name: pack_thread_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_thread_body
- name: pack_timeline_path
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_timeline_path
- name: pack_tweet_id_path
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_tweet_id_path
- name: pack_users_body
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: pack_users_body
- name: thread_items
  file: src/sevn/integrations/social_media/x_ops_pack.py
  symbol: thread_items
- name: TwexApiClient
  file: src/sevn/integrations/twexapi/client.py
  symbol: TwexApiClient
- name: TwexApiError
  file: src/sevn/integrations/twexapi/client.py
  symbol: TwexApiError
- name: TwexApiSettings
  file: src/sevn/integrations/twexapi/config.py
  symbol: TwexApiSettings
- name: load_twexapi_settings
  file: src/sevn/integrations/twexapi/config.py
  symbol: load_twexapi_settings
- name: resolve_twexapi_api_key
  file: src/sevn/integrations/twexapi/config.py
  symbol: resolve_twexapi_api_key
- name: validate_twexapi_base_url
  file: src/sevn/integrations/twexapi/config.py
  symbol: validate_twexapi_base_url
---

## Purpose

Let operators and agents launch, poll, and inspect Cursor Cloud Agents against any GitHub/GitLab repo when skills.cursor_cloud.enabled is true, returning PR URLs, dashboard links (remote desktop), and

Primary code trees: `src/sevn/integrations/`.

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`artifact_download_url`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`create_cloud_agent`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`get_agent`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`get_run`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`list_artifacts`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`parse_mcp_servers_json`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`parse_subagents_json`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`refresh_job_status`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`CursorCloudSettings`](src/sevn/integrations/cursor_cloud/config.py) — `src/sevn/integrations/cursor_cloud/config.py`
- [`load_cursor_cloud_settings`](src/sevn/integrations/cursor_cloud/config.py) — `src/sevn/integrations/cursor_cloud/config.py`
- [`CursorCloudJob`](src/sevn/integrations/cursor_cloud/jobs.py) — `src/sevn/integrations/cursor_cloud/jobs.py`
- [`get_job`](src/sevn/integrations/cursor_cloud/jobs.py) — `src/sevn/integrations/cursor_cloud/jobs.py`
- _…and 37 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`artifact_download_url`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`create_cloud_agent`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`get_agent`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`get_run`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`list_artifacts`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`parse_mcp_servers_json`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`parse_subagents_json`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`refresh_job_status`](src/sevn/integrations/cursor_cloud/client.py) — `src/sevn/integrations/cursor_cloud/client.py`
- [`CursorCloudSettings`](src/sevn/integrations/cursor_cloud/config.py) — `src/sevn/integrations/cursor_cloud/config.py`
- [`load_cursor_cloud_settings`](src/sevn/integrations/cursor_cloud/config.py) — `src/sevn/integrations/cursor_cloud/config.py`
- [`CursorCloudJob`](src/sevn/integrations/cursor_cloud/jobs.py) — `src/sevn/integrations/cursor_cloud/jobs.py`
- [`get_job`](src/sevn/integrations/cursor_cloud/jobs.py) — `src/sevn/integrations/cursor_cloud/jobs.py`
- _…and 37 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/integrations`](src/sevn/integrations/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/integrations`](src/sevn/integrations/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
