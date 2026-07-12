"""Trace helpers for self-improve job spans (`specs/33-self-improvement.md` §7).

Module: sevn.self_improve.trace_events
Depends: sevn.agent.tracing.sink

Exports:
    emit_self_improve_trace — fire-and-forget TraceSink row for ``self_improve.*`` kinds.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink


async def emit_self_improve_trace(
    trace: TraceSink | None,
    *,
    job_id: str,
    kind: str,
    status: str = "ok",
    attrs: dict[str, object] | None = None,
) -> None:
    """Emit one self-improve lifecycle span when ``trace`` is wired.

    Args:
        trace (TraceSink | None): Destination sink or ``None`` in tests.
        job_id (str): Improve job identifier stored on span attrs.
        kind (str): Stable event name such as ``self_improve.job_start``.
        status (str): Short status label (``ok``, ``failed``, ``blocked``, ...).
        attrs (dict[str, object] | None): Optional structured attributes per spec §7.

    Returns:
        None: Always; no-op when ``trace`` is ``None``.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> asyncio.run(
        ...     emit_self_improve_trace(
        ...         NullTraceSink(),
        ...         job_id="job-1",
        ...         kind="self_improve.job_start",
        ...     ),
        ... ) is None
        True
    """
    if trace is None:
        return
    from sevn.agent.tracing.sink import TraceEvent

    merged: dict[str, object] = {"job_id": job_id}
    if attrs:
        merged.update(attrs)
    now = time.time_ns()
    event = TraceEvent(
        kind=kind,
        span_id=uuid.uuid4().hex,
        parent_span_id=None,
        session_id="",
        turn_id=job_id,
        tier=None,
        ts_start_ns=now,
        ts_end_ns=now,
        status=status,
        attrs=merged,
    )
    await trace.emit(event)
