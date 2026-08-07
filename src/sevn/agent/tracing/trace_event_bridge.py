"""Bridge sevn ``TraceEvent`` rows onto the shared OTel ``TracerProvider``.

Module: sevn.agent.tracing.trace_event_bridge
Depends: opentelemetry-sdk, sevn.agent.tracing.otel_sink, sevn.agent.tracing.sink
Exports:
    TraceEventOtelBridge — ``TraceSink`` mapping product spans to OTel with parent nesting.
    TraceExportFilter — kind allowlist applied to remote export only.
    attach_turn_trace_context — context manager for pydantic-ai runs under a turn root.
    get_trace_event_bridge — module singleton accessor.
    set_trace_event_bridge — register bridge at gateway boot (tests).
Examples:
    >>> from sevn.agent.tracing.trace_event_bridge import get_trace_event_bridge
    >>> get_trace_event_bridge() is None
    True
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from opentelemetry import context, trace
from opentelemetry.trace import NonRecordingSpan, Span, SpanContext, Tracer

from sevn.agent.tracing.otel_sink import _flatten_attrs, _otel_status
from sevn.config.defaults import DEFAULT_TRACE_EXPORT_EXCLUDE_KINDS

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent

_bridge_lock = threading.Lock()
_bridge_instance: TraceEventOtelBridge | None = None


@dataclass(frozen=True)
class TraceExportFilter:
    """Kinds to drop before a ``TraceEvent`` reaches the shared ``TracerProvider``.

    Applies to remote export only — :class:`~sevn.agent.tracing.multi_sink.MultiSink`
    still hands every event to the local sqlite / JSONL sinks, so excluding a kind
    trims egress and vendor span count without losing on-box forensics.
    """

    exclude_kinds: tuple[str, ...] = DEFAULT_TRACE_EXPORT_EXCLUDE_KINDS

    @classmethod
    def from_kinds(cls, kinds: list[str] | None) -> TraceExportFilter:
        """Build a filter from configured kind patterns, falling back to defaults.

        Args:
            kinds (list[str] | None): ``tracing.export.exclude_kinds`` or ``None``.

        Returns:
            TraceExportFilter: Filter with normalized, non-empty patterns.

        Examples:
            >>> TraceExportFilter.from_kinds(None).exclude_kinds
            ('snapshot.checkpoint',)
            >>> TraceExportFilter.from_kinds([]).exclude_kinds
            ()
        """
        if kinds is None:
            return cls()
        cleaned = tuple(k.strip() for k in kinds if isinstance(k, str) and k.strip())
        return cls(exclude_kinds=cleaned)

    def allows(self, kind: str) -> bool:
        """Return whether ``kind`` should be exported to the remote backend.

        A pattern matches the kind exactly, or as a prefix when it ends with ``*``.

        Args:
            kind (str): ``TraceEvent.kind`` under consideration.

        Returns:
            bool: ``True`` when the event should reach the ``TracerProvider``.

        Examples:
            >>> f = TraceExportFilter(exclude_kinds=("snapshot.checkpoint", "debug.*"))
            >>> f.allows("gateway.turn.start")
            True
            >>> f.allows("snapshot.checkpoint")
            False
            >>> f.allows("debug.anything")
            False
        """
        for pattern in self.exclude_kinds:
            if pattern.endswith("*"):
                if kind.startswith(pattern[:-1]):
                    return False
            elif kind == pattern:
                return False
        return True


def get_trace_event_bridge() -> TraceEventOtelBridge | None:
    """Return the gateway ``TraceEventOtelBridge`` when registered.

    Returns:
        TraceEventOtelBridge | None: Active bridge or ``None`` outside gateway boot.

    Examples:
        >>> get_trace_event_bridge() is None
        True
    """
    return _bridge_instance


def set_trace_event_bridge(bridge: TraceEventOtelBridge | None) -> None:
    """Register or clear the module bridge singleton (gateway boot / tests).

    Args:
        bridge (TraceEventOtelBridge | None): Bridge instance or ``None`` to clear.

    Examples:
        >>> set_trace_event_bridge(None) is None
        True
    """
    global _bridge_instance
    with _bridge_lock:
        _bridge_instance = bridge


@contextlib.contextmanager
def attach_turn_trace_context(turn_span_id: str | None) -> Generator[None, None, None]:
    """Attach OTel context for an open turn root span during agent execution.

    Args:
        turn_span_id (str | None): ``gateway.turn.start`` span id when known.

    Yields:
        None: While the turn context is active for pydantic-ai nesting.

    Returns:
        None: Implicit after context exit.

    Examples:
        >>> with attach_turn_trace_context(None):
        ...     pass
    """
    bridge = get_trace_event_bridge()
    if bridge is None or not turn_span_id:
        yield
        return
    with bridge.attach_span_context(turn_span_id):
        yield


class TraceEventOtelBridge:
    """Map ``TraceEvent`` rows to OTel spans on the shared ``TracerProvider``.

    Honors ``parent_span_id`` for native nesting (turn → triage → agent → tool).
    ``gateway.turn.start`` spans stay open until ``gateway.turn.complete`` for the
    same ``turn_id`` so downstream pydantic-ai spans can attach as children.
    """

    def __init__(
        self,
        *,
        tracer: Tracer | None = None,
        export_filter: TraceExportFilter | None = None,
    ) -> None:
        """Bind a tracer from the global ``TracerProvider`` when omitted.

        Args:
            tracer (Tracer | None): Optional explicit tracer (test seam).
            export_filter (TraceExportFilter | None): Kinds to drop before export;
                defaults to :class:`TraceExportFilter` shipped defaults.

        Examples:
            >>> TraceEventOtelBridge() is not None
            True
        """
        self._tracer = tracer or trace.get_tracer("sevn.agent.tracing.trace_event_bridge")
        self._filter = export_filter or TraceExportFilter()
        self._lock = threading.Lock()
        self._open_spans: dict[str, Span] = {}
        self._span_contexts: dict[str, SpanContext] = {}
        self._turn_roots: dict[str, str] = {}

    async def emit(self, event: TraceEvent) -> None:
        """Convert one ``TraceEvent`` to OTel span(s) on the shared provider.

        Args:
            event (TraceEvent): Structured row from gateway emit sites.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TraceEventOtelBridge.emit)
            True
        """
        try:
            self._export_event(event)
        except Exception:
            logger.bind(kind=event.kind, span_id=event.span_id).exception(
                "trace event otel bridge failed",
            )

    async def flush(self) -> None:
        """No buffered state in the bridge.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TraceEventOtelBridge.flush)
            True
        """
        return

    async def close(self) -> None:
        """End any still-open turn spans (best-effort).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TraceEventOtelBridge.close)
            True
        """
        with self._lock:
            for span in list(self._open_spans.values()):
                with contextlib.suppress(Exception):
                    span.end()
            self._open_spans.clear()
            self._span_contexts.clear()
            self._turn_roots.clear()

    @contextlib.contextmanager
    def attach_span_context(self, span_id: str) -> Generator[None, None, None]:
        """Attach OTel context for ``span_id`` when that span is open in the bridge.

        Args:
            span_id (str): sevn ``TraceEvent.span_id`` for an open span.

        Yields:
            None: While the span context is active.

        Returns:
            None: Implicit after context exit.

        Examples:
            >>> bridge = TraceEventOtelBridge()
            >>> with bridge.attach_span_context("missing"):
            ...     pass
        """
        with self._lock:
            span_context = self._span_contexts.get(span_id)
        if span_context is None:
            yield
            return
        parent = trace.set_span_in_context(NonRecordingSpan(span_context))
        token = context.attach(parent)
        try:
            yield
        finally:
            context.detach(token)

    def _export_event(self, event: TraceEvent) -> None:
        """Route one trace row to turn lifecycle or instant-span handlers.

        Args:
            event (TraceEvent): Structured row from gateway emit sites.

        Examples:
            >>> from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent
            >>> bridge = TraceEventOtelBridge()
            >>> bridge._export_event(
            ...     TraceEvent(
            ...         kind="gateway.boot",
            ...         span_id="s",
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
        if event.kind == "gateway.turn.complete":
            self._complete_turn(event)
            return
        if event.kind == "gateway.turn.start":
            # Turn roots are the correlation spine — never filtered, since child
            # spans and ``attach_turn_trace_context`` resolve their parent through
            # the bookkeeping these two branches maintain.
            self._start_turn(event)
            return
        if not self._filter.allows(event.kind):
            return
        self._emit_instant_span(event)

    def _start_turn(self, event: TraceEvent) -> None:
        """Open a turn root span until ``gateway.turn.complete``.

        Args:
            event (TraceEvent): ``gateway.turn.start`` row with stable ``span_id``.

        Examples:
            >>> from sevn.agent.tracing.sink import TraceEvent
            >>> bridge = TraceEventOtelBridge()
            >>> bridge._start_turn(
            ...     TraceEvent(
            ...         kind="gateway.turn.start",
            ...         span_id="root",
            ...         parent_span_id=None,
            ...         session_id="s",
            ...         turn_id="t",
            ...         tier=None,
            ...         ts_start_ns=1,
            ...         ts_end_ns=1,
            ...         status="started",
            ...     ),
            ... ) is None
            True
        """
        span = self._tracer.start_span(
            name=event.kind,
            start_time=event.ts_start_ns,
            attributes=_flatten_attrs(event),
        )
        span.set_status(_otel_status(event.status))
        with self._lock:
            self._open_spans[event.span_id] = span
            ctx = span.get_span_context()
            if ctx.is_valid:
                self._span_contexts[event.span_id] = ctx
                self._turn_roots[event.turn_id] = event.span_id

    def _complete_turn(self, event: TraceEvent) -> None:
        """End the open turn root span for ``event.turn_id``.

        Args:
            event (TraceEvent): ``gateway.turn.complete`` row.

        Examples:
            >>> from sevn.agent.tracing.sink import TraceEvent
            >>> bridge = TraceEventOtelBridge()
            >>> bridge._complete_turn(
            ...     TraceEvent(
            ...         kind="gateway.turn.complete",
            ...         span_id="done",
            ...         parent_span_id=None,
            ...         session_id="s",
            ...         turn_id="missing",
            ...         tier=None,
            ...         ts_start_ns=1,
            ...         ts_end_ns=2,
            ...         status="ok",
            ...     ),
            ... ) is None
            True
        """
        with self._lock:
            root_id = self._turn_roots.pop(event.turn_id, None)
            span = self._open_spans.pop(root_id, None) if root_id else None
            if root_id:
                self._span_contexts.pop(root_id, None)
        if span is None:
            self._emit_instant_span(event)
            return
        end_ns = event.ts_end_ns if event.ts_end_ns is not None else event.ts_start_ns
        span.set_status(_otel_status(event.status))
        for key, value in _flatten_attrs(event).items():
            span.set_attribute(key, value)
        span.end(end_time=end_ns)

    def _emit_instant_span(self, event: TraceEvent) -> None:
        """Create and end one point-in-time span under the resolved parent context.

        Args:
            event (TraceEvent): Non-turn lifecycle row.

        Examples:
            >>> from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent
            >>> bridge = TraceEventOtelBridge()
            >>> bridge._emit_instant_span(
            ...     TraceEvent(
            ...         kind="triage.start",
            ...         span_id="c",
            ...         parent_span_id=None,
            ...         session_id="s",
            ...         turn_id=SYSTEM_TURN_ID,
            ...         tier=None,
            ...         ts_start_ns=1,
            ...         ts_end_ns=2,
            ...         status="started",
            ...     ),
            ... ) is None
            True
        """
        parent_ctx = self._parent_context(event.parent_span_id)
        token = context.attach(parent_ctx)
        try:
            end_ns = event.ts_end_ns if event.ts_end_ns is not None else event.ts_start_ns
            span = self._tracer.start_span(
                name=event.kind,
                start_time=event.ts_start_ns,
                attributes=_flatten_attrs(event),
            )
            span.set_status(_otel_status(event.status))
            span.end(end_time=end_ns)
        finally:
            context.detach(token)

    def _parent_context(self, parent_span_id: str | None) -> context.Context:
        """Resolve OTel parent context from an open sevn ``parent_span_id``.

        Args:
            parent_span_id (str | None): Parent sevn span id when known.

        Returns:
            context.Context: OTel context carrying the parent span, if open.

        Examples:
            >>> bridge = TraceEventOtelBridge()
            >>> bridge._parent_context(None) is not None
            True
        """
        if not parent_span_id:
            return context.get_current()
        with self._lock:
            span_context = self._span_contexts.get(parent_span_id)
        if span_context is None or not span_context.is_valid:
            return context.get_current()
        return trace.set_span_in_context(NonRecordingSpan(span_context))


__all__ = [
    "TraceEventOtelBridge",
    "TraceExportFilter",
    "attach_turn_trace_context",
    "get_trace_event_bridge",
    "set_trace_event_bridge",
]
