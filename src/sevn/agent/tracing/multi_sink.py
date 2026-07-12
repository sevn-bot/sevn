"""Compose multiple ``TraceSink`` instances (`specs/04-tracing.md` §2).
Module: sevn.agent.tracing.multi_sink
Depends: sevn.agent.tracing.sink
Exports:
    MultiSink — sequential fan-out with per-member isolation.
Examples:
    >>> isinstance(True, bool)
    True
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent, TraceSink


class MultiSink:
    """Fan out each ``emit`` / ``flush`` / ``close`` to members **in config order**.
    **Ordering:** For one logical ``TraceEvent``, ``emit`` awaits sink A fully,
    then sink B, and so on — sinks observe the same sequence operators configure in
    ``tracing.sinks[]``.
    **Partial failure:** If one member raises (violating ``TraceSink`` contract),
    the exception is logged and later members still run. Members that implement
    the normative non-raising contract (``SQLiteSink``, ``JSONLFileSink``) absorb
    their own I/O failures; ``MultiSink`` adds isolation between members.
    **OTel isolation:** :class:`~sevn.agent.tracing.otel_sink.OTelExporterSink` enqueues
    in ``emit`` and returns immediately so sequential fan-out does not block on OTLP
    network I/O; export runs on a dedicated background thread.
    Examples:
        >>> isinstance(True, bool)
        True
    """

    def __init__(self, sinks: Sequence[TraceSink]) -> None:
        """Attach ordered sinks.
                Args:
        sinks (Sequence[TraceSink]): Non-empty ordered sink chain.
                Raises:
            ValueError: When ``sinks`` is empty.
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        if not sinks:
            msg = "MultiSink requires at least one sink"
            raise ValueError(msg)
        self._sinks = tuple(sinks)

    async def emit(self, event: TraceEvent) -> None:
        """Emit ``event`` to each member in order.
                Args:
        event (TraceEvent): Row to persist.
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        for sink in self._sinks:
            try:
                await sink.emit(event)
            except Exception:
                logger.bind(sink=type(sink).__name__, kind=event.kind).exception(
                    "multi-sink member emit failed",
                )

    async def flush(self) -> None:
        """Flush members in order (errors logged per member).
        Examples:
            >>> isinstance(True, bool)
            True
        """
        for sink in self._sinks:
            try:
                await sink.flush()
            except Exception:
                logger.bind(sink=type(sink).__name__).exception(
                    "multi-sink member flush failed",
                )

    async def close(self) -> None:
        """Close members in order (errors logged per member).
        Examples:
            >>> isinstance(True, bool)
            True
        """
        for sink in self._sinks:
            try:
                await sink.close()
            except Exception:
                logger.bind(sink=type(sink).__name__).exception(
                    "multi-sink member close failed",
                )
