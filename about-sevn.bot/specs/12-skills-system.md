---
id: spec-12-skills-system
kind: spec
title: Skills system — Spec
status: scaffold
owner: Alex
summary: 'Own everything under workspace/skills/: how skills are discovered, validated,
  indexed for routing (spec-10-schema-ontology TriageResult.skills holds names only
  — descriptions come from this subsystem)'
last_updated: '2026-07-16'
fingerprint: sha256:b8d7c46dc8b26cb3e43a57b11a9f8e9c441ca1df5653094460b8d7ff4dcdf5cc
related: []
sources:
- src/sevn/skills/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-04-tracing
- spec-06-secrets
- spec-07-egress-proxy
- spec-08-sandbox
- spec-09-security-scanner
- spec-10-schema-ontology
- spec-11-tools-registry
build_phase: null
interfaces:
- name: prune_orphan_browser_profiles
  file: src/sevn/skills/browser_gc.py
  symbol: prune_orphan_browser_profiles
- name: BrowserReadiness
  file: src/sevn/skills/browser_session.py
  symbol: BrowserReadiness
- name: BrowserSessionRegistry
  file: src/sevn/skills/browser_session.py
  symbol: BrowserSessionRegistry
- name: CloseBrowserResult
  file: src/sevn/skills/browser_session.py
  symbol: CloseBrowserResult
- name: TabOperationError
  file: src/sevn/skills/browser_session.py
  symbol: TabOperationError
- name: TabSessionView
  file: src/sevn/skills/browser_session.py
  symbol: TabSessionView
- name: activate_tab
  file: src/sevn/skills/browser_session.py
  symbol: activate_tab
- name: browser_autoclose_enabled
  file: src/sevn/skills/browser_session.py
  symbol: browser_autoclose_enabled
- name: browser_page
  file: src/sevn/skills/browser_session.py
  symbol: browser_page
- name: browser_readiness_snapshot
  file: src/sevn/skills/browser_session.py
  symbol: browser_readiness_snapshot
- name: cdp_list_page_targets
  file: src/sevn/skills/browser_session.py
  symbol: cdp_list_page_targets
- name: cdp_port_from_url
  file: src/sevn/skills/browser_session.py
  symbol: cdp_port_from_url
- name: cdp_port_seed
  file: src/sevn/skills/browser_session.py
  symbol: cdp_port_seed
- name: cdp_reachable
  file: src/sevn/skills/browser_session.py
  symbol: cdp_reachable
- name: clear_registry
  file: src/sevn/skills/browser_session.py
  symbol: clear_registry
- name: close_all_gateway_browsers
  file: src/sevn/skills/browser_session.py
  symbol: close_all_gateway_browsers
- name: close_browser_session
  file: src/sevn/skills/browser_session.py
  symbol: close_browser_session
- name: close_idle_browser_sessions
  file: src/sevn/skills/browser_session.py
  symbol: close_idle_browser_sessions
- name: close_tab
  file: src/sevn/skills/browser_session.py
  symbol: close_tab
- name: connected_tab_session
  file: src/sevn/skills/browser_session.py
  symbol: connected_tab_session
- name: default_cdp_url
  file: src/sevn/skills/browser_session.py
  symbol: default_cdp_url
- name: is_brave_executable
  file: src/sevn/skills/browser_session.py
  symbol: is_brave_executable
- name: list_tabs
  file: src/sevn/skills/browser_session.py
  symbol: list_tabs
- name: merge_browser_proc_env
  file: src/sevn/skills/browser_session.py
  symbol: merge_browser_proc_env
- name: open_tab
  file: src/sevn/skills/browser_session.py
  symbol: open_tab
- name: page_target_id
  file: src/sevn/skills/browser_session.py
  symbol: page_target_id
- name: persist_active_target_id
  file: src/sevn/skills/browser_session.py
  symbol: persist_active_target_id
- name: pick_work_page
  file: src/sevn/skills/browser_session.py
  symbol: pick_work_page
- name: read_devtools_active_port
  file: src/sevn/skills/browser_session.py
  symbol: read_devtools_active_port
- name: read_registry
  file: src/sevn/skills/browser_session.py
  symbol: read_registry
- name: registry_path
  file: src/sevn/skills/browser_session.py
  symbol: registry_path
