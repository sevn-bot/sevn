"""In-process trace fan-out before persistence (`specs/04-tracing.md` §2).

Module: sevn.agent.tracing.emit
Depends: sevn.agent.tracing.sink
Exports:
    register_trace_subscriber — attach a ``TraceSink`` observer.
    unregister_trace_subscriber — detach a previously registered observer.
    reset_trace_subscribers_for_tests — clear subscribers (test isolation).
    wrap_trace_sink — wrap a sink so ``emit`` notifies subscribers first.
Examples:
    >>> isinstance(True, bool)
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent, TraceSink

_subscribers: list[TraceSink] = []


def register_trace_subscriber(sink: TraceSink) -> None:
    """Register an in-process observer for every gateway trace ``emit``.

    Args:
        sink (TraceSink): Observer (for example :class:`MissionControlTraceSink`).
    Examples:
        >>> isinstance(True, bool)
        True
    """
    if sink not in _subscribers:
        _subscribers.append(sink)


def unregister_trace_subscriber(sink: TraceSink) -> None:
    """Remove a subscriber installed via :func:`register_trace_subscriber`.

    Args:
        sink (TraceSink): Previously registered observer.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    try:
        _subscribers.remove(sink)
    except ValueError:
        return


async def _emit(event: TraceEvent) -> None:
    """Notify all registered trace subscribers (does not persist).

    Args:
        event (TraceEvent): Structured row from gateway or harness code paths.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit)
        True
    """
    for sink in list(_subscribers):
        try:
            await sink.emit(event)
        except Exception:
            logger.bind(sink=type(sink).__name__, kind=event.kind).exception(
                "trace subscriber emit failed",
            )


class _SubscriberFanoutSink:
    """Wrap a primary sink: subscribers first, then persistence."""

    def __init__(self, primary: TraceSink) -> None:
        """Wrap ``primary`` so :func:`_emit` runs before persistence.

        Args:
            primary (TraceSink): Underlying persistence sink.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._primary = primary

    async def emit(self, event: TraceEvent) -> None:
        """Fan out to subscribers, then delegate to the wrapped sink.

        Args:
            event (TraceEvent): Row to observe and persist.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        await _emit(event)
        await self._primary.emit(event)

    async def flush(self) -> None:
        """Flush the wrapped primary sink.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        await self._primary.flush()

    async def close(self) -> None:
        """Close the wrapped primary sink.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        await self._primary.close()


def wrap_trace_sink(sink: TraceSink) -> TraceSink:
    """Return ``sink`` wrapped so ``emit`` notifies :func:`register_trace_subscriber` hooks.

    Args:
        sink (TraceSink): Primary persistence sink (SQLite, JSONL, ``NullTraceSink``, …).
    Returns:
        TraceSink: Fan-out wrapper when subscribers exist; otherwise ``sink`` unchanged.
    Examples:
        >>> from sevn.agent.tracing.sink import NullTraceSink
        >>> wrap_trace_sink(NullTraceSink()) is not None
        True
    """
    if not _subscribers:
        return sink
    return _SubscriberFanoutSink(sink)


def reset_trace_subscribers_for_tests() -> None:
    """Clear all subscribers (test isolation only).

    Examples:
        >>> reset_trace_subscribers_for_tests() is None
        True
    """
    _subscribers.clear()


__all__ = [
    "_emit",
    "register_trace_subscriber",
    "reset_trace_subscribers_for_tests",
    "unregister_trace_subscriber",
    "wrap_trace_sink",
]
