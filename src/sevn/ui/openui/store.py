"""In-memory OpenUI token store + SQLite persistence hooks (`specs/29-openui.md` §3.2).

Module: sevn.ui.openui.store
Depends: sqlite3, threading, time

Exports:
    OpenUIRecord — one stored render payload.
    OpenUIStore — memory map + flush / reload / reaper.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3


@dataclass
class OpenUIRecord:
    """Authoritative server-side state for one OpenUI emission."""

    record_id: str
    workspace_id: str
    session_id: str
    message_id: str
    channel: str
    sanitised_html: str
    expires_at_ns: int
    submit_consumed: bool = False
    fallback_text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class OpenUIStore:
    """Memory-primary store with optional SQLite durability (`specs/29-openui.md` §3.2)."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        """Create an empty store.

        Args:
            conn (sqlite3.Connection | None): Optional ``sevn.db`` connection for flush/reload.

        Examples:
            >>> import sqlite3
            >>> s = OpenUIStore(sqlite3.connect(":memory:"))
            >>> isinstance(s, OpenUIStore)
            True
        """

        self._conn = conn
        self._lock = threading.Lock()
        self._by_id: dict[str, OpenUIRecord] = {}

    def put(self, rec: OpenUIRecord) -> None:
        """Insert or replace a record in memory.

        Args:
            rec (OpenUIRecord): Row keyed by ``record_id``.

        Examples:
            >>> import sqlite3
            >>> import time
            >>> s = OpenUIStore(sqlite3.connect(":memory:"))
            >>> exp = time.time_ns() + 10**18
            >>> r = OpenUIRecord(
            ...     record_id="r1",
            ...     workspace_id="w",
            ...     session_id="s",
            ...     message_id="m",
            ...     channel="webchat",
            ...     sanitised_html="<p>x</p>",
            ...     expires_at_ns=exp,
            ... )
            >>> s.put(r)
            >>> s.get("r1") is not None
            True
        """

        with self._lock:
            self._by_id[rec.record_id] = rec

    def get(self, record_id: str) -> OpenUIRecord | None:
        """Return a live record or ``None`` when missing / expired.

        Args:
            record_id (str): Primary key minted by the bridge.

        Returns:
            OpenUIRecord | None: Active row or ``None`` when absent or past ``expires_at_ns``.

        Examples:
            >>> import sqlite3
            >>> s = OpenUIStore(sqlite3.connect(":memory:"))
            >>> s.get("missing") is None
            True
        """

        now = time.time_ns()
        with self._lock:
            rec = self._by_id.get(record_id)
            if rec is None:
                return None
            if now > rec.expires_at_ns:
                return None
            return rec

    def mark_submit_consumed(self, record_id: str) -> bool:
        """Mark submit consumed; return ``True`` when this call flipped the bit.

        Args:
            record_id (str): Row id for the active OpenUI emission.

        Returns:
            bool: ``True`` when this invocation transitioned from unconsumed → consumed.

        Examples:
            >>> import sqlite3
            >>> import time
            >>> s = OpenUIStore(sqlite3.connect(":memory:"))
            >>> exp = time.time_ns() + 10**18
            >>> r = OpenUIRecord(
            ...     record_id="r2",
            ...     workspace_id="w",
            ...     session_id="s",
            ...     message_id="m",
            ...     channel="webchat",
            ...     sanitised_html="",
            ...     expires_at_ns=exp,
            ... )
            >>> s.put(r)
            >>> s.mark_submit_consumed("r2")
            True
            >>> s.mark_submit_consumed("r2")
            False
        """

        with self._lock:
            rec = self._by_id.get(record_id)
            if rec is None:
                return False
            if rec.submit_consumed:
                return False
            rec.submit_consumed = True
            return True

    def reap_expired_memory(self) -> int:
        """Drop expired rows from memory; return deleted count.

        Returns:
            int: Number of rows removed from the in-memory map.

        Examples:
            >>> import sqlite3
            >>> s = OpenUIStore(sqlite3.connect(":memory:"))
            >>> s.reap_expired_memory()
            0
        """

        now = time.time_ns()
        with self._lock:
            dead = [rid for rid, r in self._by_id.items() if now > r.expires_at_ns]
            for rid in dead:
                del self._by_id[rid]
            return len(dead)

    def reap_expired_sqlite(self) -> int:
        """Delete expired rows from ``openui_tokens``; return deleted count.

        Returns:
            int: Rows deleted from SQLite (``0`` when no DB bound).

        Examples:
            >>> import sqlite3
            >>> OpenUIStore(None).reap_expired_sqlite()
            0
        """

        if self._conn is None:
            return 0
        now_ns = time.time_ns()
        conn = self._conn

        def _run() -> int:
            cur = conn.execute(
                "DELETE FROM openui_tokens WHERE expires_at_ns < ?",
                (now_ns,),
            )
            conn.commit()
            return int(cur.rowcount or 0)

        with self._lock:
            return int(_run())

    def load_from_sqlite(self) -> int:
        """Load non-expired rows into memory on boot; return rows loaded.

        Returns:
            int: Rows hydrated into memory (``0`` when no DB bound).

        Examples:
            >>> import sqlite3
            >>> OpenUIStore(None).load_from_sqlite()
            0
        """

        if self._conn is None:
            return 0
        now_ns = time.time_ns()
        conn = self._conn

        def _run() -> list[tuple[Any, ...]]:
            cur = conn.execute(
                """
                SELECT record_id, workspace_id, session_id, message_id, channel,
                       sanitised_html, expires_at_ns, submit_consumed, fallback_text, extra_json
                FROM openui_tokens
                WHERE expires_at_ns >= ?
                """,
                (now_ns,),
            )
            return list(cur.fetchall())

        with self._lock:
            rows = _run()
            for row in rows:
                (
                    record_id,
                    workspace_id,
                    session_id,
                    message_id,
                    channel,
                    sanitised_html,
                    expires_at_ns,
                    submit_consumed,
                    fallback_text,
                    raw_ex,
                ) = row
                extra: dict[str, Any] = {}
                if isinstance(raw_ex, str) and raw_ex.strip():
                    try:
                        parsed = json.loads(raw_ex)
                        if isinstance(parsed, dict):
                            extra = {str(k): v for k, v in parsed.items()}
                    except json.JSONDecodeError:
                        extra = {}
                rec = OpenUIRecord(
                    record_id=str(record_id),
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    message_id=str(message_id),
                    channel=str(channel or "webchat"),
                    sanitised_html=str(sanitised_html),
                    expires_at_ns=int(expires_at_ns),
                    submit_consumed=bool(int(submit_consumed or 0)),
                    fallback_text=str(fallback_text or ""),
                    extra=extra,
                )
                self._by_id[rec.record_id] = rec
            return len(rows)

    def flush_to_sqlite(self) -> int:
        """Persist active in-memory rows to SQLite (graceful shutdown path).

        Returns:
            int: Rows written (skips expired rows; ``0`` when no DB bound).

        Examples:
            >>> import sqlite3
            >>> OpenUIStore(None).flush_to_sqlite()
            0
        """

        if self._conn is None:
            return 0
        now_ns = time.time_ns()
        conn = self._conn

        def _run(rows: list[OpenUIRecord]) -> int:
            n = 0
            for r in rows:
                if now_ns > r.expires_at_ns:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO openui_tokens (
                        record_id, workspace_id, session_id, message_id, channel,
                        sanitised_html, expires_at_ns, submit_consumed, fallback_text, extra_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r.record_id,
                        r.workspace_id,
                        r.session_id,
                        r.message_id,
                        r.channel,
                        r.sanitised_html,
                        r.expires_at_ns,
                        1 if r.submit_consumed else 0,
                        r.fallback_text,
                        json.dumps(r.extra, separators=(",", ":"), default=str),
                    ),
                )
                n += 1
            conn.commit()
            return n

        with self._lock:
            rows = list(self._by_id.values())
            return _run(rows)


__all__ = ["OpenUIRecord", "OpenUIStore"]