- name: resolve_browser_engine
  file: src/sevn/skills/browser_session.py
  symbol: resolve_browser_engine
- name: resolve_browser_extra_args
  file: src/sevn/skills/browser_session.py
  symbol: resolve_browser_extra_args
- name: resolve_browser_headless
  file: src/sevn/skills/browser_session.py
  symbol: resolve_browser_headless
- name: resolve_cdp_url
  file: src/sevn/skills/browser_session.py
  symbol: resolve_cdp_url
- name: resolve_chrome_executable
  file: src/sevn/skills/browser_session.py
  symbol: resolve_chrome_executable
- name: resolve_idle_close_seconds
  file: src/sevn/skills/browser_session.py
  symbol: resolve_idle_close_seconds
- name: resolve_profile_dir
  file: src/sevn/skills/browser_session.py
  symbol: resolve_profile_dir
- name: resolve_target_page
  file: src/sevn/skills/browser_session.py
  symbol: resolve_target_page
- name: restart_browser_session
  file: src/sevn/skills/browser_session.py
  symbol: restart_browser_session
- name: session_status_payload
  file: src/sevn/skills/browser_session.py
  symbol: session_status_payload
- name: spawn_chrome
  file: src/sevn/skills/browser_session.py
  symbol: spawn_chrome
- name: try_persist_active_page
  file: src/sevn/skills/browser_session.py
  symbol: try_persist_active_page
- name: wait_for_page_ready
  file: src/sevn/skills/browser_session.py
  symbol: wait_for_page_ready
- name: write_registry
  file: src/sevn/skills/browser_session.py
  symbol: write_registry
- name: build_skill_capability_rows
  file: src/sevn/skills/capabilities.py
  symbol: build_skill_capability_rows
- name: computer_use_config_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_config_enabled
- name: computer_use_mcp_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_mcp_enabled
- name: computer_use_snapshot_annotate_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_snapshot_annotate_enabled
- name: computer_use_trajectory_export_dir
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_trajectory_export_dir
- name: computer_use_trajectory_share_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_trajectory_share_enabled
- name: computer_use_uses_cua_driver_mcp
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_uses_cua_driver_mcp
- name: gate_computer_use_core_skill
  file: src/sevn/skills/computer_use.py
  symbol: gate_computer_use_core_skill
- name: mcp_stdio_entry
  file: src/sevn/skills/computer_use.py
  symbol: mcp_stdio_entry
- name: merge_computer_use_mcp_server
  file: src/sevn/skills/computer_use.py
  symbol: merge_computer_use_mcp_server
- name: resolve_computer_use_target
  file: src/sevn/skills/computer_use.py
  symbol: resolve_computer_use_target
- name: resolve_cua_cli_command
  file: src/sevn/skills/computer_use.py
  symbol: resolve_cua_cli_command
- name: resolve_cua_do_switch_provider
  file: src/sevn/skills/computer_use.py
  symbol: resolve_cua_do_switch_provider
- name: resolve_cua_driver_command
  file: src/sevn/skills/computer_use.py
  symbol: resolve_cua_driver_command
- name: validate_computer_use_host
  file: src/sevn/skills/computer_use.py
  symbol: validate_computer_use_host
- name: cua_agent_approval_mode
  file: src/sevn/skills/cua_agent.py
  symbol: cua_agent_approval_mode
- name: cua_agent_config_enabled
  file: src/sevn/skills/cua_agent.py
  symbol: cua_agent_config_enabled
- name: cua_agent_require_computer_use
  file: src/sevn/skills/cua_agent.py
  symbol: cua_agent_require_computer_use
- name: gate_cua_agent_core_skill
  file: src/sevn/skills/cua_agent.py
  symbol: gate_cua_agent_core_skill
- name: validate_cua_agent_host
  file: src/sevn/skills/cua_agent.py
  symbol: validate_cua_agent_host
- name: validate_cua_agent_run
  file: src/sevn/skills/cua_agent.py
  symbol: validate_cua_agent_run
- name: CuaDoctorRow
  file: src/sevn/skills/cua_doctor_check.py
  symbol: CuaDoctorRow
