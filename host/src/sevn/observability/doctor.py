"""``sevn doctor`` observability fields and ``sevn traces test`` (plan 0015 D11).

Nothing here prints. The CLI turns the results into output, and no field holds a
header value or a token: the exporter is named by its preset or endpoint host.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from opentelemetry import trace

from sevn.config import Settings
from sevn.identity import HostIdentity, load_or_create
from sevn.observability.presets import resolve
from sevn.observability.setup import SHUTDOWN_CAP_S, choose_exporter, setup
from sevn.paths import Paths
from sevn.secrets.backends import open_backend
from sevn.secrets.registry import register

TEST_SPAN = "sevn.test"
CANARY_ATTRIBUTE = "sevn.canary"
# The canary is registered under this name, so it exports as «redacted:traces/canary».
CANARY_SECRET = "traces/canary"  # noqa: S105 — a secret name, not a value


@dataclass(frozen=True, slots=True)
class SpanCheck:
    """What ``send_test_span`` did. ``problem`` is empty when the collector accepted it."""

    trace_id: str
    problem: str = ""

    @property
    def ok(self) -> bool:
        return self.problem == ""


def exporter_label(settings: Settings) -> str:
    """``none``, ``logfire``, or ``otlp:<preset or endpoint host>``."""
    chosen = choose_exporter(settings)
    if chosen != "otlp":
        return chosen
    obs = settings.observability
    if obs.preset:
        return f"otlp:{obs.preset}"
    endpoint = resolve(obs).traces_endpoint
    try:
        host = urlsplit(endpoint).hostname
    except ValueError:
        host = None
    return f"otlp:{host or 'unset'}"


def doctor_fields(settings: Settings, *, check: bool) -> dict[str, str]:
    """The observability keys ``sevn doctor`` adds; ``check`` sends a test span."""
    fields = {
        "observability_exporter": exporter_label(settings),
        "observability_content": "on" if settings.observability.capture_content else "off",
    }
    if check:
        if choose_exporter(settings) == "none":
            fields["observability_check"] = "off"
        else:
            sent = send_test_span(settings)
            fields["observability_check"] = "ok" if sent.ok else sent.problem
    return fields


def send_test_span(settings: Settings) -> SpanCheck:
    """Export one ``sevn.test`` span carrying a registered canary, then flush.

    The canary is a fresh value registered as a secret, so the exported attribute
    must read ``«redacted:traces/canary»``. Off or failed export is a ``problem``.
    """
    chosen = choose_exporter(settings)
    if chosen == "none":
        return SpanCheck(
            trace_id="",
            problem="observability exporter is none: set [observability] exporter "
            "or store the secret logfire/token",
        )
    try:
        identity = _identity(settings)
    except Exception as exc:  # noqa: BLE001 — reported to the operator, not raised
        return SpanCheck(trace_id="", problem=f"failed: host identity ({type(exc).__name__})")
    handle = setup(settings, identity)
    if handle.exporter == "none":
        return SpanCheck(
            trace_id="", problem=f"failed: the {chosen} exporter did not start (see the warning)"
        )
    canary = secrets.token_urlsafe(24)
    register(CANARY_SECRET, canary)
    tracer = trace.get_tracer("sevn.observability")
    with tracer.start_as_current_span(TEST_SPAN, attributes={CANARY_ATTRIBUTE: canary}) as span:
        context = span.get_span_context()
    trace_id = trace.format_trace_id(context.trace_id)
    handle.shutdown()
    if not context.trace_flags.sampled:
        return SpanCheck(
            trace_id=trace_id, problem="failed: the test span was sampled out (sample_ratio)"
        )
    result = handle.last_export("traces")
    if result is None:
        return SpanCheck(
            trace_id=trace_id,
            problem=f"failed: no answer from the collector within {SHUTDOWN_CAP_S:.0f} s",
        )
    if not result.ok:
        return SpanCheck(
            trace_id=trace_id,
            problem=f"failed: traces export to {exporter_label(settings)} ({result.detail})",
        )
    return SpanCheck(trace_id=trace_id)


def _identity(settings: Settings) -> HostIdentity:
    return load_or_create(open_backend(settings, Paths.from_env()))


__all__ = [
    "CANARY_ATTRIBUTE",
    "CANARY_SECRET",
    "TEST_SPAN",
    "SpanCheck",
    "doctor_fields",
    "exporter_label",
    "send_test_span",
]
