"""OpenTelemetry test kit (plan 0015 W1.1). Nothing here exports over the network.

- ``in_memory_spans()`` installs an SDK ``TracerProvider`` with an
  ``InMemorySpanExporter`` as the global provider for one test, and removes it.
- ``OtlpReceiver`` is a loopback OTLP/HTTP collector that records every request
  (path, headers, decompressed body). ``GrpcReceiver`` is the gRPC twin.
- Every recorded body and header value is also fed to the K-CANARY ``otlp``
  capture, so ``Canary.assert_absent`` covers what an exporter sent.

Only third-party imports run at module level; product code is never imported here.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import socket
import threading
import time
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent import futures
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from support.canary import note_otlp

TRACES = "traces"
LOGS = "logs"
METRICS = "metrics"

_GRPC_SIGNALS = {
    "/opentelemetry.proto.collector.trace.v1.TraceService/Export": TRACES,
    "/opentelemetry.proto.collector.logs.v1.LogsService/Export": LOGS,
    "/opentelemetry.proto.collector.metrics.v1.MetricsService/Export": METRICS,
}


# --- global provider handling -------------------------------------------------


def reset_otel_globals() -> None:
    """Return the OTel API to its never-configured state.

    The API allows one ``set_*_provider`` per process. Tests need a fresh global
    per test, so the set-once guards are replaced. Pydantic AI's class-wide
    instrumentation default is cleared too, so a Logfire test cannot leak into
    a later in-memory test.
    """
    import opentelemetry._logs._internal as logs_api
    import opentelemetry.metrics._internal as metrics_api
    import opentelemetry.trace as trace_api
    from opentelemetry.util._once import Once
    from pydantic_ai import Agent

    trace_api._TRACER_PROVIDER_SET_ONCE = Once()
    trace_api._TRACER_PROVIDER = None
    metrics_api._METER_PROVIDER_SET_ONCE = Once()
    metrics_api._METER_PROVIDER = None
    logs_api._LOGGER_PROVIDER_SET_ONCE = Once()
    logs_api._LOGGER_PROVIDER = None
    Agent.instrument_all(False)


def global_tracer_provider_is_sdk() -> bool:
    """True when an SDK ``TracerProvider`` (not the API no-op proxy) is global."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    return isinstance(trace.get_tracer_provider(), TracerProvider)


def global_meter_provider_is_sdk() -> bool:
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider

    return isinstance(metrics.get_meter_provider(), MeterProvider)


def global_logger_provider_is_sdk() -> bool:
    from opentelemetry._logs import get_logger_provider
    from opentelemetry.sdk._logs import LoggerProvider

    return isinstance(get_logger_provider(), LoggerProvider)


@contextmanager
def in_memory_spans() -> Iterator[Any]:
    """Yield an ``InMemorySpanExporter`` behind the global SDK provider."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    reset_otel_globals()
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "sevn-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    try:
        yield exporter
    finally:
        provider.shutdown()
        reset_otel_globals()


# --- span helpers (in-memory ReadableSpan) -------------------------------------


def trace_hex(span: Any) -> str:
    return format(span.context.trace_id, "032x")


def span_hex(span: Any) -> str:
    return format(span.context.span_id, "016x")


def traceparent_of(span: Any) -> str:
    """The W3C ``traceparent`` a sampled span hands to a child."""
    return f"00-{trace_hex(span)}-{span_hex(span)}-01"


def parent_hex(span: Any) -> str | None:
    parent = span.parent
    if parent is None:
        return None
    return format(parent.span_id, "016x")


def finished(exporter: Any) -> list[Any]:
    return list(exporter.get_finished_spans())


def named(spans: Sequence[Any], name: str) -> list[Any]:
    return [span for span in spans if span.name == name]


def one(spans: Sequence[Any], name: str) -> Any:
    found = named(spans, name)
    assert len(found) == 1, f"expected one {name!r} span, got {[s.name for s in spans]}"
    return found[0]


def with_attribute(spans: Sequence[Any], key: str, value: object) -> list[Any]:
    return [span for span in spans if (span.attributes or {}).get(key) == value]


def descends_from(span: Any, ancestor: Any, spans: Sequence[Any]) -> bool:
    """True when ``ancestor`` is on ``span``'s parent chain within ``spans``."""
    by_id = {s.context.span_id: s for s in spans}
    current = span
    seen: set[int] = set()
    while current.parent is not None:
        parent_id = current.parent.span_id
        if parent_id == ancestor.context.span_id:
            return True
        if parent_id in seen or parent_id not in by_id:
            return False
        seen.add(parent_id)
        current = by_id[parent_id]
    return False


