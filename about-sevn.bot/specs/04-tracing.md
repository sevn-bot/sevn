---
id: spec-04-tracing
kind: spec
title: Tracing — Spec
status: scaffold
owner: Alex
summary: Provide durable trace sinks that implement TraceSink without ever throwing
  through emit, so instrumentation stays off the critical path. SQLite layout matches
  Mission Control query patterns (prd-07-mi
last_updated: '2026-07-19'
fingerprint: sha256:91152ca49d6747fc3349e041d9bd35c78365c0791ad351de90680fb9f24e8ff4
related: []
sources:
- src/sevn/agent/tracing/**
parent_prd: prd-07-mission-control
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
build_phase: null
interfaces:
- name: build_tier_b_context_attrs
  file: src/sevn/agent/tracing/agent_context.py
  symbol: build_tier_b_context_attrs
- name: build_triager_context_attrs
  file: src/sevn/agent/tracing/agent_context.py
  symbol: build_triager_context_attrs
- name: emit_context_span
  file: src/sevn/agent/tracing/agent_context.py
  symbol: emit_context_span
- name: serialize_message_history_for_trace
  file: src/sevn/agent/tracing/agent_context.py
  symbol: serialize_message_history_for_trace
- name: serialize_user_prompt_for_trace
  file: src/sevn/agent/tracing/agent_context.py
  symbol: serialize_user_prompt_for_trace
- name: trace_text_field
  file: src/sevn/agent/tracing/agent_context.py
  symbol: trace_text_field
- name: json_safe_trace_attrs
  file: src/sevn/agent/tracing/attrs.py
  symbol: json_safe_trace_attrs
- name: json_safe_trace_value
  file: src/sevn/agent/tracing/attrs.py
  symbol: json_safe_trace_value
- name: trace_tool_result_value
  file: src/sevn/agent/tracing/attrs.py
  symbol: trace_tool_result_value
- name: register_trace_subscriber
  file: src/sevn/agent/tracing/emit.py
  symbol: register_trace_subscriber
- name: reset_trace_subscribers_for_tests
  file: src/sevn/agent/tracing/emit.py
  symbol: reset_trace_subscribers_for_tests
- name: unregister_trace_subscriber
  file: src/sevn/agent/tracing/emit.py
  symbol: unregister_trace_subscriber
- name: wrap_trace_sink
  file: src/sevn/agent/tracing/emit.py
  symbol: wrap_trace_sink
- name: LogfireExportStatus
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: LogfireExportStatus
- name: apply_logfire_export_to_sevn_doc
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: apply_logfire_export_to_sevn_doc
- name: logfire_export_status
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: logfire_export_status
- name: logfire_export_status_from_doc
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: logfire_export_status_from_doc
- name: logfire_sink_entry_for_tests
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: logfire_sink_entry_for_tests
- name: MultiSink
  file: src/sevn/agent/tracing/multi_sink.py
  symbol: MultiSink
- name: OTelExporterSink
  file: src/sevn/agent/tracing/otel_sink.py
  symbol: OTelExporterSink
- name: emit_provider_call
  file: src/sevn/agent/tracing/provider_call.py
  symbol: emit_provider_call
- name: RedactingSink
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: RedactingSink
- name: TraceRedactionPolicy
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: TraceRedactionPolicy
- name: redact
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: redact
- name: redact_attrs
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: redact_attrs
- name: apply_trace_redaction_to_sevn_doc
  file: src/sevn/agent/tracing/redaction_config.py
  symbol: apply_trace_redaction_to_sevn_doc
- name: effective_trace_redaction_enabled_from_doc
  file: src/sevn/agent/tracing/redaction_config.py
  symbol: effective_trace_redaction_enabled_from_doc
- name: RotatingJSONLFileSink
  file: src/sevn/agent/tracing/rotating_jsonl_sink.py
  symbol: RotatingJSONLFileSink
- name: JSONLFileSink
  file: src/sevn/agent/tracing/sink.py
  symbol: JSONLFileSink
- name: NullTraceSink
  file: src/sevn/agent/tracing/sink.py
  symbol: NullTraceSink
- name: TraceEvent
  file: src/sevn/agent/tracing/sink.py
  symbol: TraceEvent
- name: TraceSink
  file: src/sevn/agent/tracing/sink.py
  symbol: TraceSink
- name: checkpoint_snapshot
  file: src/sevn/agent/tracing/sink.py
  symbol: checkpoint_snapshot
- name: current_sink
  file: src/sevn/agent/tracing/sink.py
  symbol: current_sink
- name: trace_sink_scope
  file: src/sevn/agent/tracing/sink.py
  symbol: trace_sink_scope
- name: build_gateway_trace_sink
  file: src/sevn/agent/tracing/sink_factory.py
  symbol: build_gateway_trace_sink
- name: build_gateway_trace_sink_async
  file: src/sevn/agent/tracing/sink_factory.py
  symbol: build_gateway_trace_sink_async
- name: trace_redaction_policy_for
  file: src/sevn/agent/tracing/sink_factory.py
  symbol: trace_redaction_policy_for
- name: SQLiteSink
  file: src/sevn/agent/tracing/sqlite_sink.py
  symbol: SQLiteSink
- name: cap_attrs_json
  file: src/sevn/agent/tracing/sqlite_sink.py
  symbol: cap_attrs_json
- name: redact_trace_attrs
  file: src/sevn/agent/tracing/sqlite_sink.py
  symbol: redact_trace_attrs
- name: SubAgentPrometheusCounts
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: SubAgentPrometheusCounts
- name: SubAgentTraceEmitter
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: SubAgentTraceEmitter
- name: bind_subagent_turn_context
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: bind_subagent_turn_context
- name: build_subagent_trace_hook
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: build_subagent_trace_hook
- name: reset_subagent_trace_for_tests
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: reset_subagent_trace_for_tests
- name: reset_subagent_turn_context
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: reset_subagent_turn_context
- name: subagent_trace_scope
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: subagent_trace_scope
- name: TraceEventOtelBridge
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: TraceEventOtelBridge
- name: attach_turn_trace_context
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: attach_turn_trace_context
- name: get_trace_event_bridge
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: get_trace_event_bridge
- name: set_trace_event_bridge
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: set_trace_event_bridge
- name: purge_trace_events_ttl
  file: src/sevn/agent/tracing/traces_maintenance.py
  symbol: purge_trace_events_ttl
- name: write_hourly_rollups
  file: src/sevn/agent/tracing/traces_maintenance.py
  symbol: write_hourly_rollups
- name: apply_traces_migrations
  file: src/sevn/agent/tracing/traces_migrate.py
  symbol: apply_traces_migrations
- name: ensure_trace_connection
  file: src/sevn/agent/tracing/traces_migrate.py
  symbol: ensure_trace_connection
- name: ensure_traces_db
  file: src/sevn/agent/tracing/traces_migrate.py
  symbol: ensure_traces_db
---

## Purpose

Provide durable trace sinks that implement TraceSink without ever throwing through emit, so instrumentation stays off the critical path. SQLite layout matches Mission Control query patterns (prd-07-mi

Primary code trees: [`src/sevn/tracing`](src/sevn/tracing/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`OtlpExportTarget`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_gateway_otel`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_gateway_otel_async`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_proxy_otel`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`instrumentation_capability`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`is_otel_export_configured`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`reset_otel_pipeline_for_tests`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`resolve_otlp_targets`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`resolve_trace_sink_token`](src/sevn/tracing/trace_secrets_resolve.py) — `src/sevn/tracing/trace_secrets_resolve.py`
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`OtlpExportTarget`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_gateway_otel`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_gateway_otel_async`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_proxy_otel`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`instrumentation_capability`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`is_otel_export_configured`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`reset_otel_pipeline_for_tests`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`resolve_otlp_targets`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`resolve_trace_sink_token`](src/sevn/tracing/trace_secrets_resolve.py) — `src/sevn/tracing/trace_secrets_resolve.py`
## Internal Architecture

See **Implemented by** and [`src/sevn/tracing`](src/sevn/tracing/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/tracing`](src/sevn/tracing/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Amendments (spec-36-sub-agents)

Each sub-agent run emits OTel span `sevn.subagent` (attrs: id/level/role/specialist/parent)
child of the spawning span (`src/sevn/agent/tracing/subagent_trace.py`). Mission
telemetry kinds `subagent_spawned` / `subagent_finished` / `subagent_killed` and
Prometheus `sevn_subagents_running` / `sevn_subagents_total` counters (D12).

## Implemented by

- [`OtlpExportTarget`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_gateway_otel`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_gateway_otel_async`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`configure_proxy_otel`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`instrumentation_capability`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`is_otel_export_configured`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`reset_otel_pipeline_for_tests`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`resolve_otlp_targets`](src/sevn/tracing/otel_pipeline.py) — `src/sevn/tracing/otel_pipeline.py`
- [`resolve_trace_sink_token`](src/sevn/tracing/trace_secrets_resolve.py) — `src/sevn/tracing/trace_secrets_resolve.py`

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
