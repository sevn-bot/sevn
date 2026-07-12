"""Tracing and telemetry hooks.

Module: sevn.agent.tracing
Depends: sevn.agent.tracing.multi_sink, sevn.agent.tracing.sink,
         sevn.agent.tracing.sink_factory, sevn.agent.tracing.sqlite_sink,
         sevn.agent.tracing.traces_maintenance

Exports:
    JSONLFileSink — append-only JSONL trace sink.
    MultiSink — ordered composition of sinks (`tracing.sinks[]`).
    SQLiteSink — Mission Control ``traces.db`` sink.
    TraceEvent — structured trace row.
    TraceSink — sink protocol.
    build_gateway_trace_sink — ``sevn.json`` sink assembly for gateway boot.
    current_sink — task-local sink when the gateway binds scope.
    register_trace_subscriber — in-process trace observer (Mission Control).
    trace_sink_scope — context manager for ``current_sink`` (HTTP + WebChat WS).
    wrap_trace_sink — fan-out registered observers before persistence.
    purge_trace_events_ttl — TTL purge job for the gateway lifespan.
    write_hourly_rollups — idempotent hourly rollup writer.
"""

from __future__ import annotations

from sevn.agent.tracing.emit import register_trace_subscriber, wrap_trace_sink
from sevn.agent.tracing.multi_sink import MultiSink
from sevn.agent.tracing.sink import (
    JSONLFileSink,
    TraceEvent,
    TraceSink,
    current_sink,
    trace_sink_scope,
)
from sevn.agent.tracing.sink_factory import build_gateway_trace_sink
from sevn.agent.tracing.sqlite_sink import SQLiteSink
from sevn.agent.tracing.traces_maintenance import (
    purge_trace_events_ttl,
    write_hourly_rollups,
)

__all__ = [
    "JSONLFileSink",
    "MultiSink",
    "SQLiteSink",
    "TraceEvent",
    "TraceSink",
    "build_gateway_trace_sink",
    "current_sink",
    "purge_trace_events_ttl",
    "register_trace_subscriber",
    "trace_sink_scope",
    "wrap_trace_sink",
    "write_hourly_rollups",
]
