"""Read-only inputs from SQLite + workspace logs (`specs/31-memory-dreaming.md` §3.1).

Module: sevn.memory.dreaming.sources
Depends: sqlite3, dataclasses

Exports:
    RawMemorySignal — normalised scoring input row.
    load_memory_signals — short-term ``memory`` table slice.
    load_lcm_summary_signals — read-only ``lcm_summaries`` excerpts.
    load_daily_log_signals — parse ``memory/YYYY-MM-DD.md`` lines.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class RawMemorySignal:
    """One row from ``memory`` + LCM-derived text used by the scorer."""

    source_kind: Literal["memory", "lcm", "daily_log"]
    source_key: str
    session_label: str
    topic: str
    content: str
    created_at: str
    metadata: str | None


def load_memory_signals(conn: sqlite3.Connection, *, limit: int = 500) -> list[RawMemorySignal]:
    """Load recent short-term memory rows (newest first).

    Args:
        conn (sqlite3.Connection): Workspace ``sevn.db`` connection.
        limit (int): Row cap for safety.

    Returns:
        list[RawMemorySignal]: Parsed rows.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> load_memory_signals(c)
        []
    """
    cur = conn.execute(
        """
        SELECT key, session_id, content, tags, created_at, metadata
        FROM memory
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    out: list[RawMemorySignal] = []
    for key, session_id, content, tags, created_at, metadata in cur.fetchall():
        tag = str(tags or "").strip()
        topic = str(key)
        if tag:
            topic = f"{topic}:{tag}"
        out.append(
            RawMemorySignal(
                source_kind="memory",
                source_key=f"memory:{session_id}:{key}",
                session_label=str(session_id),
                topic=topic,
                content=str(content),
                created_at=str(created_at),
                metadata=str(metadata) if metadata is not None else None,
            ),
        )
    return out


def load_lcm_summary_signals(conn: sqlite3.Connection, *, limit: int = 64) -> list[RawMemorySignal]:
    """Load recent LCM summary text joined to conversations.

    Args:
        conn (sqlite3.Connection): Workspace ``sevn.db`` connection.
        limit (int): Row cap.

    Returns:
        list[RawMemorySignal]: Summary rows (empty when LCM tables have no rows).

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> load_lcm_summary_signals(c)
        []
    """
    cur = conn.execute(
        """
        SELECT s.summary_id, s.content, s.created_at, c.session_key, c.channel
        FROM lcm_summaries s
        JOIN lcm_conversations c ON s.conversation_id = c.id
        ORDER BY s.created_at DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    out: list[RawMemorySignal] = []
    for summary_id, content, created_at, session_key, channel in cur.fetchall():
        meta = f'{{"channel": {str(channel)!r}}}'
        out.append(
            RawMemorySignal(
                source_kind="lcm",
                source_key=f"lcm:{summary_id}",
                session_label=str(session_key),
                topic=f"lcm:{summary_id}",
                content=str(content),
                created_at=str(created_at),
                metadata=meta,
            ),
        )
    return out


def load_daily_log_signals(
    workspace_root: Path,
    *,
    max_files: int = 90,
    start: date | None = None,
    end: date | None = None,
) -> list[RawMemorySignal]:
    """Load non-empty lines from ``memory/YYYY-MM-DD.md`` (newest files first).

    Args:
        workspace_root (Path): Workspace content root.
        max_files (int): Maximum daily files to scan when no ``start``/``end``.
        start (date | None): Optional inclusive lower bound on file dates.
        end (date | None): Optional inclusive upper bound on file dates.

    Returns:
        list[RawMemorySignal]: Lines as synthetic signals.

    Examples:
        >>> from pathlib import Path
        >>> from datetime import date
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     m = root / "memory"
        ...     _ = m.mkdir()
        ...     _ = (m / "2099-01-01.md").write_text("hello world\\n", encoding="utf-8")
        ...     load_daily_log_signals(
        ...         root, start=date(2099, 1, 1), end=date(2099, 1, 1)
        ...     )[0].content
        'hello world'
    """
    mem_dir = workspace_root / "memory"
    if not mem_dir.is_dir():
        return []
    files = sorted([p for p in mem_dir.glob("????-??-??.md") if p.is_file()], reverse=True)
    filtered: list[Path] = []
    for path in files:
        try:
            d = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        filtered.append(path)
    if start is None and end is None:
        filtered = filtered[: int(max_files)]
    out: list[RawMemorySignal] = []
    for path in filtered:
        raw = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(raw.splitlines()):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            out.append(
                RawMemorySignal(
                    source_kind="daily_log",
                    source_key=f"daily:{path.name}:{i}",
                    session_label="daily_log",
                    topic=path.stem,
                    content=text,
                    created_at=path.stem,
                    metadata=None,
                ),
            )
    return out
