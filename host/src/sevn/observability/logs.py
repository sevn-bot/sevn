"""loguru records as OTel logs (plan 0015 D7, D8).

With an exporter on, ``install`` adds a loguru sink that forwards records at
``INFO`` and above to an SDK ``LoggerProvider``. Each record keeps the trace and
span ids of the span that was current when it was logged. The exporter wrapper
scrubs every body and attribute itself, so a record that skipped the loguru
redaction patcher is still clean on the wire.

Exporter failures are reported through a loguru WARNING. That warning, and the
OTel SDK's own log lines, never re-enter the sink: the SDK marks its export
threads with the suppress-instrumentation context, and ``opentelemetry.*``
records are skipped, so a dead collector cannot feed itself.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, cast

from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.instrumentation.utils import is_instrumentation_enabled
from opentelemetry.sdk._logs import LoggerProvider, ReadableLogRecord, ReadWriteLogRecord
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    LogRecordExporter,
    LogRecordExportResult,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.util.types import AnyValue, AttributeValue

from sevn import __version__
from sevn.log import logger
from sevn.observability.metrics import Drops, QueueGate
from sevn.observability.redact import scrub, scrub_attributes

if TYPE_CHECKING:
    from loguru import Message, Record

LEVEL = "INFO"
SCOPE = "sevn"
_QUEUE_CAP = 2048
_IDS = frozenset({"trace_id", "span_id"})
# loguru level numbers -> OTel severity, highest first.
_SEVERITIES = (
    (50, SeverityNumber.FATAL),
    (40, SeverityNumber.ERROR),
    (30, SeverityNumber.WARN),
    (25, SeverityNumber.INFO2),
    (20, SeverityNumber.INFO),
    (10, SeverityNumber.DEBUG),
)

type FailureReport = Callable[[str], None]


def scrub_body(value: AnyValue) -> AnyValue:
    """``value`` with every string in it scrubbed; mappings and sequences keep their shape."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, Mapping):
        items = cast("Mapping[str, AnyValue]", value)
        return {key: scrub_body(item) for key, item in items.items()}
    if isinstance(value, list | tuple):
        sequence = cast("Sequence[AnyValue]", value)
        return [scrub_body(item) for item in sequence]
    return value


def scrub_log(readable: ReadableLogRecord) -> ReadableLogRecord:
    """A copy of ``readable`` whose body and attributes are scrubbed; ids and times kept."""
    clean = copy.copy(readable.log_record)
    clean.body = scrub_body(clean.body)
    clean.attributes = scrub_attributes(clean.attributes)
    return ReadableLogRecord(
        log_record=clean,
        resource=readable.resource,
        instrumentation_scope=readable.instrumentation_scope,
        limits=readable.limits,
    )


class RedactingLogExporter(LogRecordExporter):
    """Scrubs every log record before ``inner`` sees it (D7)."""

    def __init__(self, inner: LogRecordExporter) -> None:
        self.inner = inner

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        return self.inner.export([scrub_log(item) for item in batch])

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.inner.shutdown()


class _ReportingLogExporter(LogRecordExporter):
    """Turns a failed export into one report; never raises. Frees ``gate`` slots."""

    def __init__(self, inner: LogRecordExporter, report: FailureReport, gate: QueueGate) -> None:
        self._inner = inner
        self._report = report
        self._gate = gate

    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        self._gate.taken(len(batch))
        try:
            result = self._inner.export(batch)
        except Exception as exc:  # noqa: BLE001 — a failed export is dropped, not raised
            self._report(type(exc).__name__)
            return LogRecordExportResult.FAILURE
        if result is not LogRecordExportResult.SUCCESS:
            self._report("rejected or unreachable")
        return result

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return self._inner.force_flush(timeout_millis)
        except Exception:  # noqa: BLE001 — flushing telemetry must not raise
            return False

    def shutdown(self) -> None:
        try:
            self._inner.shutdown()
        except Exception as exc:  # noqa: BLE001 — shutdown must not raise
            self._report(type(exc).__name__)


