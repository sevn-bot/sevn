"""Daily UTC JSONL trace sink under ``layout.traces_dir`` (`specs/04-tracing.md` §2).
Module: sevn.agent.tracing.rotating_jsonl_sink
Depends: asyncio, datetime, pathlib, sevn.agent.tracing.sink
Exports:
    RotatingJSONLFileSink — append to ``traces_dir / "{UTC-date}.jsonl"``.
Examples:
    >>> isinstance(True, bool)
    True
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sevn.agent.tracing.sink import JSONLFileSink, TraceEvent


def _utc_date_str() -> str:
    """Return today's UTC date as ``YYYY-MM-DD``.

    Returns:
        str: UTC calendar date for daily JSONL rotation.
    Examples:
        >>> len(_utc_date_str()) == 10
        True
        >>> _utc_date_str().count("-") == 2
        True
    """
    return datetime.now(UTC).strftime("%Y-%m-%d")


class RotatingJSONLFileSink:
    """Append JSON lines to one file per UTC day under ``traces_dir``."""

    def __init__(self, traces_dir: Path) -> None:
        """Create a sink that rotates by UTC calendar date.

        Args:
            traces_dir (Path): Directory for ``YYYY-MM-DD.jsonl`` files.
        Examples:
            >>> from pathlib import Path
            >>> RotatingJSONLFileSink(Path("/tmp/traces"))._traces_dir == Path("/tmp/traces")
            True
        """
        self._traces_dir = traces_dir
        self._lock = asyncio.Lock()
        self._active_date: str | None = None
        self._delegate: JSONLFileSink | None = None

    def _path_for_date(self, date_str: str) -> Path:
        """Resolve the JSONL path for one UTC date string.

        Args:
            date_str (str): ``YYYY-MM-DD`` label.
        Returns:
            Path: ``traces_dir / "{date_str}.jsonl"``.
        Examples:
            >>> from pathlib import Path
            >>> sink = RotatingJSONLFileSink(Path("/w/.sevn/traces"))
            >>> sink._path_for_date("2026-05-22") == Path("/w/.sevn/traces/2026-05-22.jsonl")
            True
        """
        return self._traces_dir / f"{date_str}.jsonl"

    def _delegate_for_date(self, date_str: str) -> JSONLFileSink:
        """Return (and cache) the delegate sink for ``date_str``.

        Args:
            date_str (str): UTC date label.
        Returns:
            JSONLFileSink: File sink for that day's path.
        Examples:
            >>> from pathlib import Path
            >>> sink = RotatingJSONLFileSink(Path("/tmp/t"))
            >>> d1 = sink._delegate_for_date("2026-01-01")
            >>> d2 = sink._delegate_for_date("2026-01-01")
            >>> d1 is d2
            True
        """
        if self._active_date == date_str and self._delegate is not None:
            return self._delegate
        self._active_date = date_str
        self._delegate = JSONLFileSink(self._path_for_date(date_str))
        return self._delegate

    async def emit(self, event: TraceEvent) -> None:
        """Append one JSON line to the current UTC day's file.

        Args:
            event (TraceEvent): Row to append.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(RotatingJSONLFileSink.emit)
            True
        """
        date_str = _utc_date_str()
        async with self._lock:
            delegate = self._delegate_for_date(date_str)
        await delegate.emit(event)

    async def flush(self) -> None:
        """Flush the active daily delegate when present.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(RotatingJSONLFileSink.flush)
            True
        """
        if self._delegate is not None:
            await self._delegate.flush()

    async def close(self) -> None:
        """Release the active daily delegate when present.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(RotatingJSONLFileSink.close)
            True
        """
        if self._delegate is not None:
            await self._delegate.close()
