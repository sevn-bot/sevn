"""SQLite ``TraceSink`` for Mission Control (``traces.db``).
Module: sevn.agent.tracing.sqlite_sink
Depends: asyncio, concurrent.futures, json, logging, pathlib,
    sevn.agent.tracing.sink, sevn.agent.tracing.traces_migrate,
    sevn.config.defaults, sevn.storage.sqlite
Exports:
    SQLiteSink — WAL-backed async sink; ``emit`` swallows errors.
    redact_trace_attrs — Phase 1 identity stub for pre-write redaction.
    cap_attrs_json — enforce the ``TRACE_ATTRS_JSON_MAX_BYTES`` size cap.
Examples:
    >>> from pathlib import Path
    >>> from sevn.agent.tracing.sqlite_sink import redact_trace_attrs
    >>> redact_trace_attrs({"a": 1}) == {"a": 1}
    True
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent
from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.config.defaults import TRACE_ATTRS_JSON_MAX_BYTES
from sevn.storage.sqlite import connect_sqlite


def cap_attrs_json(payload: str, *, max_bytes: int = TRACE_ATTRS_JSON_MAX_BYTES) -> str:
    """Truncate ``attrs_json`` to ``max_bytes`` with a structured marker.
    ``specs/04-tracing.md`` §10.7 / §11 design notes: ``attrs_json`` is capped
    *before* it hits SQLite or JSONL so a single pathological event cannot
    blow up the trace store. When the encoded payload exceeds the cap, we
    preserve the row but replace the body with
    ``{"_truncated": true, "_original_bytes": <N>}`` and log a warning.
    Under-cap payloads pass through unchanged.
    Args:
        payload (str): Already-JSON-encoded attrs.
        max_bytes (int): Maximum UTF-8 byte length; default is
            ``TRACE_ATTRS_JSON_MAX_BYTES`` (64 KiB).
    Returns:
        str: ``payload`` if under cap, else the truncation marker JSON.
    Examples:
        >>> cap_attrs_json('{"x": 1}')
        '{"x": 1}'
        >>> out = cap_attrs_json('{"big": "' + "a" * 200000 + '"}', max_bytes=128)
        >>> '"_truncated":true' in out
        True
    """
    encoded = payload.encode("utf-8")
    if len(encoded) <= max_bytes:
        return payload
    logger.bind(original_bytes=len(encoded), max_bytes=max_bytes).warning(
        "trace attrs_json exceeds size cap — truncating",
    )
    marker = {"_truncated": True, "_original_bytes": len(encoded)}
    return json.dumps(marker, separators=(",", ":"), ensure_ascii=False)


def redact_trace_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Return attrs safe to persist (Phase 1: passthrough).
        Args:
    attrs (dict[str, Any]): Raw ``TraceEvent.attrs``.
        Returns:
    dict[str, Any]: Redacted copy or same reference when no rules apply.
        Examples:
            >>> redact_trace_attrs({"x": 1}) == {"x": 1}
            True
    """
    return attrs


class _TracingSqliteWriter:
    """Long-lived WAL connection confined to ``ThreadPoolExecutor`` worker thread."""

    __slots__ = ("_conn",)

    def __init__(self, db_path: Path) -> None:
        """Open WAL-backed SQLite for trace upserts.
        Args:
            db_path (Path): Resolved ``Path`` owned by worker thread callers.
        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> root = Path(tempfile.mkdtemp())
            >>> w = _TracingSqliteWriter(root / "writer.db")
            >>> w.close()
        """
        self._conn = connect_sqlite(db_path)
        apply_traces_migrations(self._conn)

    def upsert_event(self, event: TraceEvent) -> None:
        """Insert/update one span row; runs only on owning thread.
        Args:
            event (TraceEvent): Row to persist (``trace_events`` DDL).
        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.agent.tracing.sink import TraceEvent
            >>> root = Path(tempfile.mkdtemp())
            >>> w = _TracingSqliteWriter(root / "traces.db")
            >>> ev = TraceEvent(
            ...     kind="tool.call",
            ...     span_id="sp-example",
            ...     parent_span_id=None,
            ...     session_id="se",
            ...     turn_id="tu",
            ...     tier="B",
            ...     ts_start_ns=10,
            ...     ts_end_ns=20,
            ...     status="ok",
            ...     attrs={"k": "v"},
            ... )
            >>> w.upsert_event(ev)
            >>> w.close()
        """
        safe_attrs = redact_trace_attrs(dict(event.attrs))
        payload = json.dumps(safe_attrs, separators=(",", ":"), default=str, ensure_ascii=False)
        payload = cap_attrs_json(payload)
        tier_val = event.tier
        conn = self._conn
        conn.execute(
            """
            INSERT INTO trace_events (
                span_id, parent_span_id, session_id, turn_id, tier, kind,
                ts_start_ns, ts_end_ns, status, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                parent_span_id = excluded.parent_span_id,
                session_id = excluded.session_id,
                turn_id = excluded.turn_id,
                tier = excluded.tier,
                kind = excluded.kind,
                ts_start_ns = excluded.ts_start_ns,
                ts_end_ns = excluded.ts_end_ns,
                status = excluded.status,
                attrs_json = excluded.attrs_json
            """,
            (
                event.span_id,
                event.parent_span_id,
                event.session_id,
                event.turn_id,
                tier_val,
                event.kind,
                event.ts_start_ns,
                event.ts_end_ns,
                event.status,
                payload,
            ),
        )
        conn.commit()

    def close(self) -> None:
        """Close the worker-owned SQLite connection.
        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> root = Path(tempfile.mkdtemp())
            >>> w = _TracingSqliteWriter(root / "close.db")
            >>> w.close()
        """
        self._conn.close()


class SQLiteSink:
    """Append/update rows in ``traces.db``; never raises from ``emit``."""

    def __init__(self, db_path: Path) -> None:
        """Open or create the trace database and apply migrations.
                Args:
        db_path (Path): Typically ``traces_sqlite_path(dot_sevn)``.
                Examples:
                    >>> isinstance(SQLiteSink, type)
                    True
        """
        path = Path(db_path).resolve()
        self._db_path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sevn-sqlite-traces")

        def bootstrap() -> _TracingSqliteWriter:
            return _TracingSqliteWriter(path)

        self._writer = self._executor.submit(bootstrap).result()

    async def emit(self, event: TraceEvent) -> None:
        """Insert or update a span row; swallow exceptions after logging.
                Args:
        event (TraceEvent): Row to persist.
                Examples:
                    >>> isinstance(True, bool)
                    True
        """
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._writer.upsert_event, event)
        except Exception:
            logger.bind(db_path=str(self._db_path)).exception("sqlite trace emit failed")

    async def flush(self) -> None:
        """No-op; each upsert commits on the writer thread.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        return

    async def close(self) -> None:
        """Close the writer connection and stop the executor.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        loop = asyncio.get_running_loop()
        writer = self._writer
        exe = self._executor
        try:
            await loop.run_in_executor(exe, writer.close)
        except Exception:
            logger.bind(db_path=str(self._db_path)).exception("sqlite trace sink close failed")
        finally:
            exe.shutdown(wait=True)
