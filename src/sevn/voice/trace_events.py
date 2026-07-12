"""Trace helpers for voice spans (`specs/20-voice.md` §7).

Module: sevn.voice.trace_events
Depends: sevn.agent.tracing.sink

Exports:
    emit_voice_event — fire-and-forget TraceSink row for ``voice.*`` kinds.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink


async def emit_voice_event(
    trace: TraceSink | None,
    *,
    kind: str,
    session_id: str,
    turn_id: str,
    status: str,
    attrs: dict[str, object] | None = None,
) -> None:
    """Emit a single-point trace row when ``trace`` is wired.

    Args:
        trace (TraceSink | None): Destination sink or ``None`` in tests.
        kind (str): Event name such as ``voice.stt.start``.
        session_id (str): Gateway session id (may be empty pre-session).
        turn_id (str): Correlation / turn id.
        status (str): Short status label (``ok``, ``failed``, ...).
        attrs (dict[str, object] | None): Optional structured attributes.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> asyncio.run(emit_voice_event(
        ...     NullTraceSink(), kind="voice.stt.start", session_id="s",
        ...     turn_id="t", status="started"))
    """

    if trace is None:
        return
    from sevn.agent.tracing.sink import TraceEvent

    now = time.time_ns()
    event = TraceEvent(
        kind=kind,
        span_id=uuid.uuid4().hex,
        parent_span_id=None,
        session_id=session_id,
        turn_id=turn_id,
        tier=None,
        ts_start_ns=now,
        ts_end_ns=now,
        status=status,
        attrs=dict(attrs or {}),
    )
    await trace.emit(event)
