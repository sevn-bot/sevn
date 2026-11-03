"""Turn OTel export on or off at host startup (plan 0015 D1-D4, D8-D10, D12).

Tracing never changes behaviour: a missing secret, a bad endpoint or an
unreachable collector is logged once at WARNING and leaves the host running.
With the exporter off nothing is installed, so the OTel API stays a no-op.
With it on, traces, loguru records (``logs``) and the host gauges (``metrics``)
go to the same backend, each behind sevn's own redaction and failure report.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from sevn import __version__
from sevn.config import SECRET_REF_PREFIX, ExporterName, ObservabilitySettings, Settings
from sevn.identity import HostIdentity
from sevn.log import logger
from sevn.observability import logs, metrics
from sevn.observability.presets import ExportTarget, resolve
from sevn.observability.redact import RedactingExporter, logfire_callback
from sevn.paths import Paths
from sevn.secrets.backends import open_backend
from sevn.secrets.errors import SecretNotFound

if TYPE_CHECKING:
    from fastapi import FastAPI
    from logfire import Logfire
    from opentelemetry.sdk._logs.export import LogRecordExporter
    from opentelemetry.sdk.metrics.export import MetricExporter

LOGFIRE_TOKEN_SECRET = "logfire/token"  # noqa: S105 — a secret name, not a value

SHUTDOWN_CAP_S = 5.0
_EXPORT_TIMEOUT_S = 5.0
_WARN_EVERY_S = 600.0
_QUEUE_CAP = 2048
# The OTel exporters log every failed attempt; sevn reports failures itself (D12).
_QUIET_LOGGERS = ("opentelemetry.exporter",)
# Logfire adds its own unredacted OTLP exporters when these are set. sevn only
# honours them on the ``otlp`` path, so they are hidden while Logfire configures.
_LOGFIRE_IGNORED_ENV = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
)


class _SetupError(Exception):
    """Export cannot start; the message names what is missing, never a secret value."""


def choose_exporter(settings: Settings) -> ExporterName:
    """The effective exporter: explicit wins; unset is Logfire when its token exists."""
    explicit = settings.observability.exporter
    if explicit is not None:
        return explicit
    return "logfire" if _logfire_token(settings) else "none"


class ObservabilityHandle:
    """What ``setup`` installed. ``shutdown`` flushes within ``SHUTDOWN_CAP_S``."""

    def __init__(
        self,
        exporter: ExporterName,
        close: Callable[[], object] | None = None,
        notice: FailureNotice | None = None,
    ) -> None:
        self._exporter: ExporterName = exporter
        self._close = close
        self._notice = notice
        self._lock = threading.Lock()
        self._closed = False

    @property
    def exporter(self) -> ExporterName:
        return self._exporter

    def last_export(self, signal: str) -> ExportResult | None:
        """The latest export result for ``signal`` (``traces``, ``logs``, ``metrics``), if any."""
        return None if self._notice is None else self._notice.result(signal)

    def shutdown(self) -> None:
        """Flush and stop the exporters. Idempotent, never raises, never blocks past the cap."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        close = self._close
        if close is None:
            return
        worker = threading.Thread(
            target=_run_close, args=(close,), name="sevn-otel-shutdown", daemon=True
        )
        worker.start()
        worker.join(SHUTDOWN_CAP_S)
        if worker.is_alive():
            logger.warning(
                "observability: shutdown did not finish within {cap:.0f} s; "
                "unsent telemetry is dropped",
                cap=SHUTDOWN_CAP_S,
            )


def _run_close(close: Callable[[], object]) -> None:
    try:
        close()
    except Exception as exc:  # noqa: BLE001 — shutdown must never raise into the host
        logger.warning(
            "observability: shutdown failed ({kind}: {reason})",
            kind=type(exc).__name__,
            reason=str(exc),
        )


def setup(settings: Settings, identity: HostIdentity) -> ObservabilityHandle:
    """Install the exporter ``settings`` choose. Failures leave tracing off."""
    try:
        chosen = choose_exporter(settings)
        if chosen == "none":
            return ObservabilityHandle("none")
        if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
            # The OTel API keeps the first provider for the life of the process, so
            # spans would not reach this setup's exporters (D12: report, stay off).
            raise _SetupError("a tracer provider is already installed in this process")
        _quiet_otel_loggers()
        if chosen == "otlp":
            return _setup_otlp(settings, identity)
        return _setup_logfire(settings, identity)
    except _SetupError as exc:
        logger.warning("observability is off: {reason}", reason=str(exc))
    except Exception as exc:  # noqa: BLE001 — tracing must never fail startup
        logger.warning(
            "observability is off: setup failed ({kind}: {reason})",
            kind=type(exc).__name__,
            reason=str(exc),
        )
    return ObservabilityHandle("none")


