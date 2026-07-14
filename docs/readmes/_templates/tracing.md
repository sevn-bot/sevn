<!-- template: slug=tracing profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Tracing — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. Trace events for debugging and Mission Control;
     JSONL/SQLite persistence; optional OTLP/Logfire export. Emit never throws.
     Operator terms in L1. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for tracing:
       ### Sink fan-out — jsonl_file, sqlite real sinks; logfire/otel OTLP bridge
       ### OTLP bridge — configure_gateway_otel, TraceEventOtelBridge
       ### sink_factory — build_gateway_trace_sink, _sink_from_entry skips logfire/otel leaves
       ### Redaction — RedactingSink wrapper
       ### Configuration (`sevn.json` → `tracing`) — sinks[], redaction
     Cite real symbols. D21 links throughout. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
