"""Where OTLP data goes: endpoints and headers per signal (plan 0015 D1, D4).

``resolve`` is pure: it reads no secret and opens no connection. Header values
stay as written, so a ``secret://`` reference is still a reference here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from sevn.config import ObservabilitySettings, OtlpProtocol

DATADOG_KEY_HEADER = "dd-api-key"
DATADOG_KEY_REF = "secret://datadog/api_key"
# Datadog routes OTLP traces carrying this header into LLM Observability (W0.3).
_LLMOBS_HEADER = ("dd-otlp-source", "llmobs")

_AGENT_HTTP = "http://localhost:4318"
_AGENT_GRPC = "http://localhost:4317"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_OTEL_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"


@dataclass(frozen=True, slots=True)
class ExportTarget:
    """Endpoints and (unresolved) headers for traces, logs and metrics."""

    protocol: OtlpProtocol
    base_endpoint: str
    traces_endpoint: str
    logs_endpoint: str
    metrics_endpoint: str
    trace_headers: dict[str, str] = field(default_factory=dict[str, str])
    log_headers: dict[str, str] = field(default_factory=dict[str, str])
    metric_headers: dict[str, str] = field(default_factory=dict[str, str])
    loopback: bool = False


def resolve(obs: ObservabilitySettings) -> ExportTarget:
    """Return the OTLP target ``obs`` describes (the ``otlp`` exporter's view)."""
    if obs.preset == "datadog-agentless":
        return _agentless(obs)
    if obs.preset == "datadog-agent":
        default = _AGENT_GRPC if obs.protocol == "grpc" else _AGENT_HTTP
        return _target(obs.protocol, obs.endpoint or default, dict(obs.headers))
    base = obs.endpoint
    if base == "" and obs.exporter == "otlp":
        base = os.environ.get(_OTEL_ENDPOINT_ENV, "").strip()
    return _target(obs.protocol, base, dict(obs.headers))


def _agentless(obs: ObservabilitySettings) -> ExportTarget:
    base = obs.endpoint or f"https://otlp.{obs.datadog_site}"
    key_ref = obs.headers.get(DATADOG_KEY_HEADER, DATADOG_KEY_REF)
    common = {**obs.headers, DATADOG_KEY_HEADER: key_ref}
    target = _target("http/protobuf", base, common)
    name, value = _LLMOBS_HEADER
    return ExportTarget(
        protocol=target.protocol,
        base_endpoint=target.base_endpoint,
        traces_endpoint=target.traces_endpoint,
        logs_endpoint=target.logs_endpoint,
        metrics_endpoint=target.metrics_endpoint,
        trace_headers={**common, name: value},
        log_headers=dict(common),
        metric_headers=dict(common),
        loopback=target.loopback,
    )


def _target(protocol: OtlpProtocol, base: str, headers: dict[str, str]) -> ExportTarget:
    base = base.strip().rstrip("/")
    if base == "" or protocol == "grpc":
        traces = logs = metrics = base
    else:
        traces, logs, metrics = (f"{base}/v1/{signal}" for signal in ("traces", "logs", "metrics"))
    return ExportTarget(
        protocol=protocol,
        base_endpoint=base,
        traces_endpoint=traces,
        logs_endpoint=logs,
        metrics_endpoint=metrics,
        trace_headers=dict(headers),
        log_headers=dict(headers),
        metric_headers=dict(headers),
        loopback=is_loopback(base),
    )


def is_loopback(endpoint: str) -> bool:
    """True when ``endpoint``'s host is ``localhost``, ``127.0.0.1`` or ``::1``."""
    if endpoint == "":
        return False
    try:
        host = urlsplit(endpoint).hostname
    except ValueError:
        return False
    return host is not None and host.lower() in _LOOPBACK_HOSTS


__all__ = ["DATADOG_KEY_HEADER", "DATADOG_KEY_REF", "ExportTarget", "is_loopback", "resolve"]
