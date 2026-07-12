"""Short-term memory K/V tools and federated search (`plan/tools-skills-full-inventory-wave-plan.md` Wave 4).

SQLite rows live in the workspace ``memory`` table; ``memory_search`` also scans
``MEMORY.md`` and ``memory/YYYY-MM-DD.md`` daily logs.

Module: sevn.tools.memory_tools
Depends: sqlite3, datetime, sevn.memory.dreaming.sources, sevn.memory.search_telemetry,
    sevn.storage.sqlite, sevn.tools.base, sevn.tools.context, sevn.tools.decorator

Exports:
    memory_get_tool — fetch the latest snippet for a session key.
    memory_store_tool — append a short-term K/V row.
    memory_search_tool — federated substring search across memory layers.
    register_memory_tools — register the three tools on a ``ToolExecutor``.
    store_memory_row — insert one SQLite row (testable helper).
    get_memory_row — fetch latest row for ``(session_id, key)``.
    federated_memory_search — merge hits from SQLite + markdown sources.

Examples:
    >>> from sevn.tools.memory_tools import _normalize_query
    >>> _normalize_query("  Hello  ")
    'hello'
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from sevn.memory.dreaming.sources import load_daily_log_signals
from sevn.memory.search_telemetry import record_memory_search_event
from sevn.storage.sqlite import open_sevn_sqlite
from sevn.tools.base import enveloped_failure, enveloped_success, maybe_spill_large_payload
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolExecutor

DEFAULT_MEMORY_SEARCH_MAX_CHARS: Final[int] = 12_000
DEFAULT_MEMORY_SEARCH_LIMIT: Final[int] = 32
MemorySearchSource = Literal["all", "memory", "daily_log", "memory_md"]

_MEMORY_TOOLS: tuple[Any, ...] = ()


def _iso_now() -> str:
    """Return UTC ISO timestamp for ``memory`` rows.

    Returns:
        str: ISO-8601 timestamp with timezone.

    Examples:
        >>> "T" in _iso_now()
        True
    """
    return datetime.now(tz=UTC).isoformat()


def _normalize_query(query: str) -> str:
    """Lowercase and trim a search needle.

    Args:
        query (str): Raw query text.

    Returns:
        str: Normalized needle (may be empty).

    Examples:
        >>> _normalize_query("  Hello  ")
        'hello'
    """
    return query.strip().lower()


def _matches(text: str, needle: str) -> bool:
    """Return whether ``needle`` appears in ``text`` (case-insensitive).

    Args:
        text (str): Haystack.
        needle (str): Normalized lowercase needle.

    Returns:
        bool: ``True`` when ``needle`` is non-empty and found.

    Examples:
        >>> _matches("Deployment plan", "deploy")
        True
        >>> _matches("alpha", "")
        False
    """
    if not needle:
        return False
    return needle in text.lower()


def _open_workspace_db(workspace_path: Path) -> sqlite3.Connection:
    """Open ``sevn.db`` under ``workspace_path/.sevn`` with migrations applied.

    Args:
        workspace_path (Path): Workspace content root.

    Returns:
        sqlite3.Connection: Open connection; caller must close.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.storage.sqlite import connect_sqlite
        >>> td = tempfile.mkdtemp()
        >>> root = Path(td)
        >>> dot = root / ".sevn"
        >>> _ = dot.mkdir()
        >>> boot = connect_sqlite(dot / "sevn.db")
        >>> apply_migrations(boot)
        >>> boot.close()
        >>> conn = _open_workspace_db(root)
        >>> conn.execute("SELECT 1").fetchone()[0]
        1
        >>> conn.close()
    """
    return open_sevn_sqlite(workspace_path / ".sevn")


def store_memory_row(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    key: str,
    content: str,
    tags: str | None = None,
    metadata: str | None = None,
) -> int:
    """Insert one short-term memory row.

    Args:
        conn (sqlite3.Connection): Workspace database connection.
        session_id (str): Owning session id.
        key (str): Memory key.
        content (str): Stored snippet body.
        tags (str | None): Optional comma-separated tags.
        metadata (str | None): Optional JSON metadata string.

    Returns:
        int: New row ``id``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> row_id = store_memory_row(
        ...     c, session_id="s1", key="prefs", content="dark mode"
        ... )
        >>> row_id >= 1
        True
    """
    cur = conn.execute(
        """
        INSERT INTO memory (key, session_id, content, tags, created_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            key.strip(),
            session_id,
            content,
            tags,
            _iso_now(),
            metadata,
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def get_memory_row(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    key: str,
) -> dict[str, Any] | None:
    """Return the newest row for ``(session_id, key)``.

    Args:
        conn (sqlite3.Connection): Workspace database connection.
        session_id (str): Session scope.
        key (str): Memory key.

    Returns:
        dict[str, Any] | None: Row payload or ``None`` when missing.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = store_memory_row(c, session_id="s1", key="k", content="v")
        >>> get_memory_row(c, session_id="s1", key="k")["content"]
        'v'
    """
    row = conn.execute(
        """
        SELECT id, key, session_id, content, tags, created_at, metadata
        FROM memory
        WHERE session_id = ? AND key = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (session_id, key.strip()),
    ).fetchone()
    if row is None:
        return None
    rid, mem_key, sid, content, tags, created_at, metadata = row
    return {
        "id": int(rid),
        "key": str(mem_key),
        "session_id": str(sid),
        "content": str(content),
        "tags": str(tags) if tags is not None else None,
        "created_at": str(created_at),
        "metadata": str(metadata) if metadata is not None else None,
    }


def _search_sqlite_memory(
    conn: sqlite3.Connection,
    *,
    query: str,
    session_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Search short-term ``memory`` rows by key/content/tags substring.

    Args:
        conn (sqlite3.Connection): Workspace database connection.
        query (str): Raw query string.
        session_id (str): Session scope (includes current session rows only).
        limit (int): Maximum hits.

    Returns:
        list[dict[str, Any]]: Normalised hit rows.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = store_memory_row(c, session_id="s", key="note", content="deploy plan")
        >>> _search_sqlite_memory(c, query="deploy", session_id="s", limit=5)[0]["source"]
        'memory'
    """
    # Empty needle → browse-recent: return the newest rows unfiltered (recall mode).
    needle = _normalize_query(query)
    cur = conn.execute(
        """
        SELECT key, session_id, content, tags, created_at, metadata
        FROM memory
        WHERE session_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (session_id, max(limit * 8, limit)),
    )
    hits: list[dict[str, Any]] = []
    for mem_key, sid, content, tags, created_at, metadata in cur.fetchall():
        blob = " ".join(
            part
            for part in (str(mem_key), str(content), str(tags or ""), str(metadata or ""))
            if part
        )
        if needle and not _matches(blob, needle):
            continue
        hits.append(
            {
                "source": "memory",
                "key": str(mem_key),
                "session_id": str(sid),
                "content": str(content),
                "tags": str(tags) if tags is not None else None,
                "created_at": str(created_at),
                "metadata": str(metadata) if metadata is not None else None,
            },
        )
        if len(hits) >= limit:
            break
    return hits


def _search_memory_md(workspace_root: Path, *, query: str, limit: int) -> list[dict[str, Any]]:
    """Search line hits in workspace ``MEMORY.md``.

    Args:
        workspace_root (Path): Workspace content root.
        query (str): Raw query string.
        limit (int): Maximum hits.

    Returns:
        list[dict[str, Any]]: Normalised hit rows.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "MEMORY.md").write_text("- prefers dark mode\\n", encoding="utf-8")
        ...     hits = _search_memory_md(root, query="dark", limit=5)
        ...     hits[0]["source"]
        'memory_md'
    """
    path = workspace_root / "MEMORY.md"
    if not path.is_file():
        return []
    # Empty needle → browse-recent: return leading entries unfiltered (recall mode).
    needle = _normalize_query(query)
    hits: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if needle and not _matches(text, needle):
            continue
        hits.append(
            {
                "source": "memory_md",
                "path": "MEMORY.md",
                "line": index + 1,
                "content": text,
            },
        )
        if len(hits) >= limit:
            break
    return hits


def _search_daily_logs(workspace_root: Path, *, query: str, limit: int) -> list[dict[str, Any]]:
    """Search ``memory/YYYY-MM-DD.md`` lines for a substring.

    Args:
        workspace_root (Path): Workspace content root.
        query (str): Raw query string.
        limit (int): Maximum hits.

    Returns:
        list[dict[str, Any]]: Normalised hit rows.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     mem = root / "memory"
        ...     _ = mem.mkdir()
        ...     _ = (mem / "2099-01-01.md").write_text("ship timeline\\n", encoding="utf-8")
        ...     _search_daily_logs(root, query="timeline", limit=3)[0]["source"]
        'daily_log'
    """
    # Empty needle → browse-recent: return leading signals unfiltered (recall mode).
    needle = _normalize_query(query)
    hits: list[dict[str, Any]] = []
    for signal in load_daily_log_signals(workspace_root, max_files=120):
        if needle and not _matches(signal.content, needle):
            continue
        hits.append(
            {
                "source": "daily_log",
                "path": f"memory/{signal.topic}.md",
                "date": signal.topic,
                "content": signal.content,
                "created_at": signal.created_at,
            },
        )
        if len(hits) >= limit:
            break
    return hits


def federated_memory_search(
    workspace_root: Path,
    conn: sqlite3.Connection,
    *,
    query: str,
    session_id: str,
    source: MemorySearchSource = "all",
    limit: int = DEFAULT_MEMORY_SEARCH_LIMIT,
    max_chars: int = DEFAULT_MEMORY_SEARCH_MAX_CHARS,
) -> tuple[list[dict[str, Any]], bool]:
    """Merge federated hits and enforce merged character cap.

    Args:
        workspace_root (Path): Workspace content root.
        conn (sqlite3.Connection): Workspace database connection.
        query (str): Substring query.
        session_id (str): Session scope for SQLite branch.
        source (MemorySearchSource): Which layers to scan.
        limit (int): Per-layer hit cap before merge truncation.
        max_chars (int): Merged JSON character budget for hit bodies.

    Returns:
        tuple[list[dict[str, Any]], bool]: Hits and whether output was truncated.

    Examples:
        >>> import sqlite3
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> td = tempfile.mkdtemp()
        >>> root = Path(td)
        >>> mem = root / "memory"
        >>> _ = mem.mkdir()
        >>> _ = (mem / "2099-06-01.md").write_text("alpha beta\\n", encoding="utf-8")
        >>> hits, truncated = federated_memory_search(
        ...     root, c, query="beta", session_id="s", source="daily_log", limit=5
        ... )
        >>> hits[0]["source"]
        'daily_log'
        >>> truncated
        False
    """
    cap = max(1, int(limit))
    merged: list[dict[str, Any]] = []
    if source in ("all", "memory"):
        merged.extend(_search_sqlite_memory(conn, query=query, session_id=session_id, limit=cap))
    if source in ("all", "daily_log"):
        merged.extend(_search_daily_logs(workspace_root, query=query, limit=cap))
    if source in ("all", "memory_md"):
        merged.extend(_search_memory_md(workspace_root, query=query, limit=cap))
    merged = merged[: cap * 3] if source == "all" else merged[:cap]

    total_chars = 0
    kept: list[dict[str, Any]] = []
    truncated = False
    for hit in merged:
        piece = json.dumps(hit, ensure_ascii=False)
        if kept and total_chars + len(piece) > max_chars:
            truncated = True
            break
        kept.append(hit)
        total_chars += len(piece)
    return kept, truncated


def _memory_enabled(workspace_config: WorkspaceConfig | None) -> bool:
    """Return whether short-term memory tools should register.

    Defaults to enabled when ``memory.enabled`` is absent (always-on empty table).

    Args:
        workspace_config (WorkspaceConfig | None): Parsed ``sevn.json``.

    Returns:
        bool: ``False`` only when ``memory.enabled`` is explicitly ``False``.

    Examples:
        >>> _memory_enabled(None)
        True
    """
    if workspace_config is None or workspace_config.memory is None:
        return True
    mem = workspace_config.memory
    enabled = getattr(mem, "enabled", None)
    if enabled is None:
        extra = mem.model_extra or {}
        enabled = extra.get("enabled")
    if enabled is None:
        return True
    return bool(enabled)


@sevn_tool(
    name="memory_store",
    category="memory",
    description="Store a short-term memory snippet in workspace SQLite.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Memory key (session-scoped)."},
            "content": {"type": "string", "description": "Snippet body to persist."},
            "tags": {
                "type": "string",
                "description": "Optional comma-separated tags.",
            },
            "metadata": {
                "type": "object",
                "description": "Optional JSON-safe metadata object.",
            },
        },
        "required": ["key", "content"],
    },
    abortable=True,
)
async def memory_store_tool(
    ctx: ToolContext,
    *,
    key: str,
    content: str,
    tags: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Persist one K/V row in ``sevn.db`` ``memory`` table.

    Args:
        ctx (ToolContext): Invocation context (session + workspace root).
        key (str): Memory key.
        content (str): Snippet body.
        tags (str | None): Optional comma-separated tags.
        metadata (dict[str, Any] | None): Optional JSON metadata.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(memory_store_tool)
        True
    """
    trimmed_key = key.strip()
    if not trimmed_key:
        return enveloped_failure("key must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    if not content:
        return enveloped_failure("content must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    meta_str: str | None = None
    if metadata is not None:
        meta_str = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)
    conn = _open_workspace_db(ctx.workspace_path)
    try:
        row_id = store_memory_row(
            conn,
            session_id=ctx.session_id,
            key=trimmed_key,
            content=content,
            tags=tags.strip() if isinstance(tags, str) and tags.strip() else None,
            metadata=meta_str,
        )
    finally:
        conn.close()
    return enveloped_success(
        {
            "id": row_id,
            "key": trimmed_key,
            "session_id": ctx.session_id,
        },
    )


@sevn_tool(
    name="memory_get",
    category="memory",
    description="Get the latest SQLite memory snippet for a session key.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Memory key to retrieve."},
        },
        "required": ["key"],
    },
    abortable=True,
)
async def memory_get_tool(ctx: ToolContext, *, key: str) -> str:
    """Fetch the newest short-term memory row for the current session.

    Args:
        ctx (ToolContext): Invocation context.
        key (str): Memory key.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(memory_get_tool)
        True
    """
    trimmed_key = key.strip()
    if not trimmed_key:
        return enveloped_failure("key must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    conn = _open_workspace_db(ctx.workspace_path)
    try:
        row = get_memory_row(conn, session_id=ctx.session_id, key=trimmed_key)
    finally:
        conn.close()
    if row is None:
        return enveloped_failure(
            f"no memory row for key {trimmed_key!r}",
            code=ToolResultCode.VALIDATION_ERROR,
            data={"key": trimmed_key},
        )
    return enveloped_success(row)


@sevn_tool(
    name="memory_search",
    category="memory",
    description="Federated search across SQLite memory, daily logs, and MEMORY.md.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Case-insensitive substring query. Omit or pass empty to browse the "
                    "most recent memory entries (recall mode)."
                ),
            },
            "source": {
                "type": "string",
                "enum": ["all", "memory", "daily_log", "memory_md"],
                "description": "Which memory layer to search (default all).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 128,
                "description": "Maximum hits per layer before merge (default 32).",
            },
        },
        "required": [],
    },
    large_result=True,
    abortable=True,
)
async def memory_search_tool(
    ctx: ToolContext,
    *,
    query: str = "",
    source: MemorySearchSource = "all",
    limit: int = DEFAULT_MEMORY_SEARCH_LIMIT,
) -> str:
    """Search short-term SQLite rows plus markdown memory layers.

    Args:
        ctx (ToolContext): Invocation context.
        query (str): Substring query. Empty browses the most recent entries (recall mode).
        source (MemorySearchSource): Layer selector.
        limit (int): Per-layer hit cap.

    Returns:
        str: §3.1 JSON envelope string (may spill when large).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(memory_search_tool)
        True
    """
    # Empty query → browse-recent mode for the recall path: the substring matcher treats ""
    # as "match all", bounded by ``limit`` / ``max_chars``, so an operator asking to recall
    # memory without a specific term gets recent entries instead of a hard error
    # (transcript-review-2026-06-22). This keeps memory_search usable as a session-recall backup.
    needle = query.strip()
    if source not in ("all", "memory", "daily_log", "memory_md"):
        return enveloped_failure(
            f"unsupported source {source!r}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    hit_limit = max(1, min(int(limit), 128))
    max_chars = DEFAULT_MEMORY_SEARCH_MAX_CHARS
    conn = _open_workspace_db(ctx.workspace_path)
    try:
        hits, truncated = federated_memory_search(
            ctx.workspace_path,
            conn,
            query=needle,
            session_id=ctx.session_id,
            source=source,
            limit=hit_limit,
            max_chars=max_chars,
        )
        record_memory_search_event(
            conn,
            session_id=ctx.session_id,
            query_text=needle,
            source=source,
            result_count=len(hits),
        )
    finally:
        conn.close()
    payload = {
        "query": needle,
        "source": source,
        "hits": hits,
        "count": len(hits),
        "truncated": truncated,
    }
    envelope = enveloped_success(payload)
    return maybe_spill_large_payload(ctx.workspace_path, ctx.session_id, envelope_str=envelope)


_MEMORY_TOOLS = (
    memory_get_tool,
    memory_store_tool,
    memory_search_tool,
)


def register_memory_tools(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None = None,
) -> None:
    """Register memory K/V tools when memory is enabled (default on).

    Args:
        executor (ToolExecutor): Registry under construction.
        workspace_config (WorkspaceConfig | None): Parsed workspace config gate.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.memory_tools import register_memory_tools
        >>> exe = ToolExecutor()
        >>> register_memory_tools(exe)
        >>> "memory_get" in {d.name for d in exe.definitions()}
        True
    """
    if not _memory_enabled(workspace_config):
        return
    for tool_fn in _MEMORY_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "DEFAULT_MEMORY_SEARCH_LIMIT",
    "DEFAULT_MEMORY_SEARCH_MAX_CHARS",
    "federated_memory_search",
    "get_memory_row",
    "memory_get_tool",
    "memory_search_tool",
    "memory_store_tool",
    "register_memory_tools",
    "store_memory_row",
]
