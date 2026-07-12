---
id: spec-09-security-scanner
kind: spec
title: Security scanner — Spec
status: done
owner: Alex
summary: Deliver a single scanner subsystem that runs in the gateway process so hostile
  content is filtered before the Triager or any routing model sees user-visible text,
  transcripts, or selected tool output.
last_updated: '2026-07-07'
fingerprint: sha256:894715877de9bdd3033a85819c6e01e6984d82513ff477cead99c630a322d7d8
related: []
sources:
- src/sevn/security/**
parent_prd: prd-03-trust-and-control
depends_on: []
build_phase: null
interfaces:
- name: apply_namespace_egress_firewall
  file: src/sevn/security/egress_firewall.py
  symbol: apply_namespace_egress_firewall
- name: egress_firewall_noop
  file: src/sevn/security/egress_firewall.py
  symbol: egress_firewall_noop
- name: write_linux_iptables_ruleset
  file: src/sevn/security/egress_firewall.py
  symbol: write_linux_iptables_ruleset
- name: write_macos_pf_ruleset
  file: src/sevn/security/egress_firewall.py
  symbol: write_macos_pf_ruleset
- name: BlockReason
  file: src/sevn/security/llm_guard_scanner.py
  symbol: BlockReason
- name: LLMGuardScanner
  file: src/sevn/security/llm_guard_scanner.py
  symbol: LLMGuardScanner
- name: ScanResult
  file: src/sevn/security/llm_guard_scanner.py
  symbol: ScanResult
- name: ScanVerdict
  file: src/sevn/security/llm_guard_scanner.py
  symbol: ScanVerdict
- name: scan_patch_diff
  file: src/sevn/security/llm_guard_scanner.py
  symbol: scan_patch_diff
- name: assert_shadow_workspace_excludes_llmignore
  file: src/sevn/security/llmignore.py
  symbol: assert_shadow_workspace_excludes_llmignore
- name: ensure_llmignore_layout
  file: src/sevn/security/llmignore.py
  symbol: ensure_llmignore_layout
- name: is_llmignored
  file: src/sevn/security/llmignore.py
  symbol: is_llmignored
- name: resolve_llmignore_root
  file: src/sevn/security/llmignore.py
  symbol: resolve_llmignore_root
- name: sweep_expired
  file: src/sevn/security/llmignore.py
  symbol: sweep_expired
- name: write_blocked_feedback
  file: src/sevn/security/llmignore.py
  symbol: write_blocked_feedback
- name: write_blocked_inbound
  file: src/sevn/security/llmignore.py
  symbol: write_blocked_inbound
- name: AuthorizationFlow
  file: src/sevn/security/oauth/authorize.py
  symbol: AuthorizationFlow
- name: build_authorization_flow
  file: src/sevn/security/oauth/authorize.py
  symbol: build_authorization_flow
- name: OAuthCallbackResult
  file: src/sevn/security/oauth/callback.py
  symbol: OAuthCallbackResult
- name: OAuthCallbackServer
  file: src/sevn/security/oauth/callback.py
  symbol: OAuthCallbackServer
- name: parse_pasted_oauth_redirect
  file: src/sevn/security/oauth/callback.py
  symbol: parse_pasted_oauth_redirect
- name: start_local_callback_server
  file: src/sevn/security/oauth/callback.py
  symbol: start_local_callback_server
- name: CodexOAuthCredential
  file: src/sevn/security/oauth/credential.py
  symbol: CodexOAuthCredential
- name: oauth_openai_secret_alias
  file: src/sevn/security/oauth/credential.py
  symbol: oauth_openai_secret_alias
- name: resolution_probe_credential
  file: src/sevn/security/oauth/credential.py
  symbol: resolution_probe_credential
- name: capture_codex_oauth_callback
  file: src/sevn/security/oauth/login_flow.py
  symbol: capture_codex_oauth_callback
- name: complete_codex_oauth_login
  file: src/sevn/security/oauth/login_flow.py
  symbol: complete_codex_oauth_login
- name: exchange_and_persist_codex_oauth
  file: src/sevn/security/oauth/login_flow.py
  symbol: exchange_and_persist_codex_oauth
- name: load_codex_oauth_credential_from_workspace
  file: src/sevn/security/oauth/login_flow.py
  symbol: load_codex_oauth_credential_from_workspace
- name: PkcePair
  file: src/sevn/security/oauth/pkce.py
  symbol: PkcePair
- name: generate_pkce_pair
  file: src/sevn/security/oauth/pkce.py
  symbol: generate_pkce_pair
- name: load_codex_oauth_credential
  file: src/sevn/security/oauth/storage.py
  symbol: load_codex_oauth_credential
- name: persist_codex_oauth_credential
  file: src/sevn/security/oauth/storage.py
  symbol: persist_codex_oauth_credential
- name: TokenExchangeResult
  file: src/sevn/security/oauth/token_client.py
  symbol: TokenExchangeResult
- name: exchange_authorization_code
  file: src/sevn/security/oauth/token_client.py
  symbol: exchange_authorization_code
- name: extract_account_id
  file: src/sevn/security/oauth/token_client.py
  symbol: extract_account_id
- name: refresh_access_token
  file: src/sevn/security/oauth/token_client.py
  symbol: refresh_access_token
- name: SandboxConfigurationError
  file: src/sevn/security/sandbox_errors.py
  symbol: SandboxConfigurationError
- name: SandboxError
  file: src/sevn/security/sandbox_errors.py
  symbol: SandboxError
- name: SandboxPolicyViolationError
  file: src/sevn/security/sandbox_errors.py
  symbol: SandboxPolicyViolationError
- name: DockerSandboxRuntime
  file: src/sevn/security/sandbox_runtime.py
  symbol: DockerSandboxRuntime
- name: SandboxDriver
  file: src/sevn/security/sandbox_runtime.py
  symbol: SandboxDriver
- name: SandboxRuntime
  file: src/sevn/security/sandbox_runtime.py
  symbol: SandboxRuntime
- name: SubprocessSandboxRuntime
  file: src/sevn/security/sandbox_runtime.py
  symbol: SubprocessSandboxRuntime
- name: build_sandbox_child_env
  file: src/sevn/security/sandbox_runtime.py
  symbol: build_sandbox_child_env
- name: check_self_preservation_argv
  file: src/sevn/security/sandbox_runtime.py
  symbol: check_self_preservation_argv
- name: docker_daemon_reachable
  file: src/sevn/security/sandbox_runtime.py
  symbol: docker_daemon_reachable
- name: load_snapshot_manifest_version
  file: src/sevn/security/sandbox_runtime.py
  symbol: load_snapshot_manifest_version
- name: make_runtime_for_driver
  file: src/sevn/security/sandbox_runtime.py
  symbol: make_runtime_for_driver
- name: materialize_shadow_workspace
  file: src/sevn/security/sandbox_runtime.py
  symbol: materialize_shadow_workspace
- name: pid_target_gate_stub
  file: src/sevn/security/sandbox_runtime.py
  symbol: pid_target_gate_stub
- name: prune_workspace_snapshots
  file: src/sevn/security/sandbox_runtime.py
  symbol: prune_workspace_snapshots
- name: resolve_sandbox_driver
  file: src/sevn/security/sandbox_runtime.py
  symbol: resolve_sandbox_driver
- name: snapshot_tarball_format_supported
  file: src/sevn/security/sandbox_runtime.py
  symbol: snapshot_tarball_format_supported
- name: snapshots_dir
  file: src/sevn/security/sandbox_runtime.py
  symbol: snapshots_dir
- name: write_workspace_snapshot_tarball
  file: src/sevn/security/sandbox_runtime.py
  symbol: write_workspace_snapshot_tarball
- name: SandboxLabeledContainer
  file: src/sevn/security/sandbox_sweeper.py
  symbol: SandboxLabeledContainer
- name: SandboxRunRegistry
  file: src/sevn/security/sandbox_sweeper.py
  symbol: SandboxRunRegistry
- name: orphan_container_should_kill
  file: src/sevn/security/sandbox_sweeper.py
  symbol: orphan_container_should_kill
- name: sweep_orphan_labels
  file: src/sevn/security/sandbox_sweeper.py
  symbol: sweep_orphan_labels
- name: EncryptedFileBackend
  file: src/sevn/security/secrets/backends/encrypted_file.py
  symbol: EncryptedFileBackend
- name: default_encrypted_store_path
  file: src/sevn/security/secrets/backends/encrypted_file.py
  symbol: default_encrypted_store_path
- name: LinuxSecretServiceBackend
  file: src/sevn/security/secrets/backends/linux_secret_service.py
  symbol: LinuxSecretServiceBackend
- name: MacOSKeychainBackend
  file: src/sevn/security/secrets/backends/macos_keychain.py
  symbol: MacOSKeychainBackend
- name: OpenBaoBackend
  file: src/sevn/security/secrets/backends/openbao.py
  symbol: OpenBaoBackend
- name: ProtonPassCliBackend
  file: src/sevn/security/secrets/backends/proton_pass.py
  symbol: ProtonPassCliBackend
- name: ResolvedSecretsCache
  file: src/sevn/security/secrets/cache.py
  symbol: ResolvedSecretsCache
- name: SecretsChain
  file: src/sevn/security/secrets/chain.py
  symbol: SecretsChain
- name: SecretsChainWriteError
  file: src/sevn/security/secrets/chain.py
  symbol: SecretsChainWriteError
- name: get_secret_resilient
  file: src/sevn/security/secrets/chain.py
  symbol: get_secret_resilient
- name: SecretUnresolvedError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretUnresolvedError
- name: SecretsBackendError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsBackendError
- name: SecretsError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsError
- name: SecretsStoreCorruptError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsStoreCorruptError
- name: is_encrypted_store_decrypt_failure
  file: src/sevn/security/secrets/errors.py
  symbol: is_encrypted_store_decrypt_failure
- name: is_encrypted_store_unlock_error
  file: src/sevn/security/secrets/errors.py
  symbol: is_encrypted_store_unlock_error
- name: default_chain_entries
  file: src/sevn/security/secrets/factory.py
  symbol: default_chain_entries
- name: parse_optional_master_key_hex
  file: src/sevn/security/secrets/factory.py
  symbol: parse_optional_master_key_hex
- name: resolve_backend
  file: src/sevn/security/secrets/factory.py
  symbol: resolve_backend
- name: resolve_primary_encrypted_store_path
  file: src/sevn/security/secrets/factory.py
  symbol: resolve_primary_encrypted_store_path
- name: secrets_chain_from_workspace
  file: src/sevn/security/secrets/factory.py
  symbol: secrets_chain_from_workspace
- name: fetch_unlock_secret_from_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: fetch_unlock_secret_from_keychain
- name: keychain_has_unlock_secret
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: keychain_has_unlock_secret
- name: prime_unlock_env_from_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: prime_unlock_env_from_keychain
- name: reconcile_unlock_env_with_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: reconcile_unlock_env_with_keychain
- name: unlock_env_var_for
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: unlock_env_var_for
- name: SecretsBackend
  file: src/sevn/security/secrets/protocol.py
  symbol: SecretsBackend
- name: EnvUnresolvedError
  file: src/sevn/security/secrets/value_expand.py
  symbol: EnvUnresolvedError
- name: expand_env_refs
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_env_refs
- name: expand_refs_env_then_secret
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_refs_env_then_secret
- name: expand_secret_refs
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_secret_refs
specs: []
personas: []
---

## Purpose

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Purpose.

## Public Interface

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Public Interface.

## Data Model

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Data Model.

## Internal Architecture

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Internal Architecture.

## Behavior

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Behavior.

## Failure Modes

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Failure Modes.

## Test Strategy

Offline scaffold for Security scanner — Spec (spec-09-security-scanner) — Test Strategy.
