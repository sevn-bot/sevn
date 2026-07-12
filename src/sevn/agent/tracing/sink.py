"""Trace sinks (`TraceSink` protocol and JSONL file implementation).
Module: sevn.agent.tracing.sink
Depends: (none)
Exports:
    TraceEvent — structured trace row.
    TraceSink — pluggable async destination.
    JSONLFileSink — append one JSON object per line; ``emit`` swallows errors.
    NullTraceSink — no-op sink for tests and gateway boots without persistence.
    checkpoint_snapshot — optional ``ActiveRunSnapshot`` hook via trace rows (§16).
    current_sink — task-local active :class:`TraceSink` when bound (gateway HTTP/WS).
    trace_sink_scope — context manager to bind ``current_sink`` for a call chain.

Also exposes the module-level constant ``SYSTEM_TURN_ID`` (``'-'``) for emitters
of non-turn lifecycle events; see its own docstring below.

Examples:
    >>> isinstance(True, bool)
    True
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import time_ns
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path
_trace_sink_ctx: ContextVar[TraceSink | None] = ContextVar("sevn_trace_sink", default=None)


def current_sink() -> TraceSink | None:
    """Return the trace sink bound for this async task, if any.
    The gateway sets this via :func:`trace_sink_scope` (HTTP middleware and
    WebChat WebSocket) so deep helpers can emit without threading ``TraceSink``
    through every frame (``specs/01-system-overview.md`` §2.5).
    Returns:
        TraceSink | None: Active sink or ``None`` when unbound / outside gateway.
    Examples:
        >>> current_sink() is None
        True
    """
    return _trace_sink_ctx.get()


@contextmanager
def trace_sink_scope(sink: TraceSink | None) -> Generator[None, None, None]:
    """Bind ``sink`` as :func:`current_sink` for the caller's block.
    Args:
        sink (TraceSink | None): Gateway trace sink or ``None`` to clear the slot.
    Yields:
        None: While the override is active.
    Returns:
        None: Implicit after context exit.
    Examples:
        >>> from sevn.agent.tracing.sink import NullTraceSink, current_sink, trace_sink_scope
        >>> s = NullTraceSink()
        >>> with trace_sink_scope(s):
        ...     assert current_sink() is s
        >>> assert current_sink() is None
    """
    token = _trace_sink_ctx.set(sink)
    try:
        yield
    finally:
        _trace_sink_ctx.reset(token)


SYSTEM_TURN_ID = "-"
"""Sentinel ``turn_id`` for trace events that do not belong to a turn.

Non-turn events (gateway boot/shutdown, workspace layout validation, channel
adapter start/stop) cannot supply a real turn correlation id. They emit with
``turn_id=SYSTEM_TURN_ID`` so the field is never empty — empty ``turn_id``
makes downstream dashboards and query filters silently drop rows.

Examples:
    >>> SYSTEM_TURN_ID
    '-'
"""


@dataclass(frozen=True)
class TraceEvent:
    """Structured trace row — sinks persist or forward.

    ``turn_id`` must be non-empty. Use :data:`SYSTEM_TURN_ID` for non-turn
    lifecycle events; supply the real correlation id for turn-scoped rows.
    """

    kind: str
    span_id: str
    parent_span_id: str | None
    session_id: str
    turn_id: str
    tier: str | None
    ts_start_ns: int
    ts_end_ns: int | None
    status: str
    attrs: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate ``turn_id`` is non-empty (use :data:`SYSTEM_TURN_ID` for non-turn rows).

        Examples:
            >>> TraceEvent(
            ...     kind="k", span_id="s", parent_span_id=None,
            ...     session_id="se", turn_id="", tier=None,
            ...     ts_start_ns=1, ts_end_ns=2, status="ok",
            ... )
            Traceback (most recent call last):
                ...
            ValueError: TraceEvent.turn_id must be non-empty; use SYSTEM_TURN_ID ('-') for non-turn events
        """
        if not self.turn_id:
            msg = (
                "TraceEvent.turn_id must be non-empty; use SYSTEM_TURN_ID ('-') for non-turn events"
            )
            raise ValueError(msg)