def attribute_text(span: Any) -> str:
    """Every attribute, event attribute and status description of ``span``."""
    parts: list[str] = [span.name]
    parts.extend(f"{key}={value}" for key, value in (span.attributes or {}).items())
    for event in span.events:
        parts.append(event.name)
        parts.extend(f"{key}={value}" for key, value in (event.attributes or {}).items())
    description = span.status.description
    if description:
        parts.append(description)
    return "\n".join(parts)


async def wait_spans(
    exporter: Any,
    predicate: Callable[[list[Any]], bool],
    *,
    timeout_s: float = 5,
) -> list[Any]:
    """Poll the in-memory exporter until ``predicate(spans)`` holds."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    spans = finished(exporter)
    while asyncio.get_running_loop().time() < deadline:
        spans = finished(exporter)
        if predicate(spans):
            return spans
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for spans: {[span.name for span in spans]}")


# --- OTLP payload parsing -----------------------------------------------------


@dataclass(frozen=True)
class Recorded:
    """One request a receiver saw. ``body`` is decompressed protobuf."""

    transport: str
    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    raw: bytes

    @property
    def signal(self) -> str:
        if self.transport == "grpc":
            return _GRPC_SIGNALS.get(self.path, "other")
        for name in (TRACES, LOGS, METRICS):
            if self.path.rstrip("/").endswith(f"/v1/{name}"):
                return name
        return "other"


@dataclass(frozen=True)
class ExportedSpan:
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str
    attributes: dict[str, object]
    events: list[tuple[str, dict[str, object]]]
    status_code: int
    status_message: str
    resource: dict[str, object]


@dataclass(frozen=True)
class ExportedLog:
    body: object
    attributes: dict[str, object]
    trace_id: str
    span_id: str
    severity_text: str
    severity_number: int
    resource: dict[str, object]


@dataclass(frozen=True)
class MetricPoint:
    name: str
    value: float
    attributes: dict[str, object]


def _any_value(value: Any) -> object:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_any_value(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return {item.key: _any_value(item.value) for item in value.kvlist_value.values}
    return getattr(value, kind)


def _attributes(items: Any) -> dict[str, object]:
    return {item.key: _any_value(item.value) for item in items}


def parse_spans(body: bytes) -> list[ExportedSpan]:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    request = ExportTraceServiceRequest.FromString(body)
    found: list[ExportedSpan] = []
    for resource_spans in request.resource_spans:
        resource = _attributes(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                found.append(
                    ExportedSpan(
                        name=span.name,
                        trace_id=span.trace_id.hex(),
                        span_id=span.span_id.hex(),
                        parent_span_id=span.parent_span_id.hex(),
                        attributes=_attributes(span.attributes),
                        events=[
                            (event.name, _attributes(event.attributes)) for event in span.events
                        ],
                        status_code=int(span.status.code),
                        status_message=span.status.message,
                        resource=resource,
                    )
                )
    return found


def parse_logs(body: bytes) -> list[ExportedLog]:
    from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

    request = ExportLogsServiceRequest.FromString(body)
    found: list[ExportedLog] = []
    for resource_logs in request.resource_logs:
        resource = _attributes(resource_logs.resource.attributes)
        for scope_logs in resource_logs.scope_logs:
            for record in scope_logs.log_records:
                found.append(
                    ExportedLog(
                        body=_any_value(record.body),
                        attributes=_attributes(record.attributes),
                        trace_id=record.trace_id.hex(),
                        span_id=record.span_id.hex(),
                        severity_text=record.severity_text,
                        severity_number=int(record.severity_number),
                        resource=resource,
                    )
                )
    return found


def parse_metrics(body: bytes) -> list[MetricPoint]:
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
        ExportMetricsServiceRequest,
    )

    request = ExportMetricsServiceRequest.FromString(body)
    found: list[MetricPoint] = []
    for resource_metrics in request.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                kind = metric.WhichOneof("data")
                if kind not in {"gauge", "sum"}:
                    continue
                points = getattr(metric, kind).data_points
                for point in points:
                    number = point.WhichOneof("value")
                    value = float(getattr(point, number)) if number is not None else 0.0
                    found.append(
                        MetricPoint(
                            name=metric.name,
                            value=value,
                            attributes=_attributes(point.attributes),
                        )
                    )
    return found


# --- receivers ----------------------------------------------------------------


@dataclass
class _Recorder:
    requests: list[Recorded] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, item: Recorded) -> None:
        with self.lock:
            self.requests.append(item)
        note_otlp(item.body)
        note_otlp(item.raw)
        note_otlp("\n".join(f"{key}: {value}" for key, value in item.headers.items()).encode())


class _Receiver:
    """Shared queries over what a receiver recorded."""

    endpoint: str

    def __init__(self) -> None:
        self._recorder = _Recorder()

    @property
    def requests(self) -> list[Recorded]:
        with self._recorder.lock:
            return list(self._recorder.requests)

    def signal_requests(self, signal: str) -> list[Recorded]:
        return [item for item in self.requests if item.signal == signal]

    def spans(self) -> list[ExportedSpan]:
        found: list[ExportedSpan] = []
        for item in self.signal_requests(TRACES):
            found.extend(parse_spans(item.body))
        return found

    def logs(self) -> list[ExportedLog]:
        found: list[ExportedLog] = []
        for item in self.signal_requests(LOGS):
            found.extend(parse_logs(item.body))
        return found

    def metrics(self) -> list[MetricPoint]:
        found: list[MetricPoint] = []
        for item in self.signal_requests(METRICS):
            found.extend(parse_metrics(item.body))
        return found

    def all_bytes(self) -> bytes:
        chunks: list[bytes] = []
        for item in self.requests:
            chunks.append(item.raw)
            chunks.append(item.body)
            chunks.extend(f"{key}: {value}".encode() for key, value in item.headers.items())
        return b"\n".join(chunks)

    def wait_for(
        self,
        predicate: Callable[[_Receiver], bool],
        *,
        timeout_s: float = 10,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if predicate(self):
                return
            time.sleep(0.05)
        paths = [item.path for item in self.requests]
        raise AssertionError(f"receiver timed out; saw {paths}")


class OtlpReceiver(_Receiver):
    """Loopback OTLP/HTTP collector.

    ``POST`` answers ``status`` with an empty protobuf body after waiting up to
    ``hang_s`` (released when the receiver closes). ``GET`` answers ``{}``-shaped
    JSON, which is enough for an SDK's token or info probe.
    """

    def __init__(self, *, status: int = 200, hang_s: float = 0.0) -> None:
        super().__init__()
        self.status = status
        self.hang_s = hang_s
        self.release = threading.Event()
        self.endpoint = ""
        self.port = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> OtlpReceiver:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length else b""
                owner._record("POST", self.path, dict(self.headers.items()), raw)
                if owner.hang_s > 0:
                    owner.release.wait(owner.hang_s)
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:
                owner._record("GET", self.path, dict(self.headers.items()), b"")
                body = json.dumps(
                    {"project_name": "sevn-test", "project_url": "http://127.0.0.1/"}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                _ = (format, args)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.daemon_threads = True
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def url(self) -> str:
        return self.endpoint

    def _record(self, method: str, path: str, headers: Mapping[str, str], raw: bytes) -> None:
        lowered = {key.lower(): value for key, value in headers.items()}
        encoding = lowered.get("content-encoding", "").lower()
        body = raw
        if encoding == "gzip" and raw:
            body = gzip.decompress(raw)
        elif encoding == "deflate" and raw:
            body = zlib.decompress(raw)
        self._recorder.add(
            Recorded(
                transport="http",
                method=method,
                path=path,
                headers=lowered,
                body=body,
                raw=raw,
            )
        )


class GrpcReceiver(_Receiver):
    """Loopback OTLP/gRPC collector for traces, logs and metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.endpoint = ""
        self.port = 0
        self._server: Any = None

    def __enter__(self) -> GrpcReceiver:
        import grpc
        from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
        from opentelemetry.proto.collector.metrics.v1 import (
            metrics_service_pb2,
            metrics_service_pb2_grpc,
        )
        from opentelemetry.proto.collector.trace.v1 import (
            trace_service_pb2,
            trace_service_pb2_grpc,
        )

        owner = self

        class Traces(trace_service_pb2_grpc.TraceServiceServicer):
            def Export(self, request: Any, context: Any) -> Any:
                owner._record(
                    "/opentelemetry.proto.collector.trace.v1.TraceService/Export", request, context
                )
                return trace_service_pb2.ExportTraceServiceResponse()

        class Logs(logs_service_pb2_grpc.LogsServiceServicer):
            def Export(self, request: Any, context: Any) -> Any:
                owner._record(
                    "/opentelemetry.proto.collector.logs.v1.LogsService/Export", request, context
                )
                return logs_service_pb2.ExportLogsServiceResponse()

        class Metrics(metrics_service_pb2_grpc.MetricsServiceServicer):
            def Export(self, request: Any, context: Any) -> Any:
                owner._record(
                    "/opentelemetry.proto.collector.metrics.v1.MetricsService/Export",
                    request,
                    context,
                )
                return metrics_service_pb2.ExportMetricsServiceResponse()

        server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        trace_service_pb2_grpc.add_TraceServiceServicer_to_server(Traces(), server)
        logs_service_pb2_grpc.add_LogsServiceServicer_to_server(Logs(), server)
        metrics_service_pb2_grpc.add_MetricsServiceServicer_to_server(Metrics(), server)
        self.port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        self._server = server
        self.endpoint = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.stop(grace=None)

    def _record(self, path: str, request: Any, context: Any) -> None:
        metadata = {str(key).lower(): str(value) for key, value in context.invocation_metadata()}
        body = request.SerializeToString()
        self._recorder.add(
            Recorded(
                transport="grpc",
                method="POST",
                path=path,
                headers=metadata,
                body=body,
                raw=body,
            )
        )


def dead_port() -> int:
    """A loopback port nothing listens on (bound, then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


__all__ = [
    "LOGS",
    "METRICS",
    "TRACES",
    "ExportedLog",
    "ExportedSpan",
    "GrpcReceiver",
    "MetricPoint",
    "OtlpReceiver",
    "Recorded",
    "attribute_text",
    "dead_port",
    "descends_from",
    "finished",
    "global_logger_provider_is_sdk",
    "global_meter_provider_is_sdk",
    "global_tracer_provider_is_sdk",
    "in_memory_spans",
    "named",
    "one",
    "parent_hex",
    "parse_logs",
    "parse_metrics",
    "parse_spans",
    "reset_otel_globals",
    "span_hex",
    "trace_hex",
    "traceparent_of",
    "wait_spans",
    "with_attribute",
]
