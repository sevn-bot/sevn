"""Host gauges as OTel metrics (plan 0015 D9) and the dropped-telemetry counter (D12).

The gauges are observable: the SDK reader calls them on its own thread every
``INTERVAL_S``, so they report the last ``sample()`` instead of touching the
database there. The host runs ``run()`` while an exporter is on; it samples
every ``INTERVAL_S``, which also caches the Ollama probe for that long.

- ``sevn.jobs.queued``: queued jobs per bot (the only attribute is ``sevn.bot_id``);
- ``sevn.turns.running``: turns in ``running``;
- ``sevn.agents.open``: agents in ``running``, ``waiting`` or ``idle``;
- ``sevn.ollama.reachable``: 1 when ``SEVN_OLLAMA_URL`` answers, else 0.

``sevn.otel.dropped`` counts spans and log records the batch processors drop
because their queue is full (attribute ``sevn.signal``).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from opentelemetry.metrics import CallbackOptions, Counter, Observation, set_meter_provider
from opentelemetry.sdk.metrics import Counter as SdkCounter
from opentelemetry.sdk.metrics import Histogram, MeterProvider, ObservableCounter
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    MetricExporter,
    MetricExportResult,
    MetricsData,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from sqlalchemy import and_, func, select

from sevn import __version__
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow

SCOPE = "sevn"
INTERVAL_S = 60.0
JOBS_QUEUED = "sevn.jobs.queued"
TURNS_RUNNING = "sevn.turns.running"
AGENTS_OPEN = "sevn.agents.open"
OLLAMA_REACHABLE = "sevn.ollama.reachable"
OTEL_DROPPED = "sevn.otel.dropped"
BOT_ID = "sevn.bot_id"
SIGNAL = "sevn.signal"

# The agent statuses ``sevn.domain.agents`` counts as open.
_OPEN_AGENTS = ("running", "waiting", "idle")
_OLLAMA_TIMEOUT_S = 2.0
# Datadog's intake takes delta sums and histograms only; Logfire prefers them too.
TEMPORALITY: dict[type, AggregationTemporality] = {
    SdkCounter: AggregationTemporality.DELTA,
    ObservableCounter: AggregationTemporality.DELTA,
    Histogram: AggregationTemporality.DELTA,
}
# The batch processors log this (per item) when their queue is full.
_SDK_LOGGER = "opentelemetry.sdk._shared_internal"
_QUEUE_FULL = "Queue full, dropping %s."

type FailureReport = Callable[[str], None]
type GaugeCallback = Callable[[CallbackOptions], Iterable[Observation]]


@dataclass(frozen=True, slots=True)
class HostSample:
    """One reading of every gauge."""

    queued: Mapping[str, int] = field(default_factory=dict[str, int])
    running_turns: int = 0
    open_agents: int = 0
    ollama_reachable: int = 0


class _Latest:
    """The last sample, read by the gauge callbacks on the reader's thread."""

    def __init__(self) -> None:
        self.sample: HostSample | None = None


_latest = _Latest()


async def sample() -> HostSample:
    """Read every gauge now, including the Ollama probe; the next export reports it."""
    async with open_session() as session:
        rows = await session.execute(
            select(BotRow.id, func.count(JobRow.id))
            .outerjoin(JobRow, and_(JobRow.to_bot_id == BotRow.id, JobRow.status == "queued"))
            .group_by(BotRow.id)
        )
        queued = {str(bot_id): int(count) for bot_id, count in rows.all()}
        running = await session.scalar(
            select(func.count()).select_from(TurnRow).where(TurnRow.status == "running")
        )
        agents = await session.scalar(
            select(func.count()).select_from(AgentRow).where(AgentRow.status.in_(_OPEN_AGENTS))
        )
    reading = HostSample(
        queued=queued,
        running_turns=int(running or 0),
        open_agents=int(agents or 0),
        ollama_reachable=await _ollama_reachable(),
    )
    _latest.sample = reading
    return reading


async def run(interval_s: float = INTERVAL_S) -> None:
    """Sample every ``interval_s`` until cancelled. A failed sample is skipped."""
    while True:
        try:
            await sample()
        except Exception as exc:  # noqa: BLE001 — metrics must never stop the host
            logger.debug(
                "observability: host metrics sample failed ({kind})", kind=type(exc).__name__
            )
        await asyncio.sleep(interval_s)


async def _ollama_reachable() -> int:
    url = os.environ.get("SEVN_OLLAMA_URL", "").strip().rstrip("/")
    if url == "":
        return 0
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_TIMEOUT_S) as client:
            response = await client.get(f"{url}/api/tags")
    except httpx.HTTPError:
        return 0
    return 1 if response.status_code < 400 else 0


# --- instruments --------------------------------------------------------------------


def _queued(_options: CallbackOptions) -> Iterable[Observation]:
    reading = _latest.sample
    if reading is None:
        return []
    return [Observation(count, {BOT_ID: bot_id}) for bot_id, count in reading.queued.items()]


def _single(read: Callable[[HostSample], int]) -> GaugeCallback:
    def callback(_options: CallbackOptions) -> Iterable[Observation]:
        reading = _latest.sample
        return [] if reading is None else [Observation(read(reading))]

    return callback


