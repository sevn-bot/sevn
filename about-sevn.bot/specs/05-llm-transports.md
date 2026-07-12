---
id: spec-05-llm-transports
kind: spec
title: LLM transports — Spec
status: done
owner: Alex
summary: Normalize provider-shaped JSON over async HTTP to a single egress base URL
  (SEVN_PROXY_URL / ProcessSettings.proxy_url), so tier executors bind once per turn
  and never touch raw secrets. LiteLLM may r
last_updated: '2026-07-07'
fingerprint: sha256:9465260ed67219a5e1a5b5b4b554e76d0442bbaf53217506002b32769a55fd10
related: []
sources:
- src/sevn/proxy/**
parent_prd: prd-05-cost-and-providers
depends_on:
- spec-00-foundation
- spec-02-config-and-workspace
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
specs: []
personas: []
---

## Purpose

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Purpose.

## Public Interface

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Public Interface.

## Data Model

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Data Model.

## Internal Architecture

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Internal Architecture.

## Behavior

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Behavior.

## Failure Modes

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Failure Modes.

## Test Strategy

Offline scaffold for LLM transports — Spec (spec-05-llm-transports) — Test Strategy.