- name: probe_cua_skill_checks
  file: src/sevn/skills/cua_doctor_check.py
  symbol: probe_cua_skill_checks
- name: cursor_cloud_config_enabled
  file: src/sevn/skills/cursor_cloud.py
  symbol: cursor_cloud_config_enabled
- name: gate_cursor_cloud_core_skill
  file: src/sevn/skills/cursor_cloud.py
  symbol: gate_cursor_cloud_core_skill
- name: EmailAccount
  file: src/sevn/skills/email_management.py
  symbol: EmailAccount
- name: ImapClientProtocol
  file: src/sevn/skills/email_management.py
  symbol: ImapClientProtocol
- name: MessageSummary
  file: src/sevn/skills/email_management.py
  symbol: MessageSummary
- name: StdlibImapClient
  file: src/sevn/skills/email_management.py
  symbol: StdlibImapClient
- name: account_public_dict
  file: src/sevn/skills/email_management.py
  symbol: account_public_dict
- name: create_imap_client
  file: src/sevn/skills/email_management.py
  symbol: create_imap_client
- name: dry_run_requested
  file: src/sevn/skills/email_management.py
  symbol: dry_run_requested
- name: fetch_recent_messages
  file: src/sevn/skills/email_management.py
  symbol: fetch_recent_messages
- name: gmail_api_plan
  file: src/sevn/skills/email_management.py
  symbol: gmail_api_plan
- name: list_imap_folders
  file: src/sevn/skills/email_management.py
  symbol: list_imap_folders
- name: load_accounts
  file: src/sevn/skills/email_management.py
  symbol: load_accounts
- name: resolve_account
  file: src/sevn/skills/email_management.py
  symbol: resolve_account
- name: resolve_password
  file: src/sevn/skills/email_management.py
  symbol: resolve_password
- name: search_imap_messages
  file: src/sevn/skills/email_management.py
  symbol: search_imap_messages
- name: send_smtp_message
  file: src/sevn/skills/email_management.py
  symbol: send_smtp_message
- name: summaries_to_dicts
  file: src/sevn/skills/email_management.py
  symbol: summaries_to_dicts
- name: reserved_skills_plugin_row
  file: src/sevn/skills/entrypoints.py
  symbol: reserved_skills_plugin_row
- name: SkillExecutionError
  file: src/sevn/skills/errors.py
  symbol: SkillExecutionError
- name: failure_envelope
  file: src/sevn/skills/errors.py
  symbol: failure_envelope
- name: success_envelope
  file: src/sevn/skills/errors.py
  symbol: success_envelope
- name: GoogleWorkspacePaths
  file: src/sevn/skills/google_workspace.py
  symbol: GoogleWorkspacePaths
- name: build_service
  file: src/sevn/skills/google_workspace.py
  symbol: build_service
- name: check_auth
  file: src/sevn/skills/google_workspace.py
  symbol: check_auth
- name: check_auth_live
  file: src/sevn/skills/google_workspace.py
  symbol: check_auth_live
- name: client_secret_path
  file: src/sevn/skills/google_workspace.py
  symbol: client_secret_path
- name: dry_run_requested
  file: src/sevn/skills/google_workspace.py
  symbol: dry_run_requested
- name: ensure_google_deps
  file: src/sevn/skills/google_workspace.py
  symbol: ensure_google_deps
- name: exchange_auth_code
  file: src/sevn/skills/google_workspace.py
  symbol: exchange_auth_code
- name: get_auth_url
  file: src/sevn/skills/google_workspace.py
  symbol: get_auth_url
- name: get_credentials
  file: src/sevn/skills/google_workspace.py
  symbol: get_credentials
- name: get_valid_token_for_gws
  file: src/sevn/skills/google_workspace.py
  symbol: get_valid_token_for_gws
- name: gws_binary
  file: src/sevn/skills/google_workspace.py
  symbol: gws_binary
- name: install_deps
  file: src/sevn/skills/google_workspace.py
  symbol: install_deps
- name: load_token_payload
  file: src/sevn/skills/google_workspace.py
  symbol: load_token_payload
- name: missing_scopes_from_payload
  file: src/sevn/skills/google_workspace.py
  symbol: missing_scopes_from_payload
- name: normalize_authorized_user_payload
  file: src/sevn/skills/google_workspace.py
  symbol: normalize_authorized_user_payload
