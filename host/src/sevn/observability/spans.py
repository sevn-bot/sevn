"""The spans of one message's trace: ``job`` -> ``route.decide`` -> ``turn`` -> ``tool.<name>``.

Plan 0015 D5. A message opens a root ``job`` span; each routing step that ran is
a ``route.decide`` child. The job's W3C ``traceparent`` is stored on its row
(``jobs.trace_parent``), because the worker runs the turn in another task, and
maybe after a restart. The ``turn`` span is parented from that value, so the
turn, the model calls and the tool calls under it join the message's trace.

Tracing never changes behaviour. With no SDK provider installed the OTel API is
a no-op: spans do not record, no attribute is computed, and ``traceparent``
values are ``None``. Span names are fixed strings; ids are attributes only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import Context as TaskContext
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from sevn import __version__
from sevn.config import Settings
from sevn.errors import ConfigError
from sevn.observability.redact import content_attributes

SCOPE = "sevn"

JOB = "job"
ROUTE = "route.decide"
TURN = "turn"
TOOL_PREFIX = "tool."

SOURCE = "sevn.source"
JOB_ID = "sevn.job_id"
BOT_ID = "sevn.bot_id"
AGENT_ID = "sevn.agent_id"
TURN_ID = "sevn.turn_id"
RUNTIME = "sevn.runtime"
DECISION_ID = "sevn.decision_id"
DECISION_POINT = "sevn.decision_point"
DECISION_PATH = "sevn.decision_path"
CONFIDENCE = "sevn.confidence"
ACCEPTED = "sevn.accepted"
STOP = "sevn.stop"
COST_USD = "sevn.cost_usd"
COST_SOURCE = "sevn.cost_source"
MODEL = "gen_ai.request.model"
INPUT_TOKENS = "gen_ai.usage.input_tokens"
OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
OPERATION = "gen_ai.operation.name"
TOOL_NAME = "gen_ai.tool.name"

_PROPAGATOR = TraceContextTextMapPropagator()


@dataclass(slots=True)
class _TurnScope:
    """The recording ``turn`` span of this task, with what its children copy."""

    span: Span
    ids: dict[str, str]
    capture: bool


_job: ContextVar[Span | None] = ContextVar("sevn_job_span", default=None)
_turn: ContextVar[_TurnScope | None] = ContextVar("sevn_turn_span", default=None)


def _tracer() -> Tracer:
    """Fetched per span, so a provider installed (or swapped) later is used."""
    return trace.get_tracer(SCOPE, __version__)


def tracing_on() -> bool:
    """True when an SDK (or Logfire) tracer provider is global."""
    provider = trace.get_tracer_provider()
    return not isinstance(provider, trace.ProxyTracerProvider | trace.NoOpTracerProvider)


def capture_content() -> bool:
    """``observability.capture_content``; off when the config cannot be read."""
    try:
        return Settings.load().observability.capture_content
    except ConfigError:
        return False


def traceparent(span: Span) -> str | None:
    """The W3C ``traceparent`` a child of ``span`` uses, or ``None`` for an invalid span.

    Only the sampled flag is kept (version 00 defines no other bit).
    """
    context = span.get_span_context()
    if not context.is_valid:
        return None
    flags = "01" if context.trace_flags.sampled else "00"
    return f"00-{context.trace_id:032x}-{context.span_id:016x}-{flags}"


def parent_context(value: str | None) -> Context:
    """A context holding the remote parent in ``value``; empty when it is missing or invalid."""
    if not value:
        return Context()
    return _PROPAGATOR.extract({"traceparent": value}, context=Context())


def _ids(**ids: str | None) -> dict[str, str]:
    keys = {
        "job_id": JOB_ID,
        "bot_id": BOT_ID,
        "agent_id": AGENT_ID,
        "turn_id": TURN_ID,
    }
    return {keys[name]: value for name, value in ids.items() if value}


def _fail(span: Span, exc: BaseException) -> None:
    """Mark ``span`` failed by exception type only: a message can echo content."""
    if isinstance(exc, asyncio.CancelledError | GeneratorExit):
        return
    span.set_status(Status(StatusCode.ERROR, type(exc).__name__))


@contextmanager
def job_span(
    source: str,
    *,
    job_id: str,
    bot_id: str | None = None,
    text: str | None = None,
) -> Generator[Span]:
    """Open the root ``job`` span of one inbound message and make it current.

    Always a new root, even inside another span (a websocket request, a turn).
    ``text`` is recorded as size and hash, or scrubbed text with content capture on.
    """
    with _tracer().start_as_current_span(
        JOB,
        context=Context(),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        if span.is_recording():
            span.set_attributes({SOURCE: source, **_ids(job_id=job_id, bot_id=bot_id)})
            if text is not None:
                span.set_attributes(content_attributes(text, capture=capture_content()))
        token = _job.set(span)
        try:
            yield span
        except BaseException as exc:
            _fail(span, exc)
            raise
        finally:
            _job.reset(token)


def job_traceparent() -> str | None:
    """The ``traceparent`` to store on a job row created inside ``job_span``.

    ``None`` outside a job span, while tracing is off, and inside a task that
    merely inherited the job span (a worker pump runs its turns in their own span).
    """
    span = _job.get()
    if span is None or trace.get_current_span() is not span:
        return None
    return traceparent(span)


def detached_context() -> TaskContext:
    """A copy of the current context with no span current, for a long-lived task.

    A task copies the context it starts in. The worker's pump starts inside the
    first message's ``job`` span and then runs later jobs too, so without this
    their log records would carry that first message's trace. Each turn takes
    its parent from ``jobs.trace_parent`` instead.
    """
    context = copy_context()
    context.run(_detach)
    return context


def _detach() -> None:
    otel_context.attach(Context())
    _job.set(None)
    _turn.set(None)


@contextmanager
def route_span(
    *,
    point: str,
    path: str,
    confidence: float,
    accepted: bool,
    decision_id: str | None = None,
) -> Generator[Span]:
    """One ``route.decide`` span per recorded attempt, a child of the active span."""
    with _tracer().start_as_current_span(
        ROUTE, record_exception=False, set_status_on_exception=False
    ) as span:
        if span.is_recording():
            attributes: dict[str, str | float | bool] = {
                DECISION_POINT: point,
                DECISION_PATH: path,
                CONFIDENCE: float(confidence),
                ACCEPTED: accepted,
            }
            if decision_id:
                attributes[DECISION_ID] = decision_id
            span.set_attributes(attributes)
        try:
            yield span
        except BaseException as exc:
            _fail(span, exc)
            raise


@contextmanager
def turn_span(
    trace_parent: str | None,
    *,
    turn_id: str,
    job_id: str,
    agent_id: str,
    bot_id: str,
    runtime: str,
    model: str | None,
) -> Generator[Span]:
    """Open the ``turn`` span as a child of the job's stored ``trace_parent``.

    The current context is ignored: a missing or invalid value starts a new root
    with no links. The span is current until the block ends, so the runtime's
    own spans (model calls, Pydantic AI tools) nest under it.
    """
    with _tracer().start_as_current_span(
        TURN,
        context=parent_context(trace_parent),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        token = None
        if span.is_recording():
            ids = _ids(turn_id=turn_id, job_id=job_id, agent_id=agent_id, bot_id=bot_id)
            span.set_attributes({**ids, RUNTIME: runtime})
            if model is not None:
                span.set_attribute(MODEL, model)
            token = _turn.set(_TurnScope(span=span, ids=ids, capture=capture_content()))
        try:
            yield span
        except BaseException as exc:
            if span.is_recording():
                cancelled = isinstance(exc, asyncio.CancelledError)
                span.set_attribute(STOP, "cancelled" if cancelled else "error")
            _fail(span, exc)
            raise
        finally:
            if token is not None:
                _turn.reset(token)


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def turn_result(*, status: str, model: str | None, usage: Mapping[str, object]) -> None:
    """Copy the stored ``turns`` row onto the current ``turn`` span.

    ``usage`` is ``turns.usage``: token counts, ``cost_source`` as stored, and
    ``cost_usd`` only when it is known.
    """
    scope = _turn.get()
    if scope is None or not scope.span.is_recording():
        return
    attributes: dict[str, str | int | float] = {
        STOP: "cancelled" if status == "cancelled" else "end",
    }
    if model is not None:
        attributes[MODEL] = model
    for key, name in (("input_tokens", INPUT_TOKENS), ("output_tokens", OUTPUT_TOKENS)):
        count = _count(usage.get(key))
        if count is not None:
            attributes[name] = count
    source = usage.get("cost_source")
    if isinstance(source, str):
        attributes[COST_SOURCE] = source
    cost = usage.get("cost_usd")
    if isinstance(cost, int | float) and not isinstance(cost, bool):
        attributes[COST_USD] = float(cost)
    scope.span.set_attributes(attributes)


def _args_text(args: Mapping[str, object] | None) -> str:
    if not args:
        return ""
    return json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)


def tool_span(name: str, args: Mapping[str, object] | None = None) -> Span:
    """Start (not make current) a ``tool.<name>`` span under the current turn.

    Arguments are content: size and hash only unless content capture is on.
    Outside a recording turn this returns the invalid no-op span.
    """
    scope = _turn.get()
    if scope is None or not scope.span.is_recording():
        return trace.INVALID_SPAN
    span = _tracer().start_span(
        TOOL_PREFIX + name,
        context=trace.set_span_in_context(scope.span, Context()),
        record_exception=False,
        set_status_on_exception=False,
    )
    span.set_attributes({TOOL_NAME: name, OPERATION: "execute_tool", **scope.ids})
    span.set_attributes(content_attributes(_args_text(args), capture=scope.capture))
    return span


@dataclass(slots=True)
class ToolSpans:
    """Pairs a CLI runtime's mapped tool start and end events into ``tool.<name>`` spans.

    The events carry no call id, so calls of one tool close in start order.
    """

    _open: dict[str, list[Span]] = field(default_factory=dict[str, list[Span]])

    def start(self, name: str, args: Mapping[str, object] | None) -> None:
        self._open.setdefault(name, []).append(tool_span(name, args))

    def finish(self, name: str, *, ok: bool | None) -> None:
        started = self._open.get(name)
        if not started:
            return
        span = started.pop(0)
        if ok is False:
            span.set_status(Status(StatusCode.ERROR))
        span.end()

    def close(self) -> None:
        """End calls the runtime never finished (a cancelled or failed turn)."""
        for started in self._open.values():
            for span in started:
                span.end()
        self._open.clear()


def cli_tool_spans(runtime: str) -> ToolSpans | None:
    """Tool spans for a CLI runtime's turn; ``None`` for Pydantic AI or an unrecorded turn.

    Pydantic AI turns get their ``execute_tool`` spans from its own instrumentation.
    """
    if runtime == "pydantic_ai":
        return None
    scope = _turn.get()
    if scope is None or not scope.span.is_recording():
        return None
    return ToolSpans()


__all__ = [
    "SCOPE",
    "ToolSpans",
    "capture_content",
    "cli_tool_spans",
    "detached_context",
    "job_span",
    "job_traceparent",
    "parent_context",
    "route_span",
    "tool_span",
    "traceparent",
    "tracing_on",
    "turn_result",
    "turn_span",
]
