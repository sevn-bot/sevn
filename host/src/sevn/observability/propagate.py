"""Trace context and collector settings for child CLI runtimes (plan 0015 D6).

A CLI runtime (Claude Code, and the codex / ACP spawns of plan 0030) gets the
turn's W3C ``TRACEPARENT`` so its own spans can nest under the sevn ``turn``.
It is told where to send its own telemetry only when sevn exports to a loopback
collector, because a CLI and every tool it runs can read its env: an export
credential (the Logfire token, a Datadog API key, any ``headers`` value) never
enters a child env.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import Span

from sevn.config import Settings
from sevn.errors import ConfigError
from sevn.observability.presets import resolve
from sevn.observability.spans import traceparent

TRACEPARENT = "TRACEPARENT"
TRACESTATE = "TRACESTATE"
OTLP_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
OTLP_PROTOCOL = "OTEL_EXPORTER_OTLP_PROTOCOL"
SERVICE_NAME = "OTEL_SERVICE_NAME"
# Claude Code exports metrics and log events only with this switch (W0.4).
CLAUDE_TELEMETRY = "CLAUDE_CODE_ENABLE_TELEMETRY"


def child_env(
    runtime: str, span: Span | None = None, *, settings: Settings | None = None
) -> dict[str, str]:
    """The env keys to add to ``runtime``'s child process; nothing else.

    ``span`` defaults to the current span. ``TRACEPARENT`` (and ``TRACESTATE``
    when set) come from a valid span. The ``OTEL_*`` keys, and Claude Code's
    telemetry switch, are added only for a loopback collector on the ``otlp``
    exporter. ``settings=None`` loads them; a config that cannot be read adds
    the trace context only.
    """
    env = _trace_context(trace.get_current_span() if span is None else span)
    if settings is None:
        try:
            settings = Settings.load()
        except ConfigError:
            return env
    env.update(_collector_env(runtime, settings))
    return env


def _trace_context(span: Span) -> dict[str, str]:
    parent = traceparent(span)
    if parent is None:
        return {}
    env = {TRACEPARENT: parent}
    state = span.get_span_context().trace_state.to_header()
    if state:
        env[TRACESTATE] = state
    return env


def _collector_env(runtime: str, settings: Settings) -> dict[str, str]:
    obs = settings.observability
    # Unset means Logfire or off; neither is a collector a child can reach.
    if obs.exporter != "otlp":
        return {}
    target = resolve(obs)
    if not target.loopback:
        return {}
    env = {
        OTLP_ENDPOINT: target.base_endpoint,
        OTLP_PROTOCOL: target.protocol,
        SERVICE_NAME: f"sevn-cli-{runtime}",
    }
    if runtime == "claude":
        env[CLAUDE_TELEMETRY] = "1"
    return env


__all__ = [
    "CLAUDE_TELEMETRY",
    "OTLP_ENDPOINT",
    "OTLP_PROTOCOL",
    "SERVICE_NAME",
    "TRACEPARENT",
    "TRACESTATE",
    "child_env",
]