- name: paths
  file: src/sevn/skills/google_workspace.py
  symbol: paths
- name: pending_auth_path
  file: src/sevn/skills/google_workspace.py
  symbol: pending_auth_path
- name: prefer_gws_enabled
  file: src/sevn/skills/google_workspace.py
  symbol: prefer_gws_enabled
- name: revoke_token
  file: src/sevn/skills/google_workspace.py
  symbol: revoke_token
- name: run_gws
  file: src/sevn/skills/google_workspace.py
  symbol: run_gws
- name: store_client_secret
  file: src/sevn/skills/google_workspace.py
  symbol: store_client_secret
- name: token_path
  file: src/sevn/skills/google_workspace.py
  symbol: token_path
- name: calendar_create
  file: src/sevn/skills/google_workspace_api.py
  symbol: calendar_create
- name: calendar_delete
  file: src/sevn/skills/google_workspace_api.py
  symbol: calendar_delete
- name: calendar_list
  file: src/sevn/skills/google_workspace_api.py
  symbol: calendar_list
- name: contacts_list
  file: src/sevn/skills/google_workspace_api.py
  symbol: contacts_list
- name: docs_append
  file: src/sevn/skills/google_workspace_api.py
  symbol: docs_append
- name: docs_create
  file: src/sevn/skills/google_workspace_api.py
  symbol: docs_create
- name: docs_get
  file: src/sevn/skills/google_workspace_api.py
  symbol: docs_get
- name: drive_create_folder
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_create_folder
- name: drive_delete
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_delete
- name: drive_download
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_download
- name: drive_get
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_get
- name: drive_search
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_search
- name: drive_share
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_share
- name: drive_upload
  file: src/sevn/skills/google_workspace_api.py
  symbol: drive_upload
- name: gmail_get
  file: src/sevn/skills/google_workspace_api.py
  symbol: gmail_get
- name: gmail_labels
  file: src/sevn/skills/google_workspace_api.py
  symbol: gmail_labels
- name: gmail_modify
  file: src/sevn/skills/google_workspace_api.py
  symbol: gmail_modify
- name: gmail_reply
  file: src/sevn/skills/google_workspace_api.py
  symbol: gmail_reply
- name: gmail_search
  file: src/sevn/skills/google_workspace_api.py
  symbol: gmail_search
- name: gmail_send
  file: src/sevn/skills/google_workspace_api.py
  symbol: gmail_send
- name: sheets_append
  file: src/sevn/skills/google_workspace_api.py
  symbol: sheets_append
- name: sheets_create
  file: src/sevn/skills/google_workspace_api.py
  symbol: sheets_create
- name: sheets_get
  file: src/sevn/skills/google_workspace_api.py
  symbol: sheets_get
- name: sheets_update
  file: src/sevn/skills/google_workspace_api.py
  symbol: sheets_update
- name: probe_google_workspace_skill_warnings
  file: src/sevn/skills/google_workspace_doctor_check.py
  symbol: probe_google_workspace_skill_warnings
- name: SkillsIndex
  file: src/sevn/skills/index.py
  symbol: SkillsIndex
- name: SkillsIndexBuilder
  file: src/sevn/skills/index.py
  symbol: SkillsIndexBuilder
- name: augment_index_with_aliases
  file: src/sevn/skills/index.py
  symbol: augment_index_with_aliases
- name: resolve_skill_alias
  file: src/sevn/skills/index.py
  symbol: resolve_skill_alias
- name: gate_lume_core_skill
  file: src/sevn/skills/lume.py
  symbol: gate_lume_core_skill
- name: lume_config_enabled
  file: src/sevn/skills/lume.py
  symbol: lume_config_enabled
- name: resolve_lume_command
  file: src/sevn/skills/lume.py
  symbol: resolve_lume_command
- name: validate_lume_host
  file: src/sevn/skills/lume.py
  symbol: validate_lume_host
- name: SkillsManager
  file: src/sevn/skills/manager.py
  symbol: SkillsManager
- name: did_you_mean_skill_script
  file: src/sevn/skills/manager.py
  symbol: did_you_mean_skill_script
- name: RunnableEntry
  file: src/sevn/skills/manifest.py
  symbol: RunnableEntry
