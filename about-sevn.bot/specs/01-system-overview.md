---
id: spec-01-system-overview
kind: spec
title: System overview — Spec
status: done
owner: Alex
summary: 'Give implementers a single picture of the runtime before feature work: package
  boundaries under src/sevn/, allowed import directions, and the shared protocols
  that keep LLM wiring, observability, and '
last_updated: '2026-07-16'
fingerprint: sha256:84db51f7b25869527cf3bb0122a24a1cc7165a3d3f872469bb447948d253089b
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

Give implementers a single picture of the runtime before feature work: package
boundaries under `src/sevn/`, allowed import directions, and the shared turn spine
(gateway → triager → tier executors). This spec complements spec-00-foundation
(build/CI) with **architectural layering** enforced by import-linter and indexed
in `about-sevn.bot/ARCHITECTURE.md`.

## Public Interface

| Layer | Primary modules | Responsibility |
|-------|-----------------|----------------|
| Gateway | `src/sevn/gateway/` | HTTP server, session queue, turn dispatch, channel routing |
| Triager | `src/sevn/agent/triager/` | Tier-A routing brain (`TriageResult`) |
| Tier B | `src/sevn/agent/executors/b_harness.py` | Pydantic-AI tool loop |
| Tier C/D | `src/sevn/agent/executors/cd_harness.py` | Lambda-RLM / planner backend |
| Channels | `src/sevn/channels/` | Telegram, webchat adapters |
| Tools / skills | `src/sevn/tools/`, `src/sevn/skills/` | Registry, file ops, bundled skills |
| Config | `src/sevn/config/` | `sevn.json` load + `WorkspaceConfig` |

Import contracts: `make lint-imports` (see **Data Model**).

## Data Model

### Import-layer contracts (`pyproject.toml` `[tool.importlinter]`)

| Contract | Rule |
|----------|------|
| Channels isolation | `sevn.channels` must not import `sevn.tools` or `sevn.skills` |
| Proxy leaf | `sevn.proxy` must not import `sevn.agent`, `sevn.gateway`, `sevn.channels` |
| Skills/tools independence | `sevn.skills` must not import `sevn.tools` |
| Tools/skills ↔ channels | `sevn.tools` / `sevn.skills` must not import `sevn.channels` (baselined outbound exceptions) |

### Turn-spine flow

```text
IncomingMessage → ChannelRouter → SessionManager.enqueue_dispatch
    → build_agent_run_turn → triage_turn (or passthrough)
    → tier A | tier B run_b_turn | tier C/D run_cd_turn → OutgoingMessage
```

Shared types: `TriageResult` (spec-10), `BTurnOutcome`, `SessionRow`, `ToolSet`.

## Internal Architecture

Forty top-level packages under `src/sevn/`. CLI entry: `sevn.cli.app:main`.
Long-lived runtime: gateway process (spec-17).

Agent read order (`about-sevn.bot/ARCHITECTURE.md`):

1. Architecture index → specs index → graphify (when present)
2. Source via tier-B tools under workspace `source_code/` mirror
3. Writes only under `workspace/.sevn/code-worktrees/<issue-id>/`

## Behavior

1. **Boot** — gateway loads config, storage, channels; wires `build_agent_run_turn`.
2. **Ingress** — adapters normalize to `IncomingMessage`; scanner/rate limits pre-enqueue.
3. **Dispatch** — one active turn per session; queue modes: cancel, steer, queue, multi.
4. **Egress** — `ChannelRouter` delivers outbound with streaming and routing footers.
5. **Cross-cutting** — OTel spans; section-specific config reload (spec-02).

## Failure Modes

| Failure | Effect |
|---------|--------|
| Import-layer violation | `make lint-imports` fails CI |
| Missing session / empty text | Turn aborts early in `agent_turn` |
| Triager unavailable | Routing-unavailable user message (spec-13) |
| Unhandled turn exception | Catch-all fallback in `_run_guarded` (spec-17) |

## Test Strategy

| Area | Tests |
|------|-------|
| Gateway | `tests/gateway/test_agent_turn_*.py`, `test_session_manager.py` |
| Triager | `tests/agent/test_triager_*.py` |
| Tier B | `tests/agent/test_b_harness*.py`, `test_tier_b_*.py` |
| Import contracts | `make lint-imports` |
| Docs gates | `make about-docs-check`, `make agent-context-manifest-check` |

Host E2E: `make telegram-e2e` (not in Docker gateway).