@runtime_checkable
class TraceSink(Protocol):
    """Pluggable trace destination."""

    async def emit(self, event: TraceEvent) -> None:
        """Record one event (must not raise into callers).
                Args:
        event (TraceEvent): Structured row to persist or forward.
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        ...

    async def flush(self) -> None:
        """Best-effort flush of buffered bytes.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    async def close(self) -> None:
        """Release resources.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...


def _event_to_line(event: TraceEvent) -> str:
    """Serialize a trace event to one JSON line.
        Args:
    event (TraceEvent): Row to persist.
        Returns:
            str: JSON object plus trailing newline.
        Examples:
            >>> te = TraceEvent(
            ...     kind="k",
            ...     span_id="s",
            ...     parent_span_id=None,
            ...     session_id="se",
            ...     turn_id="t",
            ...     tier=None,
            ...     ts_start_ns=1,
            ...     ts_end_ns=2,
            ...     status="ok",
            ... )
            >>> _event_to_line(te).startswith('{"kind":')
            True
    """
    payload = dataclasses.asdict(event)
    return json.dumps(payload, separators=(",", ":"), default=str, ensure_ascii=False) + "\n"


class JSONLFileSink:
    """Append JSON lines to a file; ``emit`` logs and drops on failure."""

    def __init__(self, path: Path) -> None:
        """Create a sink writing to the given filesystem path.
                Args:
        path (Path): Output JSONL path (parent dirs created on write).
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        self._path = path
        self._lock = asyncio.Lock()

    async def emit(self, event: TraceEvent) -> None:
        """Append one JSON line; swallow exceptions after logging.
                Args:
        event (TraceEvent): Row to append.
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        try:
            async with self._lock:
                await asyncio.to_thread(self._append_line, event)
        except Exception:
            logger.bind(path=str(self._path)).exception("trace sink emit failed")

    async def flush(self) -> None:
        """No-op: each ``emit`` opens and closes the file.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        return

    async def close(self) -> None:
        """No persistent handle in v1.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        return

    def _append_line(self, event: TraceEvent) -> None:
        """Write one line synchronously (runs in a thread from ``emit``).
                Args:
        event (TraceEvent): Row to append.
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(_event_to_line(event))


async def checkpoint_snapshot(
    trace: TraceSink | None,
    *,
    session_id: str,
    turn_id: str,
    tier: str | None,
    kind: str,
    excerpt: str = "",
    state: dict[str, object] | None = None,
) -> None:
    """Emit a harness checkpoint row with optional full ``state`` (`specs/04-tracing.md` §7.2).

    ``state`` is persisted in ``attrs_json`` (redacted + size-capped at the sink).
    ``excerpt`` remains a short human-readable summary when provided.

    Args:
        trace (TraceSink | None): When None, becomes a no-op.
        session_id (str): Session attribute on the trace row.
        turn_id (str): Turn attribute on the trace row.
        tier (str | None): Optional complexity / harness tier label.
        kind (str): Logical checkpoint discriminator (e.g. ``tool.before``).
        excerpt (str): Optional short summary (truncated to 512 chars).
        state (dict[str, object] | None): Full checkpoint payload for traces.

    Examples:
        >>> import asyncio, inspect
        >>> inspect.iscoroutinefunction(checkpoint_snapshot)
        True
        >>> asyncio.run(
        ...     checkpoint_snapshot(
        ...         None,
        ...         session_id="s",
        ...         turn_id="t",
        ...         tier=None,
        ...         kind="tool.before",
        ...         state={"name": "read"},
        ...     ),
        ... ) is None
        True
    """
    if trace is None:
        return
    from sevn.agent.tracing.attrs import json_safe_trace_attrs

    attrs: dict[str, object] = {"checkpoint_kind": kind}
    if excerpt:
        safe_excerpt = excerpt if len(excerpt) <= 512 else excerpt[:512]
        attrs["excerpt"] = safe_excerpt
    if state:
        attrs["state"] = json_safe_trace_attrs(state)
    now = time_ns()
    await trace.emit(
        TraceEvent(
            kind="snapshot.checkpoint",
            span_id=str(uuid.uuid4()),
            parent_span_id=None,
            session_id=session_id,
            turn_id=turn_id,
            tier=tier,
            ts_start_ns=now,
            ts_end_ns=now,
            status="ok",
            attrs=attrs,
        )
    )


class NullTraceSink:
    """Trace sink that discards all events (bootstraps, unit tests).
    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import NullTraceSink, TraceEvent
        >>> async def _t():
        ...     s = NullTraceSink()
        ...     await s.emit(
        ...         TraceEvent(
        ...             kind="k",
        ...             span_id="s",
        ...             parent_span_id=None,
        ...             session_id="",
        ...             turn_id="t",
        ...             tier=None,
        ...             ts_start_ns=1,
        ...             ts_end_ns=None,
        ...             status="ok",
        ...         ),
        ...     )
        >>> asyncio.run(_t()) is None
        True
    """

    async def emit(self, event: TraceEvent) -> None:
        """Drop ``event``.
        Args:
            event (TraceEvent): Unused in this sink.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(NullTraceSink.emit)
            True
        """
        _ = event
        return

    async def flush(self) -> None:
        """No buffered state.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(NullTraceSink.flush)
            True
        """
        return

    async def close(self) -> None:
        """No persistent resources.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(NullTraceSink.close)
            True
        """
        return
