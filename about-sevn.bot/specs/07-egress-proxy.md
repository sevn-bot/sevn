---
id: spec-07-egress-proxy
kind: spec
title: Egress proxy — Spec
status: scaffold
owner: Alex
summary: Product pairing (v1). Deployment, paired daemon install, onboarding validation,
  and Mission Control management of the proxy are specified in prd-06-setup-and-operations
  and prd-07-mission-control §5.1
last_updated: '2026-07-21'
fingerprint: sha256:a2ad0d78b19ea74ccf88285824347327b48f3d7f88fd12bfa6dd108099244e81
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
- name: converse_via_bedrock
  file: src/sevn/proxy/bedrock_converse.py
  symbol: converse_via_bedrock
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

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
