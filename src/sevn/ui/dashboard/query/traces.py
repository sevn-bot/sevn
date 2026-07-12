"""Parameterized trace SQL readers for Mission Control.

Module: sevn.ui.dashboard.query.traces
Depends: json, sqlite3, sevn.agent.tracing.redacting_sink, sevn.agent.tracing.traces_migrate, sevn.storage.sqlite

Exports:
    ensure_trace_connection — open and migrate ``traces.db`` via spec 04 helper.
    list_trace_events — cursor-paginated trace browse.
    get_span_with_children — one span plus descendant tree for detail view.
    list_provider_calls — per-session provider-call rows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.storage.sqlite import connect_sqlite

_TRACE_COLUMNS = """
    span_id, parent_span_id, session_id, turn_id, tier, kind,
    ts_start_ns, ts_end_ns, status, attrs_json
"""


def ensure_trace_connection(db_path: Path) -> sqlite3.Connection:
    """Open ``traces.db`` and apply owner spec migrations.

    Args:
        db_path (Path): Trace database path under ``.sevn``.

    Returns:
        sqlite3.Connection: Open connection; caller closes it.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> conn = ensure_trace_connection(Path(tempfile.mkdtemp()) / "traces.db")
        >>> conn.execute("SELECT name FROM sqlite_master WHERE name='trace_events'").fetchone()[0]
        'trace_events'
        >>> conn.close()
    """

    conn = connect_sqlite(db_path)
    apply_traces_migrations(conn)
    return conn


def _mask_llmignore_paths(value: object) -> object:
    """Replace ``.llmignore`` path strings with a fixed sentinel.

    Args:
        value (object): Parsed JSON value.

    Returns:
        object: Structure with quarantined path strings masked.

    Examples:
        >>> _mask_llmignore_paths("/workspace/.llmignore/secret.txt")
        '[REDACTED_PATH]'
    """

    if isinstance(value, dict):
        return {str(k): _mask_llmignore_paths(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_llmignore_paths(item) for item in value]
    if isinstance(value, str) and ".llmignore" in value.lower():
        return "[REDACTED_PATH]"
    return value


def _decode_attrs(attrs_json: str, policy: TraceRedactionPolicy) -> dict[str, object]:
    """Decode ``attrs_json`` with workspace redaction and path masking.

    Args:
        attrs_json (str): Raw JSON text from ``trace_events``.
        policy (TraceRedactionPolicy): Resolved ``tracing.redaction`` rules.

    Returns:
        dict[str, object]: Parsed attributes or empty dict.

    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> _decode_attrs("{}", policy)
        {}
    """

    try:
        parsed = json.loads(attrs_json)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    redacted = redact_attrs(parsed, policy)
    masked = _mask_llmignore_paths(redacted)
    return masked if isinstance(masked, dict) else {}


def _row_to_span(row: tuple[object, ...], policy: TraceRedactionPolicy) -> dict[str, object]:
    """Map one ``trace_events`` row to a JSON-serialisable span dict.

    Args:
        row (tuple[object, ...]): SQLite row in ``_TRACE_COLUMNS`` order.
        policy (TraceRedactionPolicy): Redaction policy for ``attrs_json``.

    Returns:
        dict[str, object]: Span payload for dashboard APIs.

    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> span = _row_to_span(
        ...     ("s1", None, "sess", "t1", "B", "b_turn", 1, 2, "ok", "{}"),
        ...     policy,
        ... )
        >>> span["span_id"]
        's1'
    """

    return {
        "span_id": row[0],
        "parent_span_id": row[1],
        "session_id": row[2],
        "turn_id": row[3],
        "tier": row[4],
        "kind": row[5],
        "ts_start_ns": row[6],
        "ts_end_ns": row[7],
        "status": row[8],
        "attrs": _decode_attrs(str(row[9]), policy),
    }


def _next_cursor(items: list[dict[str, Any]], limit: int) -> str | None:
    """Return opaque cursor from the last row of an over-fetched page.

    Args:
        items (list[dict[str, Any]]): Fetched rows (length may be ``limit+1``).
        limit (int): Requested page size.

    Returns:
        str | None: Cursor string or ``None`` when the page has no next slice.

    Examples:
        >>> _next_cursor([{"ts_start_ns": "9"}], 1) is None
        True
        >>> _next_cursor([{"ts_start_ns": "9"}, {"ts_start_ns": "8"}], 1)
        '9'
    """

    if len(items) <= limit:
        return None
    last = items[limit - 1]
    return str(last["ts_start_ns"])


def list_trace_events(
    conn: sqlite3.Connection,
    *,
    limit: int,
    policy: TraceRedactionPolicy,
    cursor: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    kind: str | None = None,
    kind_prefixes: list[str] | None = None,
    issue_id: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    budget_regime: str | None = None,
    model_id: str | None = None,
    job_id: str | None = None,
    ts_from_ns: int | None = None,
    ts_to_ns: int | None = None,
) -> dict[str, object]:
    """Return trace rows sorted by ``ts_start_ns DESC``.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        limit (int): Clamped page size.
        policy (TraceRedactionPolicy): Redaction policy applied on read.
        cursor (str | None): Previous page cursor; interpreted as ``ts_start_ns``.
        session_id (str | None): Optional session filter.
        turn_id (str | None): Optional turn filter.
        kind (str | None): Optional exact trace kind filter.
        kind_prefixes (list[str] | None): Optional ``kind LIKE prefix%`` OR filters.
        issue_id (str | None): Optional ``attrs.issue_id`` filter (evolution spans).
        status (str | None): Optional status filter.
        tier (str | None): Optional executor tier filter (indexed column).
        budget_regime (str | None): Optional ``attrs.budget_regime`` filter.
        model_id (str | None): Optional ``attrs.model_id`` filter.
        job_id (str | None): Optional ``attrs.job_id`` filter (self-improve spans).
        ts_from_ns (int | None): Inclusive lower bound on ``ts_start_ns``.
        ts_to_ns (int | None): Inclusive upper bound on ``ts_start_ns``.

    Returns:
        dict[str, object]: ``items`` / ``next_cursor`` / ``has_more`` page.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> list_trace_events(conn, limit=2, policy=policy)["items"]
        []
        >>> conn.close()
    """

    where: list[str] = []
    params: list[object] = []
    if cursor:
        try:
            cursor_ns = int(cursor)
        except ValueError:
            cursor_ns = 0
        if cursor_ns > 0:
            where.append("ts_start_ns < ?")
            params.append(cursor_ns)
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if turn_id:
        where.append("turn_id = ?")
        params.append(turn_id)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if kind_prefixes:
        clauses = ["kind LIKE ?" for _ in kind_prefixes]
        where.append("(" + " OR ".join(clauses) + ")")
        params.extend(f"{prefix}%" for prefix in kind_prefixes)
    if issue_id:
        where.append("json_extract(attrs_json, '$.issue_id') = ?")
        params.append(issue_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if tier:
        where.append("tier = ?")
        params.append(tier)
    if budget_regime:
        where.append("json_extract(attrs_json, '$.budget_regime') = ?")
        params.append(budget_regime)
    if model_id:
        where.append("json_extract(attrs_json, '$.model_id') = ?")
        params.append(model_id)
    if job_id:
        where.append("json_extract(attrs_json, '$.job_id') = ?")
        params.append(job_id)
    if ts_from_ns is not None:
        where.append("ts_start_ns >= ?")
        params.append(ts_from_ns)
    if ts_to_ns is not None:
        where.append("ts_start_ns <= ?")
        params.append(ts_to_ns)
    sql = f"SELECT {_TRACE_COLUMNS} FROM trace_events"  # nosec B608 — column list is fixed
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts_start_ns DESC LIMIT ?"
    params.append(limit + 1)
    rows = conn.execute(sql, tuple(params)).fetchall()
    items = [_row_to_span(row, policy) for row in rows]
    next_cursor = _next_cursor(items, limit)
    return {"items": items[:limit], "next_cursor": next_cursor, "has_more": next_cursor is not None}


def _attach_children(
    span: dict[str, object], children_by_parent: dict[str, list[dict[str, object]]]
) -> dict[str, object]:
    """Recursively attach sorted ``children`` for one span node.

    Args:
        span (dict[str, object]): Span dict without ``children``.
        children_by_parent (dict[str, list[dict[str, object]]]): Parent id to child rows.

    Returns:
        dict[str, object]: Span dict with nested ``children`` list.

    Examples:
        >>> root = {"span_id": "r", "ts_start_ns": 1}
        >>> out = _attach_children(root, {})
        >>> out["children"]
        []
    """

    span_id = str(span["span_id"])
    kids = sorted(
        children_by_parent.get(span_id, []),
        key=lambda row: int(str(row["ts_start_ns"])),
    )
    return {
        **span,
        "children": [_attach_children(child, children_by_parent) for child in kids],
    }


def get_span_with_children(
    conn: sqlite3.Connection,
    span_id: str,
    *,
    policy: TraceRedactionPolicy,
) -> dict[str, object] | None:
    """Return one span and its descendant tree for the span detail API.

    Spans may arrive out of order in ``trace_events``; tree assembly indexes the
    full session slice before linking ``parent_span_id`` edges.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        span_id (str): Target span primary key.
        policy (TraceRedactionPolicy): Redaction policy applied on read.

    Returns:
        dict[str, object] | None: Nested span tree rooted at ``span_id``, or ``None``.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> get_span_with_children(conn, "missing", policy=policy) is None
        True
        >>> conn.close()
    """

    root_row = conn.execute(
        f"SELECT {_TRACE_COLUMNS} FROM trace_events WHERE span_id = ?",  # nosec B608
        (span_id,),
    ).fetchone()
    if root_row is None:
        return None
    session_id = str(root_row[2])
    rows = conn.execute(
        f"SELECT {_TRACE_COLUMNS} FROM trace_events WHERE session_id = ? ORDER BY ts_start_ns ASC",  # nosec B608
        (session_id,),
    ).fetchall()
    spans = [_row_to_span(row, policy) for row in rows]
    by_id = {str(span["span_id"]): span for span in spans}
    if span_id not in by_id:
        return None
    children_by_parent: dict[str, list[dict[str, object]]] = {}
    for span in spans:
        parent = span.get("parent_span_id")
        if parent:
            children_by_parent.setdefault(str(parent), []).append(span)
    return _attach_children(by_id[span_id], children_by_parent)


def list_provider_calls(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    limit: int,
    policy: TraceRedactionPolicy,
    cursor: str | None = None,
) -> dict[str, object]:
    """Return ``provider.call`` rows for one session sorted oldest first.

    Args:
        conn (sqlite3.Connection): Open ``traces.db`` connection.
        session_id (str): Session id filter.
        limit (int): Clamped page size.
        policy (TraceRedactionPolicy): Redaction policy applied on read.
        cursor (str | None): Previous page cursor; interpreted as ``ts_start_ns``.

    Returns:
        dict[str, object]: ``items`` / ``next_cursor`` / ``has_more`` page.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.tracing.traces_migrate import apply_traces_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_traces_migrations(conn)
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> list_provider_calls(conn, session_id="s", limit=2, policy=policy)["items"]
        []
        >>> conn.close()
    """

    where = ["session_id = ?", "kind = ?"]
    params: list[object] = [session_id, "provider.call"]
    if cursor:
        try:
            cursor_ns = int(cursor)
        except ValueError:
            cursor_ns = 0
        if cursor_ns > 0:
            where.append("ts_start_ns > ?")
            params.append(cursor_ns)
    sql = (
        f"SELECT {_TRACE_COLUMNS} FROM trace_events WHERE "  # nosec B608
        + " AND ".join(where)
        + " ORDER BY ts_start_ns ASC LIMIT ?"
    )
    params.append(limit + 1)
    rows = conn.execute(sql, tuple(params)).fetchall()
    items = [_row_to_span(row, policy) for row in rows]
    next_cursor = None if len(items) <= limit else str(items[limit - 1]["ts_start_ns"])
    return {"items": items[:limit], "next_cursor": next_cursor, "has_more": next_cursor is not None}
