---
id: spec-08-sandbox
kind: spec
title: Sandbox — Spec
status: scaffold
owner: Alex
summary: Deliver a single tool-execution sandbox used by sandbox_exec, exec / safebash
  (when routed through the execution sandbox), process when configured for sandbox
  routing, and skill subprocesses spawned b
last_updated: '2026-08-06'
fingerprint: sha256:585b19541e4ddd465763ee603122da7cbe1280b579ec8ff74ecc8549f0bcc15f
related: []
sources:
- src/sevn/security/**
parent_prd: prd-03-trust-and-control
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-06-secrets
- spec-07-egress-proxy
- spec-17-gateway
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
- name: IngressBodyLimitMiddleware
  file: src/sevn/security/ingress_policy.py
  symbol: IngressBodyLimitMiddleware
- name: first_ws_frame_within_limit
  file: src/sevn/security/ingress_policy.py
  symbol: first_ws_frame_within_limit
- name: ingress_body_too_large_response
  file: src/sevn/security/ingress_policy.py
  symbol: ingress_body_too_large_response
- name: read_limited_body
  file: src/sevn/security/ingress_policy.py
  symbol: read_limited_body
- name: wire_ingress_body_limit
  file: src/sevn/security/ingress_policy.py
  symbol: wire_ingress_body_limit
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
- name: configured_sandbox_image
  file: src/sevn/security/sandbox_runtime.py
  symbol: configured_sandbox_image
- name: docker_daemon_reachable
  file: src/sevn/security/sandbox_runtime.py
  symbol: docker_daemon_reachable
- name: ensure_proxy_attached_to_sandbox_network
  file: src/sevn/security/sandbox_runtime.py
  symbol: ensure_proxy_attached_to_sandbox_network
- name: ensure_sandbox_docker_network
  file: src/sevn/security/sandbox_runtime.py
  symbol: ensure_sandbox_docker_network
- name: ensure_sandbox_image_ready
  file: src/sevn/security/sandbox_runtime.py
  symbol: ensure_sandbox_image_ready
- name: list_labeled_sandbox_containers
  file: src/sevn/security/sandbox_runtime.py
  symbol: list_labeled_sandbox_containers
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
- name: reap_stale_sandbox_containers
  file: src/sevn/security/sandbox_runtime.py
  symbol: reap_stale_sandbox_containers
- name: refresh_sandbox_image
  file: src/sevn/security/sandbox_runtime.py
  symbol: refresh_sandbox_image
- name: resolve_sandbox_driver
  file: src/sevn/security/sandbox_runtime.py
  symbol: resolve_sandbox_driver
- name: rewrite_proxy_url_for_sandbox_network
  file: src/sevn/security/sandbox_runtime.py
  symbol: rewrite_proxy_url_for_sandbox_network
- name: sandbox_image_stamp_missing
  file: src/sevn/security/sandbox_runtime.py
  symbol: sandbox_image_stamp_missing
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
- name: BitwardenCliBackend
  file: src/sevn/security/secrets/backends/bitwarden.py
  symbol: BitwardenCliBackend
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
- name: OnePasswordCliBackend
  file: src/sevn/security/secrets/backends/one_password.py
  symbol: OnePasswordCliBackend
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
- name: log_unlock_env_conflict
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: log_unlock_env_conflict
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
- name: SecretProvenanceReport
  file: src/sevn/security/secrets/provenance.py
  symbol: SecretProvenanceReport
- name: provenance_for_cache_entry
  file: src/sevn/security/secrets/provenance.py
  symbol: provenance_for_cache_entry
- name: resolve_secret_provenance
  file: src/sevn/security/secrets/provenance.py
  symbol: resolve_secret_provenance
- name: bind_routing_secrets_scope
  file: src/sevn/security/secrets/routing_scope.py
  symbol: bind_routing_secrets_scope
- name: current_routing_secrets_scope
  file: src/sevn/security/secrets/routing_scope.py
  symbol: current_routing_secrets_scope
- name: reset_routing_secrets_scope
  file: src/sevn/security/secrets/routing_scope.py
  symbol: reset_routing_secrets_scope
- name: scoped_secret_logical_key
  file: src/sevn/security/secrets/routing_scope.py
  symbol: scoped_secret_logical_key
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
- name: augment_operator_path_for_subprocess
  file: src/sevn/security/trigger_spawn_env.py
  symbol: augment_operator_path_for_subprocess
- name: bind_webhook_minimal_host_env
  file: src/sevn/security/trigger_spawn_env.py
  symbol: bind_webhook_minimal_host_env
- name: host_env_base_for_subprocess
  file: src/sevn/security/trigger_spawn_env.py
  symbol: host_env_base_for_subprocess
- name: is_webhook_trigger_scope
  file: src/sevn/security/trigger_spawn_env.py
  symbol: is_webhook_trigger_scope
- name: minimal_webhook_host_env
  file: src/sevn/security/trigger_spawn_env.py
  symbol: minimal_webhook_host_env
- name: redact_telegram_bot_token
  file: src/sevn/security/trigger_spawn_env.py
  symbol: redact_telegram_bot_token
---

## Purpose

Deliver a single tool-execution sandbox used by sandbox_exec, exec / safebash (when routed through the execution sandbox), process when configured for sandbox routing, and skill subprocesses spawned b

Primary code trees: [`src/sevn/security`](src/sevn/security/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`apply_namespace_egress_firewall`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`egress_firewall_noop`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`write_linux_iptables_ruleset`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`write_macos_pf_ruleset`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`BlockReason`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`LLMGuardScanner`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`ScanResult`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`ScanVerdict`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`scan_patch_diff`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`assert_shadow_workspace_excludes_llmignore`](src/sevn/security/llmignore.py) — `src/sevn/security/llmignore.py`
- [`ensure_llmignore_layout`](src/sevn/security/llmignore.py) — `src/sevn/security/llmignore.py`
- [`is_llmignored`](src/sevn/security/llmignore.py) — `src/sevn/security/llmignore.py`
- _…and 79 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`apply_namespace_egress_firewall`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`egress_firewall_noop`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`write_linux_iptables_ruleset`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`write_macos_pf_ruleset`](src/sevn/security/egress_firewall.py) — `src/sevn/security/egress_firewall.py`
- [`BlockReason`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`LLMGuardScanner`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`ScanResult`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`ScanVerdict`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`scan_patch_diff`](src/sevn/security/llm_guard_scanner.py) — `src/sevn/security/llm_guard_scanner.py`
- [`assert_shadow_workspace_excludes_llmignore`](src/sevn/security/llmignore.py) — `src/sevn/security/llmignore.py`
- [`ensure_llmignore_layout`](src/sevn/security/llmignore.py) — `src/sevn/security/llmignore.py`
- [`is_llmignored`](src/sevn/security/llmignore.py) — `src/sevn/security/llmignore.py`
- _…and 79 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/security`](src/sevn/security/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/security`](src/sevn/security/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Amendments (post-audit-0.0.1 W8 — #171)

Docker spawn enforces egress via the dedicated ``--internal`` network
``sevn-sandbox`` (``ensure_sandbox_docker_network``). The spawn path does
**not** write ``.sevn/sandbox-egress.*.rules`` files or emit
``network_policy_path`` telemetry — ``sandbox.runtime`` carries
``network_enforcement: "docker_internal"`` beside ``network_mode`` instead (D15).
``_write_docker_network_policy`` and ``apply_namespace_egress_firewall`` remain
for subprocess/namespace mode and operator reference.

**Known tradeoff:** ``ensure_proxy_attached_to_sandbox_network`` attaches the
**whole** egress-proxy container to ``sevn-sandbox`` so sandboxes can reach the
reverse-proxy API; the proxy shares the internal bridge with sandboxes.

## Amendments (prod-readiness-0.0.1 W8 — C4.2, C5.1–C5.3, D43)

Gateway startup resolves and validates the configured sandbox image digest **once**
(``ensure_sandbox_image_ready`` / ``ensure_gateway_sandbox_image_ready``) and caches
it for the process lifetime, keyed by the configured image ref so an
``rlm.docker_image`` change is not masked (C5.1). ``DockerSandboxRuntime.spawn``
consumes that cache; ``docker run`` and the ``sandbox.runtime`` trace ``image``
attribute carry the digest actually executed.

**Local short circuit (C5.2):** a digest-pinned ref that is already present locally
does not ``docker pull``. Tagged refs still pull on a cold process cache (deploy
cold-start), then pin via ``RepoDigests``.

**Explicit refresh (C5.3):** only ``refresh_sandbox_image`` invalidates the cache and
re-pulls. Spawn never refreshes implicitly.

**Pre-pull / refuse (C4.2):** ``make sandbox-image-pull`` pre-pulls
``DEFAULT_SANDBOX_IMAGE`` at deploy. When Docker is reachable and the configured
image is stamped, gateway lifespan calls ``ensure_gateway_sandbox_image_ready`` and
**refuses to start** if the digest is absent and cannot be fetched. Unstamped
local checkouts skip the boot ensure (spawn still fail-closes per W7.4).

**Hard constraint (D43):** the pull-then-pin contract and the empty-``RepoDigests``
fail-closed error in ``_resolve_digest_pinned_image`` are unchanged; the ``.Id``
fallback stays deleted.

## Amendments (prod-readiness-0.0.1 W7 — C4.1, C4.3, D42)

The default sandbox image is a **single** module constant
``DEFAULT_SANDBOX_IMAGE`` in ``src/sevn/security/sandbox_runtime.py``, consumed by
``DockerSandboxRuntime.__init__``, ``make_runtime_for_driver``, and
``agent/runtimes/sandbox._default_repl_image``. The shipped form is a digest pin
(``ghcr.io/sevn-bot/sevn/sandbox@sha256:…``), never a mutable ``:dev`` / ``:latest``
tag.

**Build stamp (W7.4):** release builds replace the ``sha256:UNSTAMPED`` literal on
``_SANDBOX_IMAGE_DIGEST_STAMP`` via ``scripts/stamp_default_sandbox_image.py``
(after the sandbox image digest is known), or set ``SEVN_SANDBOX_IMAGE_DIGEST`` at
gateway process start. ``publish-ghcr`` stamps from ``steps.sandbox.outputs.digest``
before building gateway / gateway.browser / gateway.gui images and asserts with
``--require-stamped``; those Dockerfiles also accept ``SEVN_SANDBOX_IMAGE_DIGEST`` as
a build-arg. **Failure mode when the stamp is missing:** spawn /
``_resolve_digest_pinned_image`` raises ``SandboxConfigurationError`` and does
**not** fall back to a mutable tag (D43 spirit). Release CI may also pass
``--require-stamped`` to ``scripts/check_sandbox_mutable_image_tags.py``.

**Operator override:** only ``rlm.docker_image`` is honoured. There is **no**
``sandbox.docker_image`` key (documented in ``infra/sevn.schema.json``).

**CI (C4.3):** ``make sandbox-image-check`` (wired into ``ci-infra``) rejects any
``ghcr.io/sevn-bot/sevn/sandbox:(dev|latest|…)`` literal under ``src/``.

## Amendments (post-audit-0.0.1 W6 — #168)

``build_sandbox_child_env`` (§2.2) emits only ``SEVN_PROXY_URL``,
``SEVN_SESSION_TOKEN``, and ``SEVN_WORKSPACE``. It **never** injects
``SEVN_PROXY_SHARED_SECRET``, ``X-Sevn-Proxy-Token``, or forward-proxy env vars
(``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY``) — the egress proxy is a reverse
path-prefix API, not a CONNECT forward proxy (D13). ``SEVN_SESSION_TOKEN`` carries
a scoped per-run ``X-Sevn-Session-Token`` minted at spawn (``mint_session_token``,
``sandbox`` scope); see spec-07 W6 amendment for validation semantics.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
