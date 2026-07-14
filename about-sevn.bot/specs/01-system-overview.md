---
id: spec-01-system-overview
kind: spec
title: System overview — Spec
status: scaffold
owner: Alex
summary: 'Give implementers a single picture of the runtime before feature work: package
  boundaries under src/sevn/, allowed import directions, and the shared protocols
  that keep LLM wiring, observability, and '
last_updated: '2026-07-14'
fingerprint: sha256:4cc956fe3cf76232d6c513685c57f54a2856bab4c9cf06a15fdce30a4475eebb
related: []
sources:
- src/sevn/**/__init__.py
parent_prd: prd-00-main
depends_on:
- spec-00-foundation
build_phase: null
interfaces:
- name: format_section_plain
  file: src/sevn/cli/config_sections/__init__.py
  symbol: format_section_plain
- name: nested_get
  file: src/sevn/cli/config_sections/__init__.py
  symbol: nested_get
- name: section_payload
  file: src/sevn/cli/config_sections/__init__.py
  symbol: section_payload
- name: load_log_viewer_app
  file: src/sevn/cli/tui/__init__.py
  symbol: load_log_viewer_app
- name: load_section_picker_app
  file: src/sevn/cli/tui/__init__.py
  symbol: load_section_picker_app
- name: textual_ui_allowed
  file: src/sevn/cli/tui/__init__.py
  symbol: textual_ui_allowed
- name: StubExecutor
  file: src/sevn/coding_agents/executors/__init__.py
  symbol: StubExecutor
- name: build_executor
  file: src/sevn/coding_agents/executors/__init__.py
  symbol: build_executor
- name: legacy_native_second_brain_ingest_stub_enabled
  file: src/sevn/second_brain/__init__.py
  symbol: legacy_native_second_brain_ingest_stub_enabled
- name: register_second_brain_tools
  file: src/sevn/second_brain/__init__.py
  symbol: register_second_brain_tools
- name: second_brain_ingest_stub_tool
  file: src/sevn/second_brain/__init__.py
  symbol: second_brain_ingest_stub_tool
- name: second_brain_query_tool
  file: src/sevn/second_brain/__init__.py
  symbol: second_brain_query_tool
- name: wiki_apply_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_apply_tool
- name: wiki_get_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_get_tool
- name: wiki_lint_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_lint_tool
- name: wiki_search_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_search_tool
- name: ImproveJobResult
  file: src/sevn/self_improve/eval/__init__.py
  symbol: ImproveJobResult
- name: eval_docker_required
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_docker_required
- name: eval_in_process_override
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_in_process_override
- name: eval_report_passed
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_report_passed
- name: golden_routing_fixture_path
  file: src/sevn/self_improve/eval/__init__.py
  symbol: golden_routing_fixture_path
- name: resolve_repo_root
  file: src/sevn/self_improve/eval/__init__.py
  symbol: resolve_repo_root
- name: run_docker_eval_graph
  file: src/sevn/self_improve/eval/__init__.py
  symbol: run_docker_eval_graph
- name: run_eval_graph
  file: src/sevn/self_improve/eval/__init__.py
  symbol: run_eval_graph
- name: insert_feedback_event
  file: src/sevn/self_improve/feedback/__init__.py
  symbol: insert_feedback_event
- name: mirror_structured_feedback_to_events
  file: src/sevn/self_improve/feedback/__init__.py
  symbol: mirror_structured_feedback_to_events
- name: Lesson
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: Lesson
- name: emit_recall_audit
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: emit_recall_audit
- name: recall_lessons
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: recall_lessons
- name: reject_patch_diff
  file: src/sevn/self_improve/proposer/__init__.py
  symbol: reject_patch_diff
- name: ShortlistCandidate
  file: src/sevn/self_improve/sampler/__init__.py
  symbol: ShortlistCandidate
- name: allocate_shortlist
  file: src/sevn/self_improve/sampler/__init__.py
  symbol: allocate_shortlist
- name: TrajectoryTurn
  file: src/sevn/self_improve/trajectories/__init__.py
  symbol: TrajectoryTurn
- name: stable_turn_id
  file: src/sevn/self_improve/trajectories/__init__.py
  symbol: stable_turn_id
- name: register_file_ops_tools
  file: src/sevn/tools/file_ops/__init__.py
  symbol: register_file_ops_tools
- name: register_dashboard_routes
  file: src/sevn/ui/dashboard/__init__.py
  symbol: register_dashboard_routes
- name: create_dashboard_api_router
  file: src/sevn/ui/dashboard/api/__init__.py
  symbol: create_dashboard_api_router
- name: register_shared_ui_routes
  file: src/sevn/ui/shared/__init__.py
  symbol: register_shared_ui_routes
- name: serve_shared_ui_asset
  file: src/sevn/ui/shared/__init__.py
  symbol: serve_shared_ui_asset
- name: serve_style_asset
  file: src/sevn/ui/style/__init__.py
  symbol: serve_style_asset
---

## Purpose

Give implementers a single picture of the runtime before feature work: package boundaries under src/sevn/, allowed import directions, and the shared protocols that keep LLM wiring, observability, and

Implementation spans [`src/sevn`](src/sevn/__init__.py). The frontmatter `interfaces:` block is code-owned (refresh with `make about-docs-extract DOC_ID=spec-01-system-overview`).

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
