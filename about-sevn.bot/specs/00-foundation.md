---
id: spec-00-foundation
kind: spec
title: Foundation — Spec
status: scaffold
owner: Alex
summary: 'Deliver the lowest layer every later spec assumes: a src/sevn/ package layout,
  uv-managed Python 3.12+ project (hatchling build backend), a root Makefile as the
  single recurring-command surface, pre-c'
last_updated: '2026-07-14'
fingerprint: sha256:bc2cb848e0ec03e511ef428ab1e6e967859ef90e25cc5718837adefec83f5d36
related: []
sources:
- src/sevn/__init__.py
parent_prd: prd-00-main
build_phase: null
---

## Purpose

Deliver the lowest layer every later spec assumes: a src/sevn/ package layout, uv-managed Python 3.12+ project (hatchling build backend), a root Makefile as the single recurring-command surface, pre-c

Implementation spans [`src/sevn`](src/sevn/__init__.py). The frontmatter `interfaces:` block is code-owned (refresh with `make about-docs-extract DOC_ID=spec-00-foundation`).

<!-- HUMAN-INPUT[owner=operator]: Author the full normative contract for this mega-spec — do not hand-expand the whole-tree interfaces dump. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`default_codemode_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`install_monty_resource_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`lambda_rlm_filter`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`to_dspy_tools`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`EgressBridgeContext`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_anthropic_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_httpx_event_hooks`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_openai_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_httpx_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_llm_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_proxy_transport_request`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`resolve_proxy_shared_secret`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- _…and 3973 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`default_codemode_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`install_monty_resource_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`lambda_rlm_filter`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`to_dspy_tools`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`EgressBridgeContext`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_anthropic_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_httpx_event_hooks`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_openai_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_httpx_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_llm_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_proxy_transport_request`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`resolve_proxy_shared_secret`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- _…and 3973 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn`](src/sevn/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn`](src/sevn/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
