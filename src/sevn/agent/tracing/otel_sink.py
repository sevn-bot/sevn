"""OTLP HTTP trace exporter sink with bounded queue backpressure (`specs/04-tracing.md`).

Module: sevn.agent.tracing.otel_sink
Depends: opentelemetry-sdk, opentelemetry-exporter-otlp-proto-http, queue, threading
Exports:
    OTelExporterSink — async ``TraceSink`` forwarding rows to OTLP HTTP collectors.
Examples:
    >>> from sevn.agent.tracing.otel_sink import DEFAULT_OTEL_QUEUE_SIZE
    >>> DEFAULT_OTEL_QUEUE_SIZE
    1000
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
from typing import TYPE_CHECKING

from loguru import logger
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Status, StatusCode

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent

DEFAULT_OTEL_QUEUE_SIZE = 1000


def _otel_status(status: str) -> Status:
    """Map sevn trace status strings to OpenTelemetry span status.

    Args:
        status (str): ``TraceEvent.status`` value.
    Returns:
        Status: OpenTelemetry status for the exported span.
    Examples:
        >>> _otel_status("ok").status_code
        <StatusCode.OK: 1>
        >>> _otel_status("error").status_code
        <StatusCode.ERROR: 2>
    """
    if status in ("ok", "started", "completed"):
        return Status(StatusCode.OK)
    if status in ("error", "failed", "denied", "cancelled", "escalated"):
        return Status(StatusCode.ERROR)
    return Status(StatusCode.UNSET)


def _flatten_attrs(event: TraceEvent) -> dict[str, str | int | float | bool]:
    """Coerce trace attrs plus identity columns into OTel-safe attribute values.

    Args:
        event (TraceEvent): Structured row from gateway emit sites.
    Returns:
        dict[str, str | int | float | bool]: Flat attribute mapping for OTLP export.
    Examples:
        >>> from sevn.agent.tracing.sink import TraceEvent
        >>> ev = TraceEvent(
        ...     kind="gateway.boot",
        ...     span_id="s",
        ...     parent_span_id=None,
        ...     session_id="se",
        ...     turn_id="tu",
        ...     tier=None,
        ...     ts_start_ns=1,
        ...     ts_end_ns=2,
        ...     status="ok",
        ...     attrs={"note": "boot"},
        ... )
        >>> _flatten_attrs(ev)["sevn.session_id"]
        'se'
    """
    out: dict[str, str | int | float | bool] = {
        "sevn.session_id": event.session_id,
        "sevn.turn_id": event.turn_id,
        "sevn.span_id": event.span_id,
        "sevn.status": event.status,
    }
    if event.parent_span_id:
        out["sevn.parent_span_id"] = event.parent_span_id
    if event.tier:
        out["sevn.tier"] = event.tier
    for key, value in event.attrs.items():
        attr_key = f"sevn.{key}" if not str(key).startswith("sevn.") else str(key)
        if isinstance(value, (str, int, float, bool)):
            out[attr_key] = value
        elif value is None:
            out[attr_key] = ""
        elif isinstance(value, (dict, list)):
            out[attr_key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            out[attr_key] = str(value)
    return out


class OTelExporterSink:
    """Forward ``TraceEvent`` rows to an OTLP HTTP collector without blocking callers.

    ``emit`` enqueues each event and returns immediately. A daemon background thread
    drains the queue and exports spans via OpenTelemetry. When the bounded queue is
    full, **drop-newest** applies: the incoming event is discarded so slow exporters
    cannot stall SQLite / JSONL siblings in :class:`~sevn.agent.tracing.multi_sink.MultiSink`.
    Exporter failures are logged and never raised through ``emit`` / ``flush`` / ``close``.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        headers: dict[str, str] | None = None,
        service_name: str = "sevn-gateway",
        queue_size: int = DEFAULT_OTEL_QUEUE_SIZE,
        exporter: SpanExporter | None = None,
    ) -> None:
        """Configure OTLP HTTP export and start the background drain thread.

        Args:
            endpoint (str): OTLP HTTP traces endpoint URL.
            headers (dict[str, str] | None): Optional auth / routing headers.
            service_name (str): ``service.name`` resource attribute.
            queue_size (int): Bounded queue capacity; drop-newest when full.
            exporter (SpanExporter | None): Test seam replacing the default OTLP exporter.
        Examples:
            >>> sink = OTelExporterSink(endpoint="http://127.0.0.1:4318/v1/traces")
            >>> sink._queue.maxsize
            1000
        """
        self._queue: queue.Queue[TraceEvent | None] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        otlp_exporter = exporter or OTLPSpanExporter(
            endpoint=endpoint,
            headers=dict(headers or {}),
        )
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        self._processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(self._processor)
        self._provider = provider
        self._tracer = provider.get_tracer("sevn.agent.tracing.otel_sink")
        self._thread = threading.Thread(
            target=self._worker,
            name="otel_trace_exporter",
            daemon=True,
        )
        self._thread.start()

    async def emit(self, event: TraceEvent) -> None:
        """Enqueue ``event`` for background export (drop-newest when queue is full).

        Args:
            event (TraceEvent): Structured row to forward to OTLP.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OTelExporterSink.emit)
            True
        """
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.bind(kind=event.kind, queue_size=self._queue.maxsize).warning(
                "otel sink queue full — dropping newest event",
            )

    async def flush(self) -> None:
        """Drain the pending queue and force-flush the OTLP batch processor.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OTelExporterSink.flush)
            True
        """
        self._drain_queue_sync()
        try:
            self._processor.force_flush(timeout_millis=5000)
        except Exception:
            logger.exception("otel sink flush failed")

    async def close(self) -> None:
        """Stop the worker thread and shut down the span processor.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OTelExporterSink.close)
            True
        """
        self._stop.set()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._drain_queue_sync()
        try:
            self._processor.shutdown()  # type: ignore[no-untyped-call]
            self._provider.shutdown()
        except Exception:
            logger.exception("otel sink close failed")

    def _worker(self) -> None:
        """Background loop exporting queued events until ``close`` signals stop.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(OTelExporterSink._worker)
            True
        """
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            self._export_event(item)

    def _drain_queue_sync(self) -> None:
        """Export any events still waiting in the queue (best-effort).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(OTelExporterSink._drain_queue_sync)
            True
        """
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            self._export_event(item)

    def _export_event(self, event: TraceEvent) -> None:
        """Map one ``TraceEvent`` to an OTel span and export (never raises).

        Args:
            event (TraceEvent): Dequeued trace row.
        Examples:
            >>> from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent
            >>> sink = OTelExporterSink(endpoint="http://127.0.0.1:4318/v1/traces")
            >>> sink._export_event(
            ...     TraceEvent(
            ...         kind="gateway.boot",
            ...         span_id="s1",
            ...         parent_span_id=None,
            ...         session_id="",
            ...         turn_id=SYSTEM_TURN_ID,
            ...         tier=None,
            ...         ts_start_ns=1,
            ...         ts_end_ns=2,
            ...         status="ok",
            ...     ),
            ... ) is None
            True
        """
        try:
            end_ns = event.ts_end_ns if event.ts_end_ns is not None else event.ts_start_ns
            span = self._tracer.start_span(
                name=event.kind,
                start_time=event.ts_start_ns,
                attributes=_flatten_attrs(event),
            )
            span.set_status(_otel_status(event.status))
            span.end(end_time=end_ns)
        except Exception:
            logger.bind(kind=event.kind, span_id=event.span_id).exception(
                "otel sink export failed",
            )


__all__ = ["DEFAULT_OTEL_QUEUE_SIZE", "OTelExporterSink"]
