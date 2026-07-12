---
id: spec-04-tracing
kind: spec
title: Tracing — Spec
status: done
owner: Alex
summary: Provide durable trace sinks that implement TraceSink without ever throwing
  through emit, so instrumentation stays off the critical path. SQLite layout matches
  Mission Control query patterns (prd-07-mi
last_updated: '2026-06-19'
fingerprint: sha256:5507549dd5ddaa246c3504df95f3b8d5aa4eec051d2d9a5233febb695f6c9dce
related: []
sources:
- src/sevn/tracing/**
parent_prd: prd-07-mission-control
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
build_phase: null
interfaces:
- name: OtlpExportTarget
  file: src/sevn/tracing/otel_pipeline.py
  symbol: OtlpExportTarget
- name: configure_gateway_otel
  file: src/sevn/tracing/otel_pipeline.py
  symbol: configure_gateway_otel
- name: configure_gateway_otel_async
  file: src/sevn/tracing/otel_pipeline.py
  symbol: configure_gateway_otel_async
- name: configure_proxy_otel
  file: src/sevn/tracing/otel_pipeline.py
  symbol: configure_proxy_otel
- name: instrumentation_capability
  file: src/sevn/tracing/otel_pipeline.py
  symbol: instrumentation_capability
- name: is_otel_export_configured
  file: src/sevn/tracing/otel_pipeline.py
  symbol: is_otel_export_configured
- name: reset_otel_pipeline_for_tests
  file: src/sevn/tracing/otel_pipeline.py
  symbol: reset_otel_pipeline_for_tests
- name: resolve_otlp_targets
  file: src/sevn/tracing/otel_pipeline.py
  symbol: resolve_otlp_targets
- name: resolve_trace_sink_token
  file: src/sevn/tracing/trace_secrets_resolve.py
  symbol: resolve_trace_sink_token
specs: []
personas: []
---

## Purpose

Offline scaffold for Tracing — Spec (spec-04-tracing) — Purpose.

## Public Interface

Offline scaffold for Tracing — Spec (spec-04-tracing) — Public Interface.

## Data Model

Offline scaffold for Tracing — Spec (spec-04-tracing) — Data Model.

## Internal Architecture

Offline scaffold for Tracing — Spec (spec-04-tracing) — Internal Architecture.

## Behavior

Offline scaffold for Tracing — Spec (spec-04-tracing) — Behavior.

## Failure Modes

Offline scaffold for Tracing — Spec (spec-04-tracing) — Failure Modes.

## Amendments (spec-36-sub-agents)

Each sub-agent run emits OTel span `sevn.subagent` (attrs: id/level/role/specialist/parent)
child of the spawning span (`src/sevn/agent/tracing/subagent_trace.py`). Mission
telemetry kinds `subagent_spawned` / `subagent_finished` / `subagent_killed` and
Prometheus `sevn_subagents_running` / `sevn_subagents_total` counters (D12).

## Test Strategy

Offline scaffold for Tracing — Spec (spec-04-tracing) — Test Strategy.