- name: SkillManifest
  file: src/sevn/skills/manifest.py
  symbol: SkillManifest
- name: SkillScriptEntry
  file: src/sevn/skills/manifest.py
  symbol: SkillScriptEntry
- name: downgrade_manifest
  file: src/sevn/skills/manifest.py
  symbol: downgrade_manifest
- name: infer_abortable_for_script
  file: src/sevn/skills/manifest.py
  symbol: infer_abortable_for_script
- name: manifest_from_mapping
  file: src/sevn/skills/manifest.py
  symbol: manifest_from_mapping
- name: parse_skill_markdown
  file: src/sevn/skills/manifest.py
  symbol: parse_skill_markdown
- name: required_positional_arg_count
  file: src/sevn/skills/manifest.py
  symbol: required_positional_arg_count
- name: split_frontmatter
  file: src/sevn/skills/manifest.py
  symbol: split_frontmatter
- name: validate_script_argv
  file: src/sevn/skills/manifest.py
  symbol: validate_script_argv
- name: validate_script_paths
  file: src/sevn/skills/manifest.py
  symbol: validate_script_paths
- name: SkillRecord
  file: src/sevn/skills/models.py
  symbol: SkillRecord
- name: gate_openwiki_core_skill
  file: src/sevn/skills/openwiki.py
  symbol: gate_openwiki_core_skill
- name: openwiki_config_enabled
  file: src/sevn/skills/openwiki.py
  symbol: openwiki_config_enabled
- name: OpenwikiDoctorRow
  file: src/sevn/skills/openwiki_doctor_check.py
  symbol: OpenwikiDoctorRow
- name: probe_openwiki_skill_checks
  file: src/sevn/skills/openwiki_doctor_check.py
  symbol: probe_openwiki_skill_checks
- name: probe_openwiki_skill_checks_async
  file: src/sevn/skills/openwiki_doctor_check.py
  symbol: probe_openwiki_skill_checks_async
- name: check_node_for_openwiki
  file: src/sevn/skills/openwiki_install.py
  symbol: check_node_for_openwiki
- name: openwiki_cli_installed
  file: src/sevn/skills/openwiki_install.py
  symbol: openwiki_cli_installed
- name: run_openwiki_install
  file: src/sevn/skills/openwiki_install.py
  symbol: run_openwiki_install
- name: merge_openwiki_proc_env
  file: src/sevn/skills/openwiki_secrets.py
  symbol: merge_openwiki_proc_env
- name: openwiki_credentials_hint
  file: src/sevn/skills/openwiki_secrets.py
  symbol: openwiki_credentials_hint
- name: openwiki_credentials_resolved
  file: src/sevn/skills/openwiki_secrets.py
  symbol: openwiki_credentials_resolved
- name: BaselineSuppression
  file: src/sevn/skills/security_scan.py
  symbol: BaselineSuppression
- name: ScanIssue
  file: src/sevn/skills/security_scan.py
  symbol: ScanIssue
- name: ScanResult
  file: src/sevn/skills/security_scan.py
  symbol: ScanResult
- name: apply_baseline
  file: src/sevn/skills/security_scan.py
  symbol: apply_baseline
- name: emit_security_scan_trace
  file: src/sevn/skills/security_scan.py
  symbol: emit_security_scan_trace
- name: filter_by_severities
  file: src/sevn/skills/security_scan.py
  symbol: filter_by_severities
- name: load_baseline
  file: src/sevn/skills/security_scan.py
  symbol: load_baseline
- name: normalize_skill_path
  file: src/sevn/skills/security_scan.py
  symbol: normalize_skill_path
- name: parse_skillspector_report
  file: src/sevn/skills/security_scan.py
  symbol: parse_skillspector_report
- name: read_workspace_scan_summary
  file: src/sevn/skills/security_scan.py
  symbol: read_workspace_scan_summary
- name: resolve_skillspector_command
  file: src/sevn/skills/security_scan.py
  symbol: resolve_skillspector_command
- name: run_skillspector_subprocess
  file: src/sevn/skills/security_scan.py
  symbol: run_skillspector_subprocess
- name: scan_skill_path
  file: src/sevn/skills/security_scan.py
  symbol: scan_skill_path
