<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint tracing` -->
# Tracing — TraceSink JSONL/SQLite sinks, OTLP export bridge, and trace maintenance

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** TraceSink JSONL/SQLite sinks, OTLP export bridge, and trace maintenance.

## Level 1 — Overview (non-technical)

**Tracing** records what sevn did on each turn — triage decisions, tool calls, provider latency, voice events — so you can debug in Mission Control or on disk. Events land in **JSONL files** and/or a **SQLite** `traces.db` under `.sevn/traces/`. Optional **OTLP export** sends spans to Logfire or any OpenTelemetry collector.

Instrumentation follows an **emit-never-throws** rule: a broken sink must never crash a live chat turn. Redaction strips sensitive keys before persistence when enabled.

## Level 2 — How it works (technical)

Implementation spans [`src/sevn/agent/tracing/`](../../src/sevn/agent/tracing/) (runtime sinks, factory) and [`src/sevn/tracing/`](../../src/sevn/tracing/) (OTLP pipeline helpers).

### Sink fan-out

[`build_gateway_trace_sink`](../../src/sevn/agent/tracing/sink_factory.py) reads `sevn.json` → `tracing.sinks[]` and builds a composite sink:

| `sink_type` | Built by `_sink_from_entry` | Notes |
| --- | --- | --- |
| `jsonl_file` | [`JSONLFileSink`](../../src/sevn/agent/tracing/sink.py) / [`RotatingJSONLFileSink`](../../src/sevn/agent/tracing/rotating_jsonl_sink.py) | Real persistence |
| `sqlite` | [`SQLiteSink`](../../src/sevn/agent/tracing/sqlite_sink.py) | `traces.db` queries in MC |
| `logfire` | **`None`** (skipped as leaf) | Token resolved async; export via OTLP bridge |
| `otel` | **`None`** (skipped as leaf) | Same — not a factory peer sink |

Multiple local sinks compose via [`MultiSink`](../../src/sevn/agent/tracing/multi_sink.py); see [`_sink_from_entry`](../../src/sevn/agent/tracing/sink_factory.py#L223) lines 261–263 for the logfire/otel skip.

### OTLP bridge (Logfire / OpenTelemetry)

[`configure_gateway_otel`](../../src/sevn/tracing/otel_pipeline.py#L277) installs a global `TracerProvider` at gateway boot (sync + async [`configure_gateway_otel_async`](../../src/sevn/tracing/otel_pipeline.py#L400) with secret-resolved bearer tokens). [`TraceEventOtelBridge`](../../src/sevn/agent/tracing/trace_event_bridge.py) translates in-process `TraceEvent` rows into OTel spans — it always participates in the composite even when logfire/otel sink entries return `None` from the factory.

Logfire operator toggles: [`logfire_config.py`](../../src/sevn/agent/tracing/logfire_config.py) (`apply_logfire_export_to_sevn_doc`, etc.).

### Emit never throws

In [`sink.py`](../../src/sevn/agent/tracing/sink.py), [`TraceSink.emit`](../../src/sevn/agent/tracing/sink.py#L135) implementations swallow I/O errors; [`redacting_sink.py`](../../src/sevn/agent/tracing/redacting_sink.py) [`RedactingSink`](../../src/sevn/agent/tracing/redacting_sink.py) wraps the composite once via [`_wrap_with_redaction`](../../src/sevn/agent/tracing/sink_factory.py#L78) in [`sink_factory.py`](../../src/sevn/agent/tracing/sink_factory.py). Subscribers hook through [`emit.py`](../../src/sevn/agent/tracing/emit.py) [`register_trace_subscriber`](../../src/sevn/agent/tracing/emit.py#L27).

### Configuration (`sevn.json` → `tracing`)

- `sinks[]` — `{ sink_type, path?, token_ref? }` entries
- `redaction.enabled`, `deny_keys`, `deny_value_patterns`
- Maintenance CLI: `sevn traces …` (see spec)

Validate: `sevn config validate`.

### Key modules

- [`sink_factory.py`](../../src/sevn/agent/tracing/sink_factory.py) — [`build_gateway_trace_sink`](../../src/sevn/agent/tracing/sink_factory.py), [`configure_gateway_otel`](../../src/sevn/tracing/otel_pipeline.py#L277) call site
- [`otel_pipeline.py`](../../src/sevn/tracing/otel_pipeline.py) — [`configure_gateway_otel`](../../src/sevn/tracing/otel_pipeline.py#L277)
- [`sink.py`](../../src/sevn/agent/tracing/sink.py) — `TraceSink` protocol, `NullTraceSink`
- [`sqlite_sink.py`](../../src/sevn/agent/tracing/sqlite_sink.py) — MC trace queries
- [`redacting_sink.py`](../../src/sevn/agent/tracing/redacting_sink.py) — deny-key policy

Normative spec: [`about-sevn.bot/specs/04-tracing.md`](../../about-sevn.bot/specs/04-tracing.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/tracing`](../../src/sevn/tracing/) and [`src/sevn/agent/tracing`](../../src/sevn/agent/tracing/) (23 Python files). Normative design: `about-sevn.bot/specs/04-tracing.md`.