class _QueueFullFilter(logging.Filter):
    """Counts the batch processors' per-item "queue full" lines, and hides them (D12)."""

    def __init__(self, counter: Counter, report: FailureReport) -> None:
        super().__init__()
        self._counter = counter
        self._report = report

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg != _QUEUE_FULL:
            return True
        args = record.args
        signal = str(args[0]).lower() if isinstance(args, tuple) and args else "unknown"
        self._counter.add(1, {SIGNAL: signal})
        self._report(f"{signal} queue full")
        return False


class MetricExport:
    """The installed provider and drop counter. ``close`` exports the last reading."""

    def __init__(self, provider: MeterProvider, drop_filter: _QueueFullFilter) -> None:
        self.provider = provider
        self._filter = drop_filter

    def close(self) -> None:
        logging.getLogger(_SDK_LOGGER).removeFilter(self._filter)
        self.provider.shutdown()


def install(
    exporter: MetricExporter,
    resource: Resource,
    report: FailureReport,
    *,
    export_timeout_s: float,
    drop_report: FailureReport,
) -> MetricExport:
    """A global ``MeterProvider`` exporting the host gauges every ``INTERVAL_S``."""
    reader = PeriodicExportingMetricReader(
        _ReportingMetricExporter(exporter, report),
        export_interval_millis=INTERVAL_S * 1000,
        export_timeout_millis=export_timeout_s * 1000,
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    meter = provider.get_meter(SCOPE, __version__)
    meter.create_observable_gauge(
        JOBS_QUEUED, callbacks=[_queued], unit="{job}", description="Queued jobs per bot"
    )
    meter.create_observable_gauge(
        TURNS_RUNNING,
        callbacks=[_single(lambda reading: reading.running_turns)],
        unit="{turn}",
        description="Turns running now",
    )
    meter.create_observable_gauge(
        AGENTS_OPEN,
        callbacks=[_single(lambda reading: reading.open_agents)],
        unit="{agent}",
        description="Agents running, waiting or idle",
    )
    meter.create_observable_gauge(
        OLLAMA_REACHABLE,
        callbacks=[_single(lambda reading: reading.ollama_reachable)],
        unit="1",
        description="1 when SEVN_OLLAMA_URL answers",
    )
    dropped = meter.create_counter(
        OTEL_DROPPED, unit="{item}", description="Telemetry dropped on a full export queue"
    )
    drop_filter = _QueueFullFilter(dropped, drop_report)
    logging.getLogger(_SDK_LOGGER).addFilter(drop_filter)
    # A sample from an earlier provider must not leak into this one's first export.
    _latest.sample = None
    set_meter_provider(provider)
    return MetricExport(provider, drop_filter)


def otlp_exporter(
    protocol: str,
    endpoint: str,
    headers: Mapping[str, str],
    *,
    timeout_s: float,
    gzip: bool = False,
) -> MetricExporter:
    """The OTLP metric exporter for ``protocol``. An empty ``headers`` defers to the OTEL env."""
    resolved = dict(headers) or None
    if protocol == "grpc":
        from urllib.parse import urlsplit

        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter as GrpcMetricExporter,
        )

        return GrpcMetricExporter(
            endpoint=endpoint,
            insecure=urlsplit(endpoint).scheme == "http",
            headers=resolved,
            timeout=timeout_s,
            preferred_temporality=TEMPORALITY,
        )
    from opentelemetry.exporter.otlp.proto.http import Compression
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    return OTLPMetricExporter(
        endpoint=endpoint,
        headers=resolved,
        timeout=timeout_s,
        compression=Compression.Gzip if gzip else None,
        preferred_temporality=TEMPORALITY,
    )


class _Exporter(Protocol):
    """The ``MetricExporter`` calls the wrapper makes (no pass-through ``**kwargs``)."""

    def export(
        self, metrics_data: MetricsData, timeout_millis: float = 10_000
    ) -> MetricExportResult: ...

    def force_flush(self, timeout_millis: float = 10_000) -> bool: ...

    def shutdown(self, timeout_millis: float = 30_000) -> None: ...


class _ReportingMetricExporter(MetricExporter):
    """Turns a failed export into one report; never raises."""

    def __init__(self, inner: _Exporter, report: FailureReport) -> None:
        super().__init__(preferred_temporality=TEMPORALITY)
        self._inner = inner
        self._report = report

    def export(
        self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: object
    ) -> MetricExportResult:
        try:
            result = self._inner.export(metrics_data, timeout_millis=timeout_millis)
        except Exception as exc:  # noqa: BLE001 — a failed export is dropped, not raised
            self._report(type(exc).__name__)
            return MetricExportResult.FAILURE
        if result is not MetricExportResult.SUCCESS:
            self._report("rejected or unreachable")
        return result

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        try:
            return self._inner.force_flush(timeout_millis)
        except Exception:  # noqa: BLE001 — flushing telemetry must not raise
            return False

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: object) -> None:
        try:
            self._inner.shutdown(timeout_millis=timeout_millis)
        except Exception as exc:  # noqa: BLE001 — shutdown must not raise
            self._report(type(exc).__name__)


__all__ = [
    "AGENTS_OPEN",
    "INTERVAL_S",
    "JOBS_QUEUED",
    "OLLAMA_REACHABLE",
    "OTEL_DROPPED",
    "TURNS_RUNNING",
    "HostSample",
    "MetricExport",
    "install",
    "otlp_exporter",
    "run",
    "sample",
]
