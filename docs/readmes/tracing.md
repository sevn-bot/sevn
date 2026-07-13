<!-- generated: do not edit by hand; run `sevn readme update tracing` -->
# Tracing — TraceSink, JSONL/SQLite/Logfire/OTel pipelines, and trace maintenance

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** TraceSink, JSONL/SQLite/Logfire/OTel pipelines, and trace maintenance.

## Level 1 — Overview (non-technical)

**Tracing** is a core part of sevn.bot — the personal AI assistant you run on your own machine. TraceSink, JSONL/SQLite/Logfire/OTel pipelines, and trace maintenance.

In everyday use, tracing helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Provide durable trace sinks that implement TraceSink without ever throwing through emit, so instrumentation stays off the critical path. SQLite layout matches Mission Control query patterns (prd-07-mi

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/tracing/`. The package contains 23 Python module(s); primary entry points include `src/sevn/agent/tracing/__init__.py`, `src/sevn/agent/tracing/agent_context.py`, `src/sevn/agent/tracing/attrs.py`, `src/sevn/agent/tracing/emit.py`, and 2 more.

### Data and control flow

Tracing sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/04-tracing.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/agent/tracing/agent_context.py` — `trace_text_field`, `serialize_message_history_for_trace`, `serialize_user_prompt_for_trace`, `build_triager_context_attrs`
- `src/sevn/agent/tracing/attrs.py` — `json_safe_trace_value`, `json_safe_trace_attrs`, `trace_tool_result_value`
- `src/sevn/agent/tracing/emit.py` — `register_trace_subscriber`, `unregister_trace_subscriber`, `wrap_trace_sink`, `reset_trace_subscribers_for_tests`
- `src/sevn/agent/tracing/logfire_config.py` — `logfire_export_status_from_doc`, `logfire_export_status`, `apply_logfire_export_to_sevn_doc`, `logfire_sink_entry_for_tests`
- `src/sevn/agent/tracing/multi_sink.py` — `MultiSink.emit`, `MultiSink.flush`, `MultiSink.close`

### Spec context

From about-sevn.bot/specs/04-tracing.md:
Provide durable trace sinks that implement TraceSink without ever throwing through emit, so instrumentation stays off the critical path. SQLite layout matches Mission Control query patterns (prd-07-mi

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/tracing/` (23 Python files). Normative design: `about-sevn.bot/specs/04-tracing.md`.

### Module inventory

- `src/sevn/agent/tracing/__init__.py` — """Tracing and telemetry hooks.
- `src/sevn/agent/tracing/agent_context.py` — """Structured agent-context snapshots for trace export ('about-sevn.bot/specs/04-tracing.md').
- `src/sevn/agent/tracing/attrs.py` — """Trace ''attrs'' normalization ('about-sevn.bot/specs/04-tracing.md' §7).
- `src/sevn/agent/tracing/emit.py` — """In-process trace fan-out before persistence ('about-sevn.bot/specs/04-tracing.md' §2).
- `src/sevn/agent/tracing/logfire_config.py` — """Logfire trace export helpers for operator toggles ('about-sevn.bot/specs/04-tracing.md').
- `src/sevn/agent/tracing/multi_sink.py` — """Compose multiple ''TraceSink'' instances ('about-sevn.bot/specs/04-tracing.md' §2).
- `src/sevn/agent/tracing/otel_pipeline.py` — """Backward-compatible re-export of ''sevn.tracing.otel_pipeline''.
- `src/sevn/agent/tracing/otel_sink.py` — """OTLP HTTP trace exporter sink with bounded queue backpressure ('about-sevn.bot/specs/04-tracing.md').
- `src/sevn/agent/tracing/provider_call.py` — """Canonical ''provider.call'' trace emission for dashboard budget and provider stats.
- `src/sevn/agent/tracing/redacting_sink.py` — """Trace redaction wrapper applied once before sink fan-out ('about-sevn.bot/specs/04-tracing.md' §2.5).
- `src/sevn/agent/tracing/redaction_config.py` — """Trace redaction JSON helpers for operator toggles ('about-sevn.bot/specs/04-tracing.md' §2.5).
- `src/sevn/agent/tracing/rotating_jsonl_sink.py` — """Daily UTC JSONL trace sink under ''layout.traces_dir'' ('about-sevn.bot/specs/04-tracing.md' §2).
- … and 11 more Python modules

### Agent Context (`src/sevn/agent/tracing/agent_context.py`)

Public entry points:
- `trace_text_field` — see `src/sevn/agent/tracing/agent_context.py`
- `serialize_message_history_for_trace` — see `src/sevn/agent/tracing/agent_context.py`
- `serialize_user_prompt_for_trace` — see `src/sevn/agent/tracing/agent_context.py`
- `build_triager_context_attrs` — see `src/sevn/agent/tracing/agent_context.py`
- `build_tier_b_context_attrs` — see `src/sevn/agent/tracing/agent_context.py`
- `emit_context_span` — see `src/sevn/agent/tracing/agent_context.py`

### Attrs (`src/sevn/agent/tracing/attrs.py`)

Public entry points:
- `json_safe_trace_value` — see `src/sevn/agent/tracing/attrs.py`
- `json_safe_trace_attrs` — see `src/sevn/agent/tracing/attrs.py`
- `trace_tool_result_value` — see `src/sevn/agent/tracing/attrs.py`

### Emit (`src/sevn/agent/tracing/emit.py`)

Public entry points:
- `register_trace_subscriber` — see `src/sevn/agent/tracing/emit.py`
- `unregister_trace_subscriber` — see `src/sevn/agent/tracing/emit.py`
- `wrap_trace_sink` — see `src/sevn/agent/tracing/emit.py`
- `reset_trace_subscribers_for_tests` — see `src/sevn/agent/tracing/emit.py`

### Logfire Config (`src/sevn/agent/tracing/logfire_config.py`)

Public entry points:
- `logfire_export_status_from_doc` — see `src/sevn/agent/tracing/logfire_config.py`
- `logfire_export_status` — see `src/sevn/agent/tracing/logfire_config.py`
- `apply_logfire_export_to_sevn_doc` — see `src/sevn/agent/tracing/logfire_config.py`
- `logfire_sink_entry_for_tests` — see `src/sevn/agent/tracing/logfire_config.py`

### Multi Sink (`src/sevn/agent/tracing/multi_sink.py`)

Public entry points:
- `MultiSink.emit` — see `src/sevn/agent/tracing/multi_sink.py`
- `MultiSink.flush` — see `src/sevn/agent/tracing/multi_sink.py`
- `MultiSink.close` — see `src/sevn/agent/tracing/multi_sink.py`

### Otel Sink (`src/sevn/agent/tracing/otel_sink.py`)

Public entry points:
- `OTelExporterSink.emit` — see `src/sevn/agent/tracing/otel_sink.py`
- `OTelExporterSink.flush` — see `src/sevn/agent/tracing/otel_sink.py`
- `OTelExporterSink.close` — see `src/sevn/agent/tracing/otel_sink.py`

### Provider Call (`src/sevn/agent/tracing/provider_call.py`)

Public entry points:
- `emit_provider_call` — see `src/sevn/agent/tracing/provider_call.py`

### Redacting Sink (`src/sevn/agent/tracing/redacting_sink.py`)

Public entry points:
- `TraceRedactionPolicy.from_defaults` — see `src/sevn/agent/tracing/redacting_sink.py`
- `redact_attrs` — see `src/sevn/agent/tracing/redacting_sink.py`
- `redact` — see `src/sevn/agent/tracing/redacting_sink.py`
- `RedactingSink.emit` — see `src/sevn/agent/tracing/redacting_sink.py`
- `RedactingSink.flush` — see `src/sevn/agent/tracing/redacting_sink.py`
- `RedactingSink.close` — see `src/sevn/agent/tracing/redacting_sink.py`

### Additional modules

11 more Python files under `src/sevn/tracing/` — including `src/sevn/agent/tracing/sink.py`, `src/sevn/agent/tracing/sink_factory.py`, `src/sevn/agent/tracing/sqlite_sink.py`, `src/sevn/agent/tracing/subagent_trace.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/04-tracing.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/tracing/`, run `sevn readme update tracing` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/04-tracing.md](../../about-sevn.bot/specs/04-tracing.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/04-tracing.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/tracing/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