# --- OTLP -------------------------------------------------------------------------


def _setup_otlp(settings: Settings, identity: HostIdentity) -> ObservabilityHandle:
    obs = settings.observability
    target = resolve(obs)
    host = _endpoint_host(target.traces_endpoint)
    headers = _resolve_headers(target.trace_headers, settings)
    log_headers = _resolve_headers(target.log_headers, settings)
    metric_headers = _resolve_headers(target.metric_headers, settings)
    notice = FailureNotice()
    drops = _drops(notice, host)
    resource = _resource(obs, identity, target.resource_attributes)
    provider = TracerProvider(resource=resource, sampler=_sampler(obs))
    provider.add_span_processor(_batch(_otlp_span_exporter(target, headers), notice, host, drops))
    close = _install_signals(
        provider.shutdown,
        resource,
        notice,
        host,
        drops,
        logs.otlp_exporter(
            target.protocol, target.logs_endpoint, log_headers, timeout_s=_EXPORT_TIMEOUT_S
        ),
        metrics.otlp_exporter(
            target.protocol, target.metrics_endpoint, metric_headers, timeout_s=_EXPORT_TIMEOUT_S
        ),
    )
    trace.set_tracer_provider(provider)
    return ObservabilityHandle("otlp", close=close, notice=notice)


def _otlp_span_exporter(target: ExportTarget, headers: dict[str, str]) -> SpanExporter:
    # An empty mapping lets the exporter fall back to OTEL_EXPORTER_OTLP_HEADERS (D1).
    resolved = headers or None
    if target.protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcSpanExporter,
        )

        return GrpcSpanExporter(
            endpoint=target.traces_endpoint,
            insecure=urlsplit(target.traces_endpoint).scheme == "http",
            headers=resolved,
            timeout=_EXPORT_TIMEOUT_S,
        )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(
        endpoint=target.traces_endpoint, headers=resolved, timeout=_EXPORT_TIMEOUT_S
    )


def _resolve_headers(headers: Mapping[str, str], settings: Settings) -> dict[str, str]:
    """Resolve ``secret://`` references through the secret backend; literals stay."""
    refs = {key: value for key, value in headers.items() if value.startswith(SECRET_REF_PREFIX)}
    resolved = {key: value for key, value in headers.items() if key not in refs}
    if not refs:
        return resolved
    backend = open_backend(settings, Paths.from_env())
    for key, ref in refs.items():
        name = ref.removeprefix(SECRET_REF_PREFIX)
        try:
            resolved[key] = backend.get(name)
        except SecretNotFound:
            raise _SetupError(f"header {key!r}: secret {name!r} not found") from None
    return resolved


# --- Logfire ------------------------------------------------------------------------