def otlp_exporter(
    protocol: str,
    endpoint: str,
    headers: Mapping[str, str],
    *,
    timeout_s: float,
    gzip: bool = False,
) -> LogRecordExporter:
    """The OTLP log exporter for ``protocol``. An empty ``headers`` defers to the OTEL env."""
    resolved = dict(headers) or None
    if protocol == "grpc":
        from urllib.parse import urlsplit

        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
            OTLPLogExporter as GrpcLogExporter,
        )

        return GrpcLogExporter(
            endpoint=endpoint,
            insecure=urlsplit(endpoint).scheme == "http",
            headers=resolved,
            timeout=timeout_s,
        )
    from opentelemetry.exporter.otlp.proto.http import Compression
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

    return OTLPLogExporter(
        endpoint=endpoint,
        headers=resolved,
        timeout=timeout_s,
        compression=Compression.Gzip if gzip else None,
    )


class LogExport:
    """The installed sink and provider. ``close`` removes the sink, then flushes."""

    def __init__(self, provider: LoggerProvider, sink_id: int) -> None:
        self.provider = provider
        self._sink_id: int | None = sink_id

    def detach(self) -> None:
        """Stop forwarding records. Idempotent."""
        sink_id, self._sink_id = self._sink_id, None
        if sink_id is not None:
            # ``sevn.log.setup`` may have removed every sink already.
            with suppress(ValueError):
                logger.remove(sink_id)

    def close(self) -> None:
        self.detach()
        self.provider.shutdown()


def install(
    exporter: LogRecordExporter,
    resource: Resource,
    report: FailureReport,
    *,
    export_timeout_s: float,
    drops: Drops,
) -> LogExport:
    """Make ``exporter`` (behind the redacting wrapper) the destination of loguru records."""
    gate = QueueGate("logs", _QUEUE_CAP, drops)
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(
        _GatedLogProcessor(
            _ReportingLogExporter(RedactingLogExporter(exporter), report, gate),
            gate,
            export_timeout_s=export_timeout_s,
        )
    )
    set_logger_provider(provider)
    sink_id = logger.add(_Sink(provider), level=LEVEL, format="{message}", catch=True)
    return LogExport(provider, sink_id)


class _GatedLogProcessor(BatchLogRecordProcessor):
    """A batch processor that queues a record only when ``gate`` admits it (D12)."""

    def __init__(
        self, exporter: LogRecordExporter, gate: QueueGate, *, export_timeout_s: float
    ) -> None:
        super().__init__(
            exporter, max_queue_size=_QUEUE_CAP, export_timeout_millis=export_timeout_s * 1000
        )
        self._gate = gate

    def on_emit(self, log_record: ReadWriteLogRecord) -> None:
        if self._gate.admit():
            super().on_emit(log_record)


class _Sink:
    """loguru sink: one OTel log record per loguru record."""

    def __init__(self, provider: LoggerProvider) -> None:
        self._logger = provider.get_logger(SCOPE, __version__)

    def __call__(self, message: Message) -> None:
        # Inside an exporter's thread: its own failure report must not loop back.
        if not is_instrumentation_enabled():
            return
        record = message.record
        name = record["name"] or ""
        if name.startswith("opentelemetry"):
            return
        level = record["level"]
        self._logger.emit(
            timestamp=int(record["time"].timestamp() * 1_000_000_000),
            severity_number=_severity(level.no),
            severity_text=level.name,
            body=str(record["message"]),
            attributes=_attributes(record),
        )


def _severity(number: int) -> SeverityNumber:
    for floor, severity in _SEVERITIES:
        if number >= floor:
            return severity
    return SeverityNumber.TRACE


def _attributes(record: Record) -> dict[str, AttributeValue]:
    attributes: dict[str, AttributeValue] = {
        "code.namespace": record["name"] or "",
        "code.function": record["function"],
        "code.lineno": record["line"],
    }
    for key, value in record["extra"].items():
        # ``_``-prefixed keys are sevn.log's rendering scratch; ids ride on the record.
        if key.startswith("_") or key in _IDS:
            continue
        attributes[key] = _attribute_value(value)
    exception = record["exception"]
    if exception is not None and exception.type is not None:
        attributes["exception.type"] = exception.type.__name__
        text = record["extra"].get("_exception_text")
        if isinstance(text, str) and text != "":
            attributes["exception.stacktrace"] = text
    return attributes


def _attribute_value(value: object) -> AttributeValue:
    if isinstance(value, str | bool | int | float):
        return value
    return str(value)


__all__ = [
    "LEVEL",
    "LogExport",
    "RedactingLogExporter",
    "install",
    "otlp_exporter",
    "scrub_body",
    "scrub_log",
]