- name: workspace_scan_summary_path
  file: src/sevn/skills/security_scan.py
  symbol: workspace_scan_summary_path
- name: write_workspace_scan_summary
  file: src/sevn/skills/security_scan.py
  symbol: write_workspace_scan_summary
- name: cdp_reachable
  file: src/sevn/skills/social_browser.py
  symbol: cdp_reachable
- name: default_cdp_url
  file: src/sevn/skills/social_browser.py
  symbol: default_cdp_url
- name: dry_run_requested
  file: src/sevn/skills/social_browser.py
  symbol: dry_run_requested
- name: facebook_search_url
  file: src/sevn/skills/social_browser.py
  symbol: facebook_search_url
- name: fetch_page_snapshot
  file: src/sevn/skills/social_browser.py
  symbol: fetch_page_snapshot
- name: host_allowed
  file: src/sevn/skills/social_browser.py
  symbol: host_allowed
- name: logged_in_browser_page
  file: src/sevn/skills/social_browser.py
  symbol: logged_in_browser_page
- name: merge_social_browser_proc_env
  file: src/sevn/skills/social_browser.py
  symbol: merge_social_browser_proc_env
- name: resolve_browser_profile
  file: src/sevn/skills/social_browser.py
  symbol: resolve_browser_profile
- name: session_status_payload
  file: src/sevn/skills/social_browser.py
  symbol: session_status_payload
- name: validate_social_url
  file: src/sevn/skills/social_browser.py
  symbol: validate_social_url
- name: x_search_url
  file: src/sevn/skills/social_browser.py
  symbol: x_search_url
- name: gate_social_media_manager_core_skill
  file: src/sevn/skills/social_media_manager.py
  symbol: gate_social_media_manager_core_skill
- name: social_media_manager_config_enabled
  file: src/sevn/skills/social_media_manager.py
  symbol: social_media_manager_config_enabled
---

## Purpose

Own everything under workspace/skills/: how skills are discovered, validated, indexed for routing (spec-10-schema-ontology TriageResult.skills holds names only — descriptions come from this subsystem)

Primary code trees: [`src/sevn/skills`](src/sevn/skills/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`prune_orphan_browser_profiles`](src/sevn/skills/browser_gc.py) — `src/sevn/skills/browser_gc.py`
- [`BrowserReadiness`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`BrowserSessionRegistry`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`CloseBrowserResult`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`TabOperationError`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`TabSessionView`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`activate_tab`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_autoclose_enabled`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_page`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_readiness_snapshot`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_list_page_targets`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_port_from_url`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- _…and 138 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`prune_orphan_browser_profiles`](src/sevn/skills/browser_gc.py) — `src/sevn/skills/browser_gc.py`
- [`BrowserReadiness`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`BrowserSessionRegistry`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`CloseBrowserResult`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`TabOperationError`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`TabSessionView`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`activate_tab`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_autoclose_enabled`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_page`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_readiness_snapshot`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_list_page_targets`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_port_from_url`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- _…and 138 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/skills`](src/sevn/skills/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/skills`](src/sevn/skills/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Amendments (spec-36-sub-agents)

Bundled `media_generation` skill binds to the `media_generator` specialist via
`spawn_subagent(..., wait=true)` (`src/sevn/data/bundled_skills/core/media_generation/`).
Skills may declare `requires_specialist` in SKILL front matter; triager/tier B route
media asks through the specialist grant path (D8/D16).

## Implemented by

- [`prune_orphan_browser_profiles`](src/sevn/skills/browser_gc.py) — `src/sevn/skills/browser_gc.py`
- [`BrowserReadiness`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`BrowserSessionRegistry`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`CloseBrowserResult`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`TabOperationError`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`TabSessionView`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`activate_tab`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_autoclose_enabled`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_page`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`browser_readiness_snapshot`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_list_page_targets`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_port_from_url`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_port_seed`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`cdp_reachable`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`clear_registry`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`close_all_gateway_browsers`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`close_browser_session`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`close_idle_browser_sessions`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`close_tab`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- [`connected_tab_session`](src/sevn/skills/browser_session.py) — `src/sevn/skills/browser_session.py`
- _…and 130 more in frontmatter `interfaces:`._

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