def _setup_logfire(settings: Settings, identity: HostIdentity) -> ObservabilityHandle:
    import logfire
    from opentelemetry.exporter.otlp.proto.http import Compression
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    obs = settings.observability
    token = _logfire_token(settings)
    if not token:
        raise _SetupError(f"secret {LOGFIRE_TOKEN_SECRET!r} not found")
    # The region comes from the token unless LOGFIRE_BASE_URL overrides it.
    advanced = logfire.AdvancedOptions(base_url=os.environ.get("LOGFIRE_BASE_URL") or None)
    base_url = advanced.generate_base_url(token)
    traces_endpoint = urljoin(base_url, "/v1/traces")
    host = _endpoint_host(traces_endpoint)
    # Logfire's own exporter would ship spans sevn has not scrubbed, so sevn
    # exports to Logfire's intake itself, behind the redacting wrapper.
    exporter = OTLPSpanExporter(
        endpoint=traces_endpoint,
        headers={"Authorization": token, "User-Agent": f"sevn/{__version__}"},
        compression=Compression.Gzip,
        timeout=_EXPORT_TIMEOUT_S,
    )
    notice = FailureNotice()
    drops = _drops(notice, host)
    processor = _batch(exporter, notice, host, drops)
    environment = _environment()
    with _without_env(_LOGFIRE_IGNORED_ENV):
        instance = logfire.configure(
            local=True,
            send_to_logfire=False,
            token=token,
            service_name=obs.service_name,
            service_version=__version__,
            environment=environment,
            resource_attributes={
                "sevn.host_id": identity.host_id,
                "deployment.environment": environment,
                "deployment.environment.name": environment,
            },
            console=False,
            additional_span_processors=[processor],
            metrics=False,
            scrubbing=logfire.ScrubbingOptions(callback=logfire_callback),
            sampling=logfire.SamplingOptions(head=obs.sample_ratio),
            inspect_arguments=False,
            add_baggage_to_attributes=False,
            distributed_tracing=True,
            advanced=advanced,
        )
    # Logs and metrics go to Logfire's intake the same way: sevn's exporters, redacted.
    intake = {"Authorization": token, "User-Agent": f"sevn/{__version__}"}
    close = _install_signals(
        lambda: _close_logfire(instance),
        _resource(obs, identity),
        notice,
        host,
        drops,
        logs.otlp_exporter(
            "http/protobuf",
            urljoin(base_url, "/v1/logs"),
            intake,
            timeout_s=_EXPORT_TIMEOUT_S,
            gzip=True,
        ),
        metrics.otlp_exporter(
            "http/protobuf",
            urljoin(base_url, "/v1/metrics"),
            intake,
            timeout_s=_EXPORT_TIMEOUT_S,
            gzip=True,
        ),
    )
    trace.set_tracer_provider(instance.config.get_tracer_provider())
    return ObservabilityHandle("logfire", close=close, notice=notice)


def _close_logfire(instance: Logfire) -> None:
    instance.shutdown(timeout_millis=int(SHUTDOWN_CAP_S * 1000), flush=True)