### Module inventory

Tracing and telemetry hooks.

Working with [`__init__.py`](../../src/sevn/agent/tracing/__init__.py): inspect the public entry points below.

Structured agent-context snapshots for trace export (about-sevn.bot/specs/04-tracing.md).

Working with [`agent_context.py`](../../src/sevn/agent/tracing/agent_context.py): inspect the public entry points below.
Start with [`trace_text_field`](../../src/sevn/agent/tracing/agent_context.py#L38), then [`serialize_message_history_for_trace`](../../src/sevn/agent/tracing/agent_context.py#L92), [`serialize_user_prompt_for_trace`](../../src/sevn/agent/tracing/agent_context.py#L155), [`build_triager_context_attrs`](../../src/sevn/agent/tracing/agent_context.py#L184).

Trace attrs normalization (about-sevn.bot/specs/04-tracing.md §7).

Working with [`attrs.py`](../../src/sevn/agent/tracing/attrs.py): inspect the public entry points below.
Start with [`json_safe_trace_value`](../../src/sevn/agent/tracing/attrs.py#L21), then [`json_safe_trace_attrs`](../../src/sevn/agent/tracing/attrs.py#L47), [`trace_tool_result_value`](../../src/sevn/agent/tracing/attrs.py#L63).

In-process trace fan-out before persistence (about-sevn.bot/specs/04-tracing.md §2).

Working with [`emit.py`](../../src/sevn/agent/tracing/emit.py): inspect the public entry points below.
Start with [`register_trace_subscriber`](../../src/sevn/agent/tracing/emit.py#L27), then [`unregister_trace_subscriber`](../../src/sevn/agent/tracing/emit.py#L40), [`wrap_trace_sink`](../../src/sevn/agent/tracing/emit.py#L119), [`reset_trace_subscribers_for_tests`](../../src/sevn/agent/tracing/emit.py#L136).

Logfire trace export helpers for operator toggles (about-sevn.bot/specs/04-tracing.md).

Working with [`logfire_config.py`](../../src/sevn/agent/tracing/logfire_config.py): inspect the public entry points below.
Start with [`logfire_export_status_from_doc`](../../src/sevn/agent/tracing/logfire_config.py#L65), then [`logfire_export_status`](../../src/sevn/agent/tracing/logfire_config.py#L107), [`apply_logfire_export_to_sevn_doc`](../../src/sevn/agent/tracing/logfire_config.py#L197), [`logfire_sink_entry_for_tests`](../../src/sevn/agent/tracing/logfire_config.py#L245).

Compose multiple TraceSink instances (about-sevn.bot/specs/04-tracing.md §2).

Working with [`multi_sink.py`](../../src/sevn/agent/tracing/multi_sink.py): inspect the public entry points below.
Start with [`MultiSink.emit`](../../src/sevn/agent/tracing/multi_sink.py#L54), then [`MultiSink.flush`](../../src/sevn/agent/tracing/multi_sink.py#L70), [`MultiSink.close`](../../src/sevn/agent/tracing/multi_sink.py#L84).

Backward-compatible re-export of sevn.tracing.otel_pipeline.

Working with [`otel_pipeline.py`](../../src/sevn/agent/tracing/otel_pipeline.py): inspect the public entry points below.

OTLP HTTP trace exporter sink with bounded queue backpressure (about-sevn.bot/specs/04-tracing.md).

Working with [`otel_sink.py`](../../src/sevn/agent/tracing/otel_sink.py): inspect the public entry points below.
Start with [`OTelExporterSink.emit`](../../src/sevn/agent/tracing/otel_sink.py#L152), then [`OTelExporterSink.flush`](../../src/sevn/agent/tracing/otel_sink.py#L169), [`OTelExporterSink.close`](../../src/sevn/agent/tracing/otel_sink.py#L183).

Canonical provider.call trace emission for dashboard budget and provider stats.

Working with [`provider_call.py`](../../src/sevn/agent/tracing/provider_call.py): inspect the public entry points below.
Start with [`emit_provider_call`](../../src/sevn/agent/tracing/provider_call.py#L42).

Trace redaction wrapper applied once before sink fan-out (about-sevn.bot/specs/04-tracing.md §2.5).

Working with [`redacting_sink.py`](../../src/sevn/agent/tracing/redacting_sink.py): inspect the public entry points below.
Start with [`TraceRedactionPolicy.from_defaults`](../../src/sevn/agent/tracing/redacting_sink.py#L77), then [`redact_attrs`](../../src/sevn/agent/tracing/redacting_sink.py#L159), [`redact`](../../src/sevn/agent/tracing/redacting_sink.py#L182), [`RedactingSink.emit`](../../src/sevn/agent/tracing/redacting_sink.py#L237).

Trace redaction JSON helpers for operator toggles (about-sevn.bot/specs/04-tracing.md §2.5).

Working with [`redaction_config.py`](../../src/sevn/agent/tracing/redaction_config.py): inspect the public entry points below.
Start with [`effective_trace_redaction_enabled_from_doc`](../../src/sevn/agent/tracing/redaction_config.py#L38), then [`apply_trace_redaction_to_sevn_doc`](../../src/sevn/agent/tracing/redaction_config.py#L67).

Daily UTC JSONL trace sink under layout.traces_dir (about-sevn.bot/specs/04-tracing.md §2).

Working with [`rotating_jsonl_sink.py`](../../src/sevn/agent/tracing/rotating_jsonl_sink.py): inspect the public entry points below.
Start with [`RotatingJSONLFileSink.emit`](../../src/sevn/agent/tracing/rotating_jsonl_sink.py#L88), then [`RotatingJSONLFileSink.flush`](../../src/sevn/agent/tracing/rotating_jsonl_sink.py#L103), [`RotatingJSONLFileSink.close`](../../src/sevn/agent/tracing/rotating_jsonl_sink.py#L114).

11 more Python files under [`src/sevn/tracing`](../../src/sevn/tracing/) — including `src/sevn/agent/tracing/sink.py`, `src/sevn/agent/tracing/sink_factory.py`, `src/sevn/agent/tracing/sqlite_sink.py`, `src/sevn/agent/tracing/subagent_trace.py`.

### Extension and invariants

Follow [`04-tracing.md`](../../about-sevn.bot/specs/04-tracing.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/tracing`](../../src/sevn/tracing/), run `sevn readme update tracing` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/04-tracing.md](../../about-sevn.bot/specs/04-tracing.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/04-tracing.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/tracing/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
