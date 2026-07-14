---
id: spec-37-openui
kind: spec
title: OpenUI — Spec
status: scaffold
owner: Alex
summary: 'Deliver OpenUI: explicit openui_render tool calls produce sanitised, CSP-wrapped,
  size-capped HTML (live or rasterised) and deterministic form callbacks that rejoin
  the same executor turn for tier B /'
last_updated: '2026-07-12'
fingerprint: sha256:bea823d693563b387c0227a26e81a81491fb872ae79aaa1e5fab82ed888727f7
related: []
sources:
- src/sevn/ui/openui/**
parent_prd: prd-10-generated-ui
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
- spec-04-tracing
- spec-06-secrets
- spec-09-security-scanner
- spec-11-tools-registry
- spec-13-rlm-triager
- spec-14-executor-tier-b
- spec-16-harness-discipline
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-21-executor-tier-cd
- spec-24-dashboard
build_phase: null
interfaces:
- name: OpenUIBridge
  file: src/sevn/ui/openui/bridge.py
  symbol: OpenUIBridge
- name: build_content_security_policy
  file: src/sevn/ui/openui/bridge.py
  symbol: build_content_security_policy
- name: inject_submit_token_into_html
  file: src/sevn/ui/openui/bridge.py
  symbol: inject_submit_token_into_html
- name: build_openui_dispatch_payload
  file: src/sevn/ui/openui/callback.py
  symbol: build_openui_dispatch_payload
- name: normalize_webchat_openui_callback
  file: src/sevn/ui/openui/callback.py
  symbol: normalize_webchat_openui_callback
- name: parse_query_dict
  file: src/sevn/ui/openui/callback.py
  symbol: parse_query_dict
- name: build_openui_payload
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: build_openui_payload
- name: cards_fallback_text
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: cards_fallback_text
- name: compose_cards_html
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: compose_cards_html
- name: compose_table_html
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: compose_table_html
- name: escape_html
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: escape_html
- name: parse_json_list
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: parse_json_list
- name: table_fallback_text
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: table_fallback_text
- name: build_openui_delivery_metadata
  file: src/sevn/ui/openui/delivery.py
  symbol: build_openui_delivery_metadata
- name: build_telegram_openui_inline_keyboard
  file: src/sevn/ui/openui/delivery.py
  symbol: build_telegram_openui_inline_keyboard
- name: Drop
  file: src/sevn/ui/openui/models.py
  symbol: Drop
- name: OpenUIConfig
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIConfig
- name: OpenUIRenderError
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIRenderError
- name: OpenUIRenderResult
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIRenderResult
- name: OpenUIRuntimeDeps
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIRuntimeDeps
- name: RasteriseCaps
  file: src/sevn/ui/openui/models.py
  symbol: RasteriseCaps
- name: SanitiseResult
  file: src/sevn/ui/openui/models.py
  symbol: SanitiseResult
- name: effective_openui_config
  file: src/sevn/ui/openui/models.py
  symbol: effective_openui_config
- name: rasterise_pdf_bytes
  file: src/sevn/ui/openui/rasteriser.py
  symbol: rasterise_pdf_bytes
- name: rasterise_png_bytes
  file: src/sevn/ui/openui/rasteriser.py
  symbol: rasterise_png_bytes
- name: sanitise
  file: src/sevn/ui/openui/sanitiser.py
  symbol: sanitise
- name: OpenUIRecord
  file: src/sevn/ui/openui/store.py
  symbol: OpenUIRecord
- name: OpenUIStore
  file: src/sevn/ui/openui/store.py
  symbol: OpenUIStore
- name: sign_token
  file: src/sevn/ui/openui/tokens.py
  symbol: sign_token
- name: verify_token
  file: src/sevn/ui/openui/tokens.py
  symbol: verify_token
- name: verify_token_status
  file: src/sevn/ui/openui/tokens.py
  symbol: verify_token_status
- name: openui_render
  file: src/sevn/ui/openui/tools_register.py
  symbol: openui_render
- name: register_openui_tools
  file: src/sevn/ui/openui/tools_register.py
  symbol: register_openui_tools
specs: []
personas: []
prd_profile: null
---


## Purpose

Deliver OpenUI: explicit openui_render tool calls produce sanitised, CSP-wrapped, size-capped HTML (live or rasterised) and deterministic form callbacks that rejoin the same executor turn for tier B /

Primary code trees: [`src/sevn/ui/openui`](src/sevn/ui/openui/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`OpenUIBridge`](src/sevn/ui/openui/bridge.py) — `src/sevn/ui/openui/bridge.py`
- [`build_content_security_policy`](src/sevn/ui/openui/bridge.py) — `src/sevn/ui/openui/bridge.py`
- [`inject_submit_token_into_html`](src/sevn/ui/openui/bridge.py) — `src/sevn/ui/openui/bridge.py`
- [`build_openui_dispatch_payload`](src/sevn/ui/openui/callback.py) — `src/sevn/ui/openui/callback.py`
- [`normalize_webchat_openui_callback`](src/sevn/ui/openui/callback.py) — `src/sevn/ui/openui/callback.py`
- [`parse_query_dict`](src/sevn/ui/openui/callback.py) — `src/sevn/ui/openui/callback.py`
- [`build_openui_payload`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`cards_fallback_text`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`compose_cards_html`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`compose_table_html`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`escape_html`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`parse_json_list`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- _…and 21 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`OpenUIBridge`](src/sevn/ui/openui/bridge.py) — `src/sevn/ui/openui/bridge.py`
- [`build_content_security_policy`](src/sevn/ui/openui/bridge.py) — `src/sevn/ui/openui/bridge.py`
- [`inject_submit_token_into_html`](src/sevn/ui/openui/bridge.py) — `src/sevn/ui/openui/bridge.py`
- [`build_openui_dispatch_payload`](src/sevn/ui/openui/callback.py) — `src/sevn/ui/openui/callback.py`
- [`normalize_webchat_openui_callback`](src/sevn/ui/openui/callback.py) — `src/sevn/ui/openui/callback.py`
- [`parse_query_dict`](src/sevn/ui/openui/callback.py) — `src/sevn/ui/openui/callback.py`
- [`build_openui_payload`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`cards_fallback_text`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`compose_cards_html`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`compose_table_html`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`escape_html`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- [`parse_json_list`](src/sevn/ui/openui/canvas_compose.py) — `src/sevn/ui/openui/canvas_compose.py`
- _…and 21 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/ui/openui`](src/sevn/ui/openui/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/ui/openui`](src/sevn/ui/openui/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