@contextmanager
def _without_env(keys: Sequence[str]) -> Generator[None]:
    saved = {key: os.environ.pop(key) for key in keys if key in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _logfire_token(settings: Settings) -> str:
    try:
        return open_backend(settings, Paths.from_env()).get(LOGFIRE_TOKEN_SECRET)
    except SecretNotFound:
        return ""


# --- shared pieces --------------------------------------------------------------------


def _install_signals(
    close_traces: Callable[[], object],
    resource: Resource,
    notice: FailureNotice,
    host: str,
    drops: metrics.Drops,
    log_exporter: LogRecordExporter,
    metric_exporter: MetricExporter,
) -> Callable[[], None]:
    """Install log and metric export next to the traces; return the close for all three.

    The three exporters share ``notice``, so a dead collector is one WARNING (D12).
    The log sink is detached first, so nothing logged while closing is queued.
    """

    def report(signal: str) -> Callable[[str], None]:
        return lambda detail: notice.report(signal, host, detail)

    log_export = logs.install(
        log_exporter, resource, report("logs"), export_timeout_s=_EXPORT_TIMEOUT_S, drops=drops
    )
    metric_export = metrics.install(
        metric_exporter,
        resource,
        report("metrics"),
        export_timeout_s=_EXPORT_TIMEOUT_S,
        drops=drops,
    )
    steps: tuple[Callable[[], object], ...] = (
        log_export.detach,
        close_traces,
        log_export.close,
        metric_export.close,
    )

    def close() -> None:
        for step in steps:
            _run_close(step)

    return close


def _resource(
    obs: ObservabilitySettings, identity: HostIdentity, extra: Mapping[str, bool] | None = None
) -> Resource:
    return Resource.create(
        {
            **(extra or {}),
            SERVICE_NAME: obs.service_name,
            SERVICE_VERSION: __version__,
            "sevn.host_id": identity.host_id,
            "deployment.environment": _environment(),
            "deployment.environment.name": _environment(),
        }
    )


def _environment() -> str:
    return os.environ.get("SEVN_ENV", "").strip() or "local"


def _sampler(obs: ObservabilitySettings) -> ParentBased:
    return ParentBased(TraceIdRatioBased(obs.sample_ratio))


def _drops(notice: FailureNotice, host: str) -> metrics.Drops:
    return metrics.Drops(lambda detail: notice.report("telemetry", host, detail))


def _batch(
    exporter: SpanExporter, notice: FailureNotice, host: str, drops: metrics.Drops
) -> BatchSpanProcessor:
    """The span queue: gated to ``_QUEUE_CAP``, redacted, failures reported (D7, D12)."""
    gate = metrics.QueueGate("traces", _QUEUE_CAP, drops)
    return _GatedSpanProcessor(
        _ReportingExporter(RedactingExporter(exporter), notice, "traces", host, gate), gate
    )


class _GatedSpanProcessor(BatchSpanProcessor):
    """A batch processor that queues a span only when ``gate`` admits it (D12)."""

    def __init__(self, exporter: SpanExporter, gate: metrics.QueueGate) -> None:
        super().__init__(
            exporter,
            max_queue_size=_QUEUE_CAP,
            export_timeout_millis=int(_EXPORT_TIMEOUT_S * 1000),
        )
        self._gate = gate

    def on_end(self, span: ReadableSpan) -> None:
        # Unsampled spans never reach the SDK queue, so they take no slot.
        if span.context is None or not span.context.trace_flags.sampled:
            return
        if self._gate.admit():
            super().on_end(span)


def _endpoint_host(endpoint: str) -> str:
    """The endpoint's ``host[:port]``, for messages. Raises when it is not an http(s) URL."""
    if endpoint == "":
        raise _SetupError(
            "no OTLP endpoint; set observability.endpoint or OTEL_EXPORTER_OTLP_ENDPOINT"
        )
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise _SetupError("observability.endpoint is not a valid URL") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise _SetupError("observability.endpoint must be an http:// or https:// URL")
    return parts.hostname if port is None else f"{parts.hostname}:{port}"


def _quiet_otel_loggers() -> None:
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


@dataclass(frozen=True, slots=True)
class ExportResult:
    """One export attempt's outcome; ``detail`` says why it failed."""

    ok: bool
    detail: str = ""


class FailureNotice:
    """One WARNING per ``_WARN_EVERY_S`` for the exporters one ``setup`` call built (D12).

    It also keeps the latest result per signal, so ``sevn traces test`` and
    ``sevn doctor --check`` can tell whether the collector accepted an export.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last: float | None = None
        self._results: dict[str, ExportResult] = {}

    def succeeded(self, signal: str) -> None:
        with self._lock:
            self._results[signal] = ExportResult(ok=True)

    def result(self, signal: str) -> ExportResult | None:
        with self._lock:
            return self._results.get(signal)

    def report(self, signal: str, host: str, detail: str) -> None:
        now = self._clock()
        with self._lock:
            self._results[signal] = ExportResult(ok=False, detail=detail)
            if self._last is not None and now - self._last < _WARN_EVERY_S:
                return
            self._last = now
        logger.warning(
            "observability: {signal} export to {host} failed ({detail}); "
            "data is dropped, next report in 10 min",
            signal=signal,
            host=host,
            detail=detail,
        )


class _ReportingExporter(SpanExporter):
    """Turns export failures and errors into one rate-limited warning; never raises.

    Each batch it is handed has left the queue, so it frees that many ``gate`` slots.
    """

    def __init__(
        self,
        inner: SpanExporter,
        notice: FailureNotice,
        signal: str,
        host: str,
        gate: metrics.QueueGate,
    ) -> None:
        self._inner = inner
        self._notice = notice
        self._signal = signal
        self._host = host
        self._gate = gate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self._gate.taken(len(spans))
        try:
            result = self._inner.export(spans)
        except Exception as exc:  # noqa: BLE001 — a failed export is dropped, not raised
            self._notice.report(self._signal, self._host, type(exc).__name__)
            return SpanExportResult.FAILURE
        if result is SpanExportResult.SUCCESS:
            self._notice.succeeded(self._signal)
        else:
            self._notice.report(self._signal, self._host, "rejected or unreachable")
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
            self._notice.report(self._signal, self._host, type(exc).__name__)


# --- HTTP ---------------------------------------------------------------------------------


def instrument_fastapi(app: FastAPI) -> None:
    """Make each request a server span (``http.route``) on the global provider.

    Called from the lifespan, after Starlette built its middleware stack, so the
    stack is rebuilt; the middleware order inside it does not change.
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, exclude_spans=["receive", "send"])
    app.middleware_stack = app.build_middleware_stack()


def uninstrument_fastapi(app: FastAPI) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.uninstrument_app(app)


__all__ = [
    "LOGFIRE_TOKEN_SECRET",
    "SHUTDOWN_CAP_S",
    "ExportResult",
    "FailureNotice",
    "ObservabilityHandle",
    "choose_exporter",
    "instrument_fastapi",
    "setup",
    "uninstrument_fastapi",
]
