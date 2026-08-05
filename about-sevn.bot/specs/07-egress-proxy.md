---
id: spec-07-egress-proxy
kind: spec
title: Egress proxy — Spec
status: scaffold
owner: Alex
summary: Product pairing (v1). Deployment, paired daemon install, onboarding validation,
  and Mission Control management of the proxy are specified in prd-06-setup-and-operations
  and prd-07-mission-control §5.1
last_updated: '2026-08-05'
fingerprint: sha256:3f99a93c0925e204a2cc98174b9dfc729ef71f63a0063d8967b81b67e103fd0e
related: []
sources:
- src/sevn/proxy/**
parent_prd: prd-03-trust-and-control
depends_on:
- spec-00-foundation
- spec-02-config-and-workspace
- spec-05-llm-transports
- spec-06-secrets
build_phase: null
interfaces:
- name: normalize_anthropic_request_body
  file: src/sevn/proxy/anthropic_body.py
  symbol: normalize_anthropic_request_body
- name: create_app
  file: src/sevn/proxy/app.py
  symbol: create_app
- name: llm_post_auth_failure
  file: src/sevn/proxy/auth.py
  symbol: llm_post_auth_failure
- name: log_proxy_allow_unauthenticated_boot_warning
  file: src/sevn/proxy/auth.py
  symbol: log_proxy_allow_unauthenticated_boot_warning
- name: mint_session_token
  file: src/sevn/proxy/auth.py
  symbol: mint_session_token
- name: proxy_allow_unauthenticated
  file: src/sevn/proxy/auth.py
  symbol: proxy_allow_unauthenticated
- name: validate_session_token
  file: src/sevn/proxy/auth.py
  symbol: validate_session_token
- name: converse_via_bedrock
  file: src/sevn/proxy/bedrock_converse.py
  symbol: converse_via_bedrock
- name: ensure_proxy_shared_secret_file
  file: src/sevn/proxy/bootstrap_secret.py
  symbol: ensure_proxy_shared_secret_file
- name: main
  file: src/sevn/proxy/bootstrap_secret.py
  symbol: main
- name: proxy_shared_secret_path
  file: src/sevn/proxy/bootstrap_secret.py
  symbol: proxy_shared_secret_path
- name: read_proxy_shared_secret_file
  file: src/sevn/proxy/bootstrap_secret.py
  symbol: read_proxy_shared_secret_file
- name: resolve_effective_proxy_shared_secret
  file: src/sevn/proxy/bootstrap_secret.py
  symbol: resolve_effective_proxy_shared_secret
- name: aggregate_responses_sse
  file: src/sevn/proxy/codex_translation.py
  symbol: aggregate_responses_sse
- name: translate_chat_to_responses_request
  file: src/sevn/proxy/codex_translation.py
  symbol: translate_chat_to_responses_request
- name: translate_responses_sse_to_chat_stream
  file: src/sevn/proxy/codex_translation.py
  symbol: translate_responses_sse_to_chat_stream
- name: translate_responses_to_chat_completion
  file: src/sevn/proxy/codex_translation.py
  symbol: translate_responses_to_chat_completion
- name: build_codex_request_headers
  file: src/sevn/proxy/codex_transport.py
  symbol: build_codex_request_headers
- name: codex_responses_url
  file: src/sevn/proxy/codex_transport.py
  symbol: codex_responses_url
- name: ProviderCredentialEntry
  file: src/sevn/proxy/credentials.py
  symbol: ProviderCredentialEntry
- name: ProviderCredentials
  file: src/sevn/proxy/credentials.py
  symbol: ProviderCredentials
- name: build_proxy_settings
  file: src/sevn/proxy/credentials.py
  symbol: build_proxy_settings
- name: build_proxy_settings_sync
  file: src/sevn/proxy/credentials.py
  symbol: build_proxy_settings_sync
- name: credential_unresolved_detail
  file: src/sevn/proxy/credentials.py
  symbol: credential_unresolved_detail
- name: resolve_oauth_request_credential
  file: src/sevn/proxy/credentials.py
  symbol: resolve_oauth_request_credential
- name: resolve_oauth_request_credential_async
  file: src/sevn/proxy/credentials.py
  symbol: resolve_oauth_request_credential_async
- name: resolve_request_credential
  file: src/sevn/proxy/credentials.py
  symbol: resolve_request_credential
- name: post_json
  file: src/sevn/proxy/forward.py
  symbol: post_json
- name: post_sse_stream
  file: src/sevn/proxy/forward.py
  symbol: post_sse_stream
- name: redact_headers
  file: src/sevn/proxy/forward.py
  symbol: redact_headers
- name: summarize_request_body
  file: src/sevn/proxy/forward.py
  symbol: summarize_request_body
- name: build_proxy_upstream_timeout
  file: src/sevn/proxy/http_client.py
  symbol: build_proxy_upstream_timeout
- name: create_proxy_http_client
  file: src/sevn/proxy/http_client.py
  symbol: create_proxy_http_client
- name: dispatch_cursor
  file: src/sevn/proxy/integration/cursor.py
  symbol: dispatch_cursor
- name: dispatch_github
  file: src/sevn/proxy/integration/github.py
  symbol: dispatch_github
- name: deep_expand_secret_refs
  file: src/sevn/proxy/integration/mcp_expand.py
  symbol: deep_expand_secret_refs
- name: merge_mcp_profile_into_args
  file: src/sevn/proxy/integration/mcp_expand.py
  symbol: merge_mcp_profile_into_args
- name: integration_post
  file: src/sevn/proxy/integration/router.py
  symbol: integration_post
- name: OauthCredentialMissingError
  file: src/sevn/proxy/oauth_lifecycle.py
  symbol: OauthCredentialMissingError
- name: ensure_fresh_oauth_credential
  file: src/sevn/proxy/oauth_lifecycle.py
  symbol: ensure_fresh_oauth_credential
- name: is_oauth_credential_fresh
  file: src/sevn/proxy/oauth_lifecycle.py
  symbol: is_oauth_credential_fresh
- name: ProxySettings
  file: src/sevn/proxy/settings.py
  symbol: ProxySettings
- name: brave_search_json
  file: src/sevn/proxy/web_forward.py
  symbol: brave_search_json
- name: web_fetch_json
  file: src/sevn/proxy/web_forward.py
  symbol: web_fetch_json
---

## Purpose

Product pairing (v1). Deployment, paired daemon install, onboarding validation, and Mission Control management of the proxy are specified in prd-06-setup-and-operations and prd-07-mission-control §5.1

Primary code trees: [`src/sevn/proxy`](src/sevn/proxy/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`normalize_anthropic_request_body`](src/sevn/proxy/anthropic_body.py) — `src/sevn/proxy/anthropic_body.py`
- [`create_app`](src/sevn/proxy/app.py) — `src/sevn/proxy/app.py`
- [`llm_post_auth_failure`](src/sevn/proxy/auth.py) — `src/sevn/proxy/auth.py`
- [`converse_via_bedrock`](src/sevn/proxy/bedrock_converse.py) — `src/sevn/proxy/bedrock_converse.py`
- [`aggregate_responses_sse`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`translate_chat_to_responses_request`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`translate_responses_sse_to_chat_stream`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`translate_responses_to_chat_completion`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`build_codex_request_headers`](src/sevn/proxy/codex_transport.py) — `src/sevn/proxy/codex_transport.py`
- [`codex_responses_url`](src/sevn/proxy/codex_transport.py) — `src/sevn/proxy/codex_transport.py`
- [`ProviderCredentialEntry`](src/sevn/proxy/credentials.py) — `src/sevn/proxy/credentials.py`
- [`ProviderCredentials`](src/sevn/proxy/credentials.py) — `src/sevn/proxy/credentials.py`
- _…and 23 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`normalize_anthropic_request_body`](src/sevn/proxy/anthropic_body.py) — `src/sevn/proxy/anthropic_body.py`
- [`create_app`](src/sevn/proxy/app.py) — `src/sevn/proxy/app.py`
- [`llm_post_auth_failure`](src/sevn/proxy/auth.py) — `src/sevn/proxy/auth.py`
- [`converse_via_bedrock`](src/sevn/proxy/bedrock_converse.py) — `src/sevn/proxy/bedrock_converse.py`
- [`aggregate_responses_sse`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`translate_chat_to_responses_request`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`translate_responses_sse_to_chat_stream`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`translate_responses_to_chat_completion`](src/sevn/proxy/codex_translation.py) — `src/sevn/proxy/codex_translation.py`
- [`build_codex_request_headers`](src/sevn/proxy/codex_transport.py) — `src/sevn/proxy/codex_transport.py`
- [`codex_responses_url`](src/sevn/proxy/codex_transport.py) — `src/sevn/proxy/codex_transport.py`
- [`ProviderCredentialEntry`](src/sevn/proxy/credentials.py) — `src/sevn/proxy/credentials.py`
- [`ProviderCredentials`](src/sevn/proxy/credentials.py) — `src/sevn/proxy/credentials.py`
- _…and 23 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/proxy`](src/sevn/proxy/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/proxy`](src/sevn/proxy/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

| Tests | Focus |
|-------|-------|
| `tests/proxy/test_codex_aggregation.py` | Truncated-stream retry; high-latency stage naming; slow-turn Still working… route |
| `tests/proxy/test_codex_aggregation_w1_red.py` | Turn-progress scheduler + MC stage-latency unwired log |

## Amendments (open-issues-sweep W24, #81)

The egress proxy ASGI app (`src/sevn/proxy/app.py`) applies the same
`IngressBodyLimitMiddleware` cap as the gateway (`DEFAULT_MAX_INGRESS_BODY_BYTES`).
`POST /llm/*` and other proxy ingress routes return **413** before upstream forward.

## Amendments (post-audit-0.0.1 W5 — #167)

Guarded route prefixes (`/llm/`, `/web/`, `/integration/`) return **503**
``{"detail":"proxy authentication not configured"}`` when
``proxy_shared_secret`` / ``SEVN_PROXY_SHARED_SECRET`` is unset. The only escape
is explicit ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1``, which logs a loud warning at
proxy boot and on every guarded request. Onboarding stores
``SEVN_PROXY_SHARED_SECRET`` in the workspace secrets chain; gateway and proxy
resolve it at boot (``resolve_proxy_shared_secret`` reads process env unchanged).

## Amendments (post-audit-0.0.1 W6 — #168)

Two credentials authenticate guarded proxy routes (D12):

| Header | Holder | Scope |
|--------|--------|-------|
| ``X-Sevn-Proxy-Token`` | Gateway → proxy | Long-lived ``SEVN_PROXY_SHARED_SECRET``; all guarded prefixes |
| ``X-Sevn-Session-Token`` | Sandbox / tool → proxy | Per-run HMAC token minted by ``mint_session_token``; ``sandbox`` scope covers ``/web/*`` and ``/integration``; ``llm`` scope covers ``/llm/*`` |

Session tokens carry ``exp`` (unix expiry) and ``run_id`` in a ``v1.<payload>.<sig>``
envelope signed with the same ``SEVN_PROXY_SHARED_SECRET``. Either header alone
satisfies the guard for its route family. The service secret is **never** injected
into sandbox child env (``build_sandbox_child_env``).

## Amendments (prod-readiness-0.0.1 W3 — C3.2, C3.3)

Exactly one configuration authority resolves ``SEVN_PROXY_SHARED_SECRET`` for
in-process gateway and proxy clients:

| Process | Authority |
|---------|-----------|
| Proxy | ``ProxySettings.proxy_shared_secret`` via env alias and/or secrets-chain merge in ``build_proxy_settings`` (``settings.model_copy`` only — **no** ``os.environ`` write-back) |
| Gateway | ``ProcessSettings.proxy_shared_secret`` (env allowlist) then secrets chain via ``resolve_proxy_shared_secret``; value is injected into ``build_runtime_tool_bindings(proxy_shared_secret=…)`` |

Guarded-route **clients** (``build_egress_web_headers``, web/integration callers) raise
``ProxySharedSecretUnconfiguredError`` when the resolved shared secret is empty,
naming ``SEVN_PROXY_SHARED_SECRET`` and a remedy (set env / ``sevn secrets put`` /
generate / onboard). They must not send an empty ``X-Sevn-Proxy-Token`` and surface
an opaque 401.

The sole remaining ``os.environ.get("SEVN_PROXY_SHARED_SECRET")`` under ``src/`` is
the sandbox child-env seam
(``data/bundled_skills/core/job-ops/scripts/lib/llm.py``), which runs out-of-process.

## Amendments (prod-readiness-0.0.1 W5 — C1.3, C1.4)

**Preflight (C1.3 / D38).** ``make compose-up`` (and browser/GUI wrappers via
``COMPOSE_FILES``) runs ``scripts/check_compose_operator_secrets.py`` before
``docker compose up``. The check rejects empty, placeholder (``change-me`` and
siblings), and below-minimum-length (<24) values for ``SEVN_PROXY_SHARED_SECRET``,
``SEVN_GATEWAY_TOKEN``, and ``SEVN_SECRETS_PASSPHRASE``. CI reaches the same
logic via ``make check-compose-operator-secrets`` (``--self-check``) in
``ci-infra`` / ``CI_STEPS``.

**W5.3 — generate-once interaction.** An unset/blank ``SEVN_PROXY_SHARED_SECRET``
is allowed at compose-up so ``sevn-operator-perms`` generate-once can satisfy the
gate; an *explicit* low-quality value still fails. Gateway token and secrets
passphrase remain mandatory high-entropy values.

**Authenticated healthcheck (C1.4 / D39).** ``sevn-proxy`` keeps ``GET /healthz``
as liveness and additionally probes guarded ``GET /web/auth-check`` with
``X-Sevn-Proxy-Token`` resolved from env or ``/operator/.sevn/proxy-shared-secret``.
HTTP **401** or **503** marks the container unhealthy. ``/web/auth-check`` is a
guarded no-op (no provider upstream) so the probe consumes no quota.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
