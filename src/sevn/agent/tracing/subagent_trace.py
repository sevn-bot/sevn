"""Sub-agent OTel spans and mission telemetry trace events (D12/W5).

Module: sevn.agent.tracing.subagent_trace
Depends: opentelemetry-sdk, sevn.agent.subagents.models, sevn.agent.tracing.emit,
    sevn.agent.tracing.sink, sevn.agent.tracing.trace_event_bridge

Exports:
    SubAgentPrometheusCounts — in-process scrape snapshot for Prometheus.
    SubAgentTraceEmitter — OTel ``sevn.subagent`` spans + mission telemetry rows.
    build_subagent_trace_hook — factory for gateway registry wiring.
    bind_subagent_turn_context — bind turn ids without a ``with`` block.
    reset_subagent_turn_context — restore tokens from bind.
    subagent_trace_scope — bind turn correlation ids for parent span linkage.
    reset_subagent_trace_for_tests — clear context + open spans (test isolation).

Examples:
    >>> from sevn.agent.tracing.subagent_trace import SubAgentPrometheusCounts
    >>> isinstance(SubAgentPrometheusCounts().total_by_status, dict)
    True
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import time_ns
from typing import TYPE_CHECKING, Literal

from loguru import logger
from opentelemetry import context, trace
from opentelemetry.trace import NonRecordingSpan, Span

from sevn.agent.tracing.emit import _emit as emit_trace_subscribers
from sevn.agent.tracing.otel_sink import _otel_status
from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent, current_sink
from sevn.agent.tracing.trace_event_bridge import get_trace_event_bridge

if TYPE_CHECKING:
    from sevn.agent.subagents.models import SubAgentRun
    from sevn.agent.subagents.registry import SubAgentRegistry

TracePhase = Literal["registered", "running", "done", "failed", "killed", "orphaned"]
TraceHook = Callable[["SubAgentRun", TracePhase], Awaitable[None]]

_turn_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sevn_subagent_turn_id",
    default=None,
)
_turn_span_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sevn_subagent_turn_span_id",
    default=None,
)

_open_spans_lock = threading.Lock()
_open_spans_global: dict[str, Span] = {}


def bind_subagent_turn_context(
    *,
    turn_id: str,
    turn_span_id: str | None,
) -> tuple[contextvars.Token[str | None], contextvars.Token[str | None]]:
    """Bind turn ids for sub-agent parent span linkage without a ``with`` block.

    Args:
        turn_id (str): Gateway turn / correlation id.
        turn_span_id (str | None): ``gateway.turn.start`` span id when known.

    Returns:
        tuple[contextvars.Token, contextvars.Token]: Tokens for :func:`reset_subagent_turn_context`.

    Examples:
        >>> tokens = bind_subagent_turn_context(turn_id="t1", turn_span_id="root")
        >>> isinstance(tokens, tuple)
        True
    """
    return _turn_id_ctx.set(turn_id), _turn_span_id_ctx.set(turn_span_id)


def reset_subagent_turn_context(
    tokens: tuple[contextvars.Token[str | None], contextvars.Token[str | None]],
) -> None:
    """Restore turn context vars previously bound by :func:`bind_subagent_turn_context`.

    Args:
        tokens (tuple[contextvars.Token, contextvars.Token]): Tokens from bind.

    Examples:
        >>> reset_subagent_turn_context(bind_subagent_turn_context(turn_id="t", turn_span_id=None)) is None
        True
    """
    _turn_id_ctx.reset(tokens[0])
    _turn_span_id_ctx.reset(tokens[1])


@contextmanager
def subagent_trace_scope(*, turn_id: str, turn_span_id: str | None) -> Generator[None, None, None]:
    """Bind turn correlation ids used to parent level-1 sub-agent spans (W5.1).

    Args:
        turn_id (str): Gateway turn / correlation id.
        turn_span_id (str | None): ``gateway.turn.start`` span id when known.

    Yields:
        None: While the turn trace context is active.

    Returns:
        None: Implicit after context exit.

    Examples:
        >>> with subagent_trace_scope(turn_id="t1", turn_span_id="root"):
        ...     pass
    """
    turn_token = _turn_id_ctx.set(turn_id)
    span_token = _turn_span_id_ctx.set(turn_span_id)
    try:
        yield
    finally:
        _turn_id_ctx.reset(turn_token)
        _turn_span_id_ctx.reset(span_token)


@dataclass
class SubAgentPrometheusCounts:
    """In-process scrape snapshot for ``sevn_subagents_*`` Prometheus series (W5.3)."""

    running: dict[tuple[int, str], int] = field(default_factory=dict)
    total_by_status: dict[str, int] = field(
        default_factory=lambda: {"done": 0, "failed": 0, "killed": 0},
    )


def _subagent_span_id(run: SubAgentRun) -> str:
    """Return the stable OTel span id for one sub-agent run.

    Args:
        run (SubAgentRun): Registry row.

    Returns:
        str: ``run.trace_id`` when set, else ``sub-<id>``.

    Examples:
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> run = SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None, parent_id=None,
        ...     session_id="s", channel="c", task_summary="t",
        ...     status=SubAgentStatus.PENDING, started_at=1, finished_at=None, trace_id="sub-a1f3",
        ... )
        >>> _subagent_span_id(run)
        'sub-a1f3'
    """
    return run.trace_id or f"sub-{run.id}"


def _subagent_attrs(run: SubAgentRun) -> dict[str, object]:
    """Build mission/OTel attribute payload for one sub-agent run (D12).

    Args:
        run (SubAgentRun): Registry row.

    Returns:
        dict[str, object]: Normalized ``subagent.*`` attrs.

    Examples:
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> attrs = _subagent_attrs(SubAgentRun(
        ...     id="a1f3", level=2, role="tier_b", specialist="media_generator",
        ...     parent_id="p1", session_id="s", channel="c", task_summary="t",
        ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id="sub-a1f3",
        ... ))
        >>> attrs["subagent.level"]
        2
    """
    attrs: dict[str, object] = {
        "subagent.id": run.id,
        "subagent.level": run.level,
        "subagent.role": run.role,
        "subagent.session_id": run.session_id,
        "subagent.channel": run.channel,
        "subagent.task_summary": run.task_summary,
    }
    if run.specialist:
        attrs["subagent.specialist"] = run.specialist
    if run.parent_id:
        attrs["subagent.parent_id"] = run.parent_id
    return attrs


class SubAgentTraceEmitter:
    """Emit ``sevn.subagent`` OTel spans and mission telemetry for registry rows (W5)."""

    def __init__(
        self,
        registry: SubAgentRegistry,
        *,
        prometheus: SubAgentPrometheusCounts | None = None,
    ) -> None:
        """Bind one emitter to a registry for parent-span lookup and gauge refresh.

        Args:
            registry (SubAgentRegistry): Backing registry (parent ``trace_id`` lookup).
            prometheus (SubAgentPrometheusCounts | None): Mutable scrape snapshot;
                a fresh instance is created when omitted.

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> isinstance(SubAgentTraceEmitter(SubAgentRegistry()), SubAgentTraceEmitter)
            True
        """
        self._registry = registry
        self._prometheus = prometheus or SubAgentPrometheusCounts()
        self._tracer = trace.get_tracer("sevn.agent.tracing.subagent_trace")

    @property
    def prometheus_counts(self) -> SubAgentPrometheusCounts:
        """Return the mutable Prometheus snapshot updated by this emitter.

        Returns:
            SubAgentPrometheusCounts: Running gauge + terminal counters.

        Examples:
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> SubAgentTraceEmitter(SubAgentRegistry()).prometheus_counts.total_by_status["done"]
            0
        """
        return self._prometheus

    async def __call__(self, run: SubAgentRun, phase: str) -> None:
        """Dispatch one lifecycle phase (registry :data:`TraceHook` entry point).

        Args:
            run (SubAgentRun): Row after the triggering transition.
            phase (str): Lifecycle phase that fired the hook.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SubAgentTraceEmitter.__call__)
            True
        """
        try:
            await self._handle(run, phase)  # type: ignore[arg-type]
        except Exception:
            logger.bind(subagent_id=run.id, phase=phase).exception("subagent trace hook failed")

    async def _handle(self, run: SubAgentRun, phase: TracePhase) -> None:
        """Route one lifecycle phase to telemetry and/or OTel span handlers.

        Args:
            run (SubAgentRun): Row after the triggering transition.
            phase (TracePhase): Lifecycle phase that fired the hook.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SubAgentTraceEmitter._handle)
            True
        """
        if phase == "registered":
            await self._emit_telemetry(run, kind="subagent_spawned", status="pending")
            await self._refresh_running_gauge()
            return
        if phase == "running":
            await self._start_otel_span(run)
            await self._refresh_running_gauge()
            return
        if phase == "killed":
            await self._finish(run, terminal_status="killed", telemetry_kind="subagent_killed")
            return
        if phase in ("done", "failed", "orphaned"):
            await self._finish(
                run,
                terminal_status=phase,
                telemetry_kind="subagent_finished",
            )
            return

    async def _resolve_parent_span_id(self, run: SubAgentRun) -> str | None:
        """Resolve the OTel parent span id for one sub-agent run.

        Args:
            run (SubAgentRun): Child or level-1 row.

        Returns:
            str | None: Parent sub-agent span id, turn root span id, or ``None``.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> from sevn.agent.subagents.registry import SubAgentRegistry
            >>> async def _demo() -> str | None:
            ...     emitter = SubAgentTraceEmitter(SubAgentRegistry())
            ...     run = SubAgentRun(
            ...         id="a1", level=1, role="tier_b", specialist=None, parent_id=None,
            ...         session_id="s", channel="c", task_summary="t",
            ...         status=SubAgentStatus.PENDING, started_at=1, finished_at=None,
            ...         trace_id="sub-a1",
            ...     )
            ...     return await emitter._resolve_parent_span_id(run)
            >>> asyncio.run(_demo()) is None
            True
        """
        if run.parent_id:
            parent = await self._registry.get(run.parent_id)
            if parent is not None and parent.trace_id:
                return parent.trace_id
        turn_span = _turn_span_id_ctx.get()
        if turn_span:
            return turn_span
        return None

    def _parent_context(self, parent_span_id: str | None) -> context.Context:
        """Build OTel parent context from a sevn parent span id when open.

        Args:
            parent_span_id (str | None): Parent span id from registry or turn root.

        Returns:
            context.Context: OTel context for span parenting.

        Examples:
            >>> emitter = SubAgentTraceEmitter.__new__(SubAgentTraceEmitter)
            >>> emitter._parent_context(None) is not None
            True
        """
        if not parent_span_id:
            return context.get_current()
        bridge = get_trace_event_bridge()
        if bridge is not None:
            with bridge._lock:
                span_context = bridge._span_contexts.get(parent_span_id)
            if span_context is not None and span_context.is_valid:
                return trace.set_span_in_context(NonRecordingSpan(span_context))
        with _open_spans_lock:
            span = _open_spans_global.get(parent_span_id)
        if span is not None:
            ctx = span.get_span_context()
            if ctx.is_valid:
                return trace.set_span_in_context(NonRecordingSpan(ctx))
        return context.get_current()

    async def _start_otel_span(self, run: SubAgentRun) -> None:
        """Open one long-lived ``sevn.subagent`` OTel span for a running row.

        Args:
            run (SubAgentRun): ``running`` registry row.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SubAgentTraceEmitter._start_otel_span)
            True
        """
        span_id = _subagent_span_id(run)
        parent_span_id = await self._resolve_parent_span_id(run)
        parent_ctx = self._parent_context(parent_span_id)
        token = context.attach(parent_ctx)
        try:
            attrs = _subagent_attrs(run)
            flat = {
                f"sevn.{key}" if not str(key).startswith("sevn.") else str(key): (
                    value if isinstance(value, (str, int, float, bool)) else str(value)
                )
                for key, value in attrs.items()
            }
            span = self._tracer.start_span(
                name="sevn.subagent",
                start_time=run.started_at,
                attributes=flat,
            )
            span.set_status(_otel_status("running"))
        finally:
            context.detach(token)
        with _open_spans_lock:
            _open_spans_global[span_id] = span

    async def _finish(
        self,
        run: SubAgentRun,
        *,
        terminal_status: str,
        telemetry_kind: str,
    ) -> None:
        """End the OTel span and emit a terminal mission telemetry row.

        Args:
            run (SubAgentRun): Terminal registry row.
            terminal_status (str): Final status label for attrs/counters.
            telemetry_kind (str): ``subagent_finished`` or ``subagent_killed``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SubAgentTraceEmitter._finish)
            True
        """
        span_id = _subagent_span_id(run)
        with _open_spans_lock:
            span = _open_spans_global.pop(span_id, None)
        end_ns = run.finished_at if run.finished_at is not None else time_ns()
        if span is not None:
            span.set_status(_otel_status(terminal_status))
            span.end(end_time=end_ns)
        await self._emit_telemetry(run, kind=telemetry_kind, status=terminal_status)
        if terminal_status in self._prometheus.total_by_status:
            self._prometheus.total_by_status[terminal_status] += 1
        await self._refresh_running_gauge()

    async def _emit_telemetry(self, run: SubAgentRun, *, kind: str, status: str) -> None:
        """Emit one mission telemetry :class:`~sevn.agent.tracing.sink.TraceEvent`.

        Args:
            run (SubAgentRun): Registry row for the event.
            kind (str): ``subagent_spawned`` / ``subagent_finished`` / ``subagent_killed``.
            status (str): Row status at emit time.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SubAgentTraceEmitter._emit_telemetry)
            True
        """
        turn_id = _turn_id_ctx.get() or SYSTEM_TURN_ID
        parent_span_id = await self._resolve_parent_span_id(run)
        now = time_ns()
        attrs = _subagent_attrs(run)
        attrs["subagent.status"] = status
        event = TraceEvent(
            kind=kind,
            span_id=_subagent_span_id(run),
            parent_span_id=parent_span_id,
            session_id=run.session_id,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=run.started_at,
            ts_end_ns=now,
            status=status,
            attrs=attrs,
        )
        sink = current_sink()
        if sink is not None:
            with contextlib.suppress(Exception):
                await sink.emit(event)
        await emit_trace_subscribers(event)

    async def _refresh_running_gauge(self) -> None:
        """Recompute ``sevn_subagents_running`` snapshot from the registry map.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SubAgentTraceEmitter._refresh_running_gauge)
            True
        """
        counts = await self._registry.counts()
        self._prometheus.running = dict(counts)


def build_subagent_trace_hook(
    registry: SubAgentRegistry,
    *,
    prometheus: SubAgentPrometheusCounts | None = None,
) -> Callable[[SubAgentRun, str], Awaitable[None]]:
    """Return a registry :data:`TraceHook` wired to :class:`SubAgentTraceEmitter`.

    Args:
        registry (SubAgentRegistry): Backing registry.
        prometheus (SubAgentPrometheusCounts | None): Optional shared Prometheus snapshot.

    Returns:
        TraceHook: Async callable for :class:`~sevn.agent.subagents.registry.SubAgentRegistry`.

    Examples:
        >>> from sevn.agent.subagents.registry import SubAgentRegistry
        >>> callable(build_subagent_trace_hook(SubAgentRegistry()))
        True
    """
    return SubAgentTraceEmitter(registry, prometheus=prometheus)


def reset_subagent_trace_for_tests() -> None:
    """Clear turn context vars and any open sub-agent OTel spans (test isolation).

    Examples:
        >>> reset_subagent_trace_for_tests() is None
        True
    """
    _turn_id_ctx.set(None)
    _turn_span_id_ctx.set(None)
    with _open_spans_lock:
        for span in list(_open_spans_global.values()):
            with contextlib.suppress(Exception):
                span.end()
        _open_spans_global.clear()


__all__ = [
    "SubAgentPrometheusCounts",
    "SubAgentTraceEmitter",
    "TraceHook",
    "TracePhase",
    "bind_subagent_turn_context",
    "build_subagent_trace_hook",
    "reset_subagent_trace_for_tests",
    "reset_subagent_turn_context",
    "subagent_trace_scope",
]
