---
id: spec-22-onboarding
kind: spec
title: Onboarding — Spec
status: draft
owner: Alex
summary: 'Deliver the merge + validation + promotion pipeline every setup path shares
  so sevn.json stays the single source of truth (prd-06-setup-and-operations §5.4,
  spec-02-config-and-workspace): shipped pres'
last_updated: '2026-07-14'
fingerprint: sha256:8c1707baf254d04a7d4b4bc933c1fc054358a5b2185b1bddf6ae400bf01c24d3
related: []
sources:
- src/sevn/onboarding/**
parent_prd: prd-06-setup-and-operations
depends_on:
- spec-02-config-and-workspace
- spec-17-gateway
build_phase: null
interfaces:
- name: BrowserSession
  file: src/sevn/onboarding/browser_automation.py
  symbol: BrowserSession
- name: BrowserStartRequest
  file: src/sevn/onboarding/browser_automation.py
  symbol: BrowserStartRequest
- name: get_browser_session
  file: src/sevn/onboarding/browser_automation.py
  symbol: get_browser_session
- name: register_shutdown_hooks
  file: src/sevn/onboarding/browser_automation.py
  symbol: register_shutdown_hooks
- name: reset_browser_session_for_tests
  file: src/sevn/onboarding/browser_automation.py
  symbol: reset_browser_session_for_tests
- name: resolve_start_request
  file: src/sevn/onboarding/browser_automation.py
  symbol: resolve_start_request
- name: stop_browser_on_shutdown
  file: src/sevn/onboarding/browser_automation.py
  symbol: stop_browser_on_shutdown
- name: CapabilityEntry
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: CapabilityEntry
- name: CapabilityGroup
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: CapabilityGroup
- name: CapabilityManifest
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: CapabilityManifest
- name: GroupWithCapabilities
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: GroupWithCapabilities
- name: InstallAction
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: InstallAction
- name: index_skill_capability_ids
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: index_skill_capability_ids
- name: list_groups
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: list_groups
- name: load_manifest
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: load_manifest
- name: manifest_resource_path
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: manifest_resource_path
- name: merged_capability_defaults
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: merged_capability_defaults
- name: resolve_install_plan
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: resolve_install_plan
- name: skill_capability_id
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: skill_capability_id
- name: CDPOnboardingBrowser
  file: src/sevn/onboarding/cdp_browser.py
  symbol: CDPOnboardingBrowser
- name: apply_web_ui_url_for_dashboard
  file: src/sevn/onboarding/dashboard_url.py
  symbol: apply_web_ui_url_for_dashboard
- name: mission_control_entry_url
  file: src/sevn/onboarding/dashboard_url.py
  symbol: mission_control_entry_url
- name: DraftLock
  file: src/sevn/onboarding/draft_store.py
  symbol: DraftLock
- name: discard_draft
  file: src/sevn/onboarding/draft_store.py
  symbol: discard_draft
- name: draft_path
  file: src/sevn/onboarding/draft_store.py
  symbol: draft_path
- name: lock_path
  file: src/sevn/onboarding/draft_store.py
  symbol: lock_path
- name: read_draft
  file: src/sevn/onboarding/draft_store.py
  symbol: read_draft
- name: write_draft
  file: src/sevn/onboarding/draft_store.py
  symbol: write_draft
- name: OnboardingDraftLockError
  file: src/sevn/onboarding/errors.py
  symbol: OnboardingDraftLockError
- name: ExportBundle
  file: src/sevn/onboarding/export_bundle.py
  symbol: ExportBundle
- name: ExportBundleError
  file: src/sevn/onboarding/export_bundle.py
  symbol: ExportBundleError
- name: ExportResult
  file: src/sevn/onboarding/export_bundle.py
  symbol: ExportResult
- name: build_export_text
  file: src/sevn/onboarding/export_bundle.py
  symbol: build_export_text
- name: bundle_seed_secrets
  file: src/sevn/onboarding/export_bundle.py
  symbol: bundle_seed_secrets
- name: parse_export_text
  file: src/sevn/onboarding/export_bundle.py
  symbol: parse_export_text
- name: provider_bindings_from_config_doc
  file: src/sevn/onboarding/export_bundle.py
  symbol: provider_bindings_from_config_doc
- name: resolve_export_workspace
  file: src/sevn/onboarding/export_bundle.py
  symbol: resolve_export_workspace
- name: run_export_secrets
  file: src/sevn/onboarding/export_bundle.py
  symbol: run_export_secrets
- name: FastOnboardError
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardError
- name: FastOnboardPreconditionError
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardPreconditionError
- name: FastOnboardResult
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardResult
- name: FastOnboardValidationError
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardValidationError
- name: merge_config_layers
  file: src/sevn/onboarding/fast_onboard.py
  symbol: merge_config_layers
- name: run_fast_onboard
  file: src/sevn/onboarding/fast_onboard.py
  symbol: run_fast_onboard
- name: spawn_gateway_background
  file: src/sevn/onboarding/gateway_spawn.py
  symbol: spawn_gateway_background
- name: build_authorize_url
  file: src/sevn/onboarding/github_oauth.py
  symbol: build_authorize_url
- name: callback_redirect_uri
  file: src/sevn/onboarding/github_oauth.py
  symbol: callback_redirect_uri
- name: clear_oauth_states
  file: src/sevn/onboarding/github_oauth.py
  symbol: clear_oauth_states
- name: clear_wizard_oauth_credentials
  file: src/sevn/onboarding/github_oauth.py
  symbol: clear_wizard_oauth_credentials
- name: exchange_code_for_token
  file: src/sevn/onboarding/github_oauth.py
  symbol: exchange_code_for_token
- name: fetch_github_user
  file: src/sevn/onboarding/github_oauth.py
  symbol: fetch_github_user
- name: mint_oauth_state
  file: src/sevn/onboarding/github_oauth.py
  symbol: mint_oauth_state
- name: oauth_client_credentials
  file: src/sevn/onboarding/github_oauth.py
  symbol: oauth_client_credentials
- name: oauth_configured
  file: src/sevn/onboarding/github_oauth.py
  symbol: oauth_configured
- name: set_wizard_oauth_credentials
  file: src/sevn/onboarding/github_oauth.py
  symbol: set_wizard_oauth_credentials
- name: validate_oauth_state
  file: src/sevn/onboarding/github_oauth.py
  symbol: validate_oauth_state
- name: execute_install_action
  file: src/sevn/onboarding/install_actions/executors.py
  symbol: execute_install_action
- name: idempotent_check_satisfied
  file: src/sevn/onboarding/install_actions/executors.py
  symbol: idempotent_check_satisfied
- name: run_computer_use_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_computer_use_validate
- name: run_cua_agent_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_cua_agent_validate
- name: run_lume_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_lume_validate
- name: run_openwiki_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_openwiki_validate
- name: InstallGateState
  file: src/sevn/onboarding/install_gate.py
  symbol: InstallGateState
- name: InstallResolution
  file: src/sevn/onboarding/install_gate.py
  symbol: InstallResolution
- name: apply_install_resolution
  file: src/sevn/onboarding/install_gate.py
  symbol: apply_install_resolution
- name: bind_operator_home
  file: src/sevn/onboarding/install_gate.py
  symbol: bind_operator_home
- name: install_gate_state
  file: src/sevn/onboarding/install_gate.py
  symbol: install_gate_state
- name: prompt_install_gate_tty
  file: src/sevn/onboarding/install_gate.py
  symbol: prompt_install_gate_tty
- name: prompt_keystore_passphrase_tty
  file: src/sevn/onboarding/install_gate.py
  symbol: prompt_keystore_passphrase_tty
- name: replace_keystore
  file: src/sevn/onboarding/install_gate.py
  symbol: replace_keystore
- name: resolve_install_action
  file: src/sevn/onboarding/install_gate.py
  symbol: resolve_install_action
- name: wipe_operator_home
  file: src/sevn/onboarding/install_gate.py
  symbol: wipe_operator_home
- name: InstallPlan
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: InstallPlan
- name: InstallPlanStep
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: InstallPlanStep
- name: InstallRunSummary
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: InstallRunSummary
- name: build_install_plan
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: build_install_plan
- name: collect_install_run
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: collect_install_run
- name: format_ndjson_event
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: format_ndjson_event
- name: resolve_install_root
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: resolve_install_root
- name: run_install_plan
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: run_install_plan
- name: selected_capability_ids
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: selected_capability_ids
- name: InstallStatusRow
  file: src/sevn/onboarding/live_validate.py
  symbol: InstallStatusRow
- name: ValidationCheck
  file: src/sevn/onboarding/live_validate.py
  symbol: ValidationCheck
- name: ValidationReport
  file: src/sevn/onboarding/live_validate.py
  symbol: ValidationReport
- name: asyncio_subprocess_run
  file: src/sevn/onboarding/live_validate.py
  symbol: asyncio_subprocess_run
- name: emit_openai_oauth_warnings
  file: src/sevn/onboarding/live_validate.py
  symbol: emit_openai_oauth_warnings
- name: github_hub_enabled
  file: src/sevn/onboarding/live_validate.py
  symbol: github_hub_enabled
- name: handoff_credential_keys_for_doc
  file: src/sevn/onboarding/live_validate.py
  symbol: handoff_credential_keys_for_doc
- name: install_status_to_dict
  file: src/sevn/onboarding/live_validate.py
  symbol: install_status_to_dict
- name: llm_provider_configured
  file: src/sevn/onboarding/live_validate.py
  symbol: llm_provider_configured
- name: openai_oauth_mode_active
  file: src/sevn/onboarding/live_validate.py
  symbol: openai_oauth_mode_active
- name: probe_capability_install_status
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_capability_install_status
- name: probe_github_hub
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_github_hub
- name: probe_llm_reachability
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_llm_reachability
- name: probe_mcp_reachability
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_mcp_reachability
- name: probe_openai_oauth_credential
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_openai_oauth_credential
- name: probe_pdf_weasyprint
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_pdf_weasyprint
- name: probe_secrets_backend
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_secrets_backend
- name: probe_webapp_https
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_webapp_https
- name: run_live_validation
  file: src/sevn/onboarding/live_validate.py
  symbol: run_live_validation
- name: section_uses_encrypted_file
  file: src/sevn/onboarding/live_validate.py
  symbol: section_uses_encrypted_file
- name: telegram_channel_enabled
  file: src/sevn/onboarding/live_validate.py
  symbol: telegram_channel_enabled
- name: merge_layers
  file: src/sevn/onboarding/merge.py
  symbol: merge_layers
- name: MigrationPlan
  file: src/sevn/onboarding/migrate.py
  symbol: MigrationPlan
- name: describe_schema_upgrade
  file: src/sevn/onboarding/migrate.py
  symbol: describe_schema_upgrade
- name: import_foreign_workspace
  file: src/sevn/onboarding/migrate.py
  symbol: import_foreign_workspace
- name: upgrade_schema_inplace
  file: src/sevn/onboarding/migrate.py
  symbol: upgrade_schema_inplace
- name: MyTelegramApiExtract
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: MyTelegramApiExtract
- name: MyTelegramSkipError
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: MyTelegramSkipError
- name: extract_api_hash_from_text
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: extract_api_hash_from_text
- name: extract_api_id_from_text
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: extract_api_id_from_text
- name: normalize_phone
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: normalize_phone
- name: run_fetch_my_telegram_api
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: run_fetch_my_telegram_api
- name: WizardCodexOAuthStart
  file: src/sevn/onboarding/openai_oauth.py
  symbol: WizardCodexOAuthStart
- name: clear_wizard_codex_oauth_flows
  file: src/sevn/onboarding/openai_oauth.py
  symbol: clear_wizard_codex_oauth_flows
- name: poll_wizard_codex_oauth
  file: src/sevn/onboarding/openai_oauth.py
  symbol: poll_wizard_codex_oauth
- name: start_wizard_codex_oauth
  file: src/sevn/onboarding/openai_oauth.py
  symbol: start_wizard_codex_oauth
- name: build_profile_inspector_payload
  file: src/sevn/onboarding/profile_inspector.py
  symbol: build_profile_inspector_payload
- name: format_inspector_value
  file: src/sevn/onboarding/profile_inspector.py
  symbol: format_inspector_value
- name: get_config_at_path
  file: src/sevn/onboarding/profile_inspector.py
  symbol: get_config_at_path
- name: load_profile_catalog
  file: src/sevn/onboarding/profiles.py
  symbol: load_profile_catalog
- name: load_profile_catalog_for_wizard
  file: src/sevn/onboarding/profiles.py
  symbol: load_profile_catalog_for_wizard
- name: load_profile_fragment
  file: src/sevn/onboarding/profiles.py
  symbol: load_profile_fragment
- name: profile_catalog_path
  file: src/sevn/onboarding/profiles.py
  symbol: profile_catalog_path
- name: profile_default_sandbox_mode
  file: src/sevn/onboarding/profiles.py
  symbol: profile_default_sandbox_mode
- name: profile_has_capabilities_defaults
  file: src/sevn/onboarding/profiles.py
  symbol: profile_has_capabilities_defaults
- name: promote_draft
  file: src/sevn/onboarding/promote.py
  symbol: promote_draft
- name: spawn_proxy_background
  file: src/sevn/onboarding/proxy_spawn.py
  symbol: spawn_proxy_background
- name: ensure_skills_user_dir
  file: src/sevn/onboarding/seed.py
  symbol: ensure_skills_user_dir
- name: expected_core_skill_ids
  file: src/sevn/onboarding/seed.py
  symbol: expected_core_skill_ids
- name: list_deployed_core_skill_ids
  file: src/sevn/onboarding/seed.py
  symbol: list_deployed_core_skill_ids
- name: load_personality_presets
  file: src/sevn/onboarding/seed.py
  symbol: load_personality_presets
- name: load_template
  file: src/sevn/onboarding/seed.py
  symbol: load_template
- name: opt_in_skill_ids_from_capabilities
  file: src/sevn/onboarding/seed.py
  symbol: opt_in_skill_ids_from_capabilities
- name: refresh_bundled_core_skills
  file: src/sevn/onboarding/seed.py
  symbol: refresh_bundled_core_skills
- name: render_template
  file: src/sevn/onboarding/seed.py
  symbol: render_template
- name: resolve_agent_display_name
  file: src/sevn/onboarding/seed.py
  symbol: resolve_agent_display_name
- name: seed_bundled_skills
  file: src/sevn/onboarding/seed.py
  symbol: seed_bundled_skills
- name: seed_llm_params
  file: src/sevn/onboarding/seed.py
  symbol: seed_llm_params
- name: seed_narrative_templates
  file: src/sevn/onboarding/seed.py
  symbol: seed_narrative_templates
- name: seed_personality_from_wizard
  file: src/sevn/onboarding/seed.py
  symbol: seed_personality_from_wizard
- name: seed_tracing_defaults
  file: src/sevn/onboarding/seed.py
  symbol: seed_tracing_defaults
- name: verify_core_skills_deployed
  file: src/sevn/onboarding/seed.py
  symbol: verify_core_skills_deployed
- name: restart_services_after_promote
  file: src/sevn/onboarding/service_restart.py
  symbol: restart_services_after_promote
- name: handoff_child_env
  file: src/sevn/onboarding/spawn_env.py
  symbol: handoff_child_env
- name: TelegramBotExtract
  file: src/sevn/onboarding/telegram_automation.py
  symbol: TelegramBotExtract
- name: extract_bot_token_from_text
  file: src/sevn/onboarding/telegram_automation.py
  symbol: extract_bot_token_from_text
- name: extract_bot_username_from_text
  file: src/sevn/onboarding/telegram_automation.py
  symbol: extract_bot_username_from_text
- name: normalize_bot_username
  file: src/sevn/onboarding/telegram_automation.py
  symbol: normalize_bot_username
- name: open_telegram_web
  file: src/sevn/onboarding/telegram_automation.py
  symbol: open_telegram_web
- name: run_create_new_bot
  file: src/sevn/onboarding/telegram_automation.py
  symbol: run_create_new_bot
- name: run_lookup_existing_bot
  file: src/sevn/onboarding/telegram_automation.py
  symbol: run_lookup_existing_bot
- name: suggest_owner_user_id_from_text
  file: src/sevn/onboarding/telegram_automation.py
  symbol: suggest_owner_user_id_from_text
- name: wait_for_login
  file: src/sevn/onboarding/telegram_automation.py
  symbol: wait_for_login
- name: OnboardApp
  file: src/sevn/onboarding/tui.py
  symbol: OnboardApp
- name: run_textual_onboarding
  file: src/sevn/onboarding/tui.py
  symbol: run_textual_onboarding
- name: emit_unused_provider_warnings
  file: src/sevn/onboarding/validate.py
  symbol: emit_unused_provider_warnings
- name: validate_workspace_document
  file: src/sevn/onboarding/validate.py
  symbol: validate_workspace_document
- name: apply_model_slot_policy
  file: src/sevn/onboarding/web_app.py
  symbol: apply_model_slot_policy
- name: create_onboarding_app
  file: src/sevn/onboarding/web_app.py
  symbol: create_onboarding_app
- name: normalize_llm_main_model_layer
  file: src/sevn/onboarding/web_app.py
  symbol: normalize_llm_main_model_layer
- name: normalize_secrets_backend_section
  file: src/sevn/onboarding/web_app.py
  symbol: normalize_secrets_backend_section
- name: credentials_status
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: credentials_status
- name: default_wizard_secrets_section
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: default_wizard_secrets_section
- name: delete_wizard_credential
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: delete_wizard_credential
- name: get_wizard_credential
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: get_wizard_credential
- name: probe_host_github_token
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: probe_host_github_token
- name: read_wizard_credential_values
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: read_wizard_credential_values
- name: resolve_wizard_secrets_section
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: resolve_wizard_secrets_section
- name: secrets_section_from_sevn_json
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: secrets_section_from_sevn_json
- name: store_wizard_credentials
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: store_wizard_credentials
- name: unlock_wizard_keystore
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: unlock_wizard_keystore
- name: verify_wizard_passphrase
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: verify_wizard_passphrase
- name: create_github_repo_via_api
  file: src/sevn/onboarding/workspace_backup.py
  symbol: create_github_repo_via_api
- name: create_repo_via_gh_cli
  file: src/sevn/onboarding/workspace_backup.py
  symbol: create_repo_via_gh_cli
- name: create_workspace_backup_repo
  file: src/sevn/onboarding/workspace_backup.py
  symbol: create_workspace_backup_repo
- name: default_backup_repo_name
  file: src/sevn/onboarding/workspace_backup.py
  symbol: default_backup_repo_name
- name: repo_url_from_api_response
  file: src/sevn/onboarding/workspace_backup.py
  symbol: repo_url_from_api_response
- name: resolve_backup_default_name
  file: src/sevn/onboarding/workspace_backup.py
  symbol: resolve_backup_default_name
- name: sanitize_repo_name
  file: src/sevn/onboarding/workspace_backup.py
  symbol: sanitize_repo_name
specs: []
personas: []
prd_profile: null
---

## Purpose

Deliver the merge + validation + promotion pipeline every setup path shares so sevn.json stays the single source of truth (prd-06-setup-and-operations §5.4, spec-02-config-and-workspace): shipped pres

Primary code trees: [`src/sevn/onboarding`](src/sevn/onboarding/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`BrowserSession`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`BrowserStartRequest`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`get_browser_session`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`register_shutdown_hooks`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`reset_browser_session_for_tests`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`resolve_start_request`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`stop_browser_on_shutdown`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`CapabilityEntry`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`CapabilityGroup`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`CapabilityManifest`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`GroupWithCapabilities`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`InstallAction`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- _…and 168 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`BrowserSession`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`BrowserStartRequest`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`get_browser_session`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`register_shutdown_hooks`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`reset_browser_session_for_tests`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`resolve_start_request`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`stop_browser_on_shutdown`](src/sevn/onboarding/browser_automation.py) — `src/sevn/onboarding/browser_automation.py`
- [`CapabilityEntry`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`CapabilityGroup`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`CapabilityManifest`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`GroupWithCapabilities`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- [`InstallAction`](src/sevn/onboarding/capabilities_manifest.py) — `src/sevn/onboarding/capabilities_manifest.py`
- _…and 168 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/onboarding`](src/sevn/onboarding/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/onboarding`](src/sevn/onboarding/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
