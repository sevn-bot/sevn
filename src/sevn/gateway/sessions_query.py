"""Read/write gateway session helpers for bundled skill scripts (`specs/17-gateway.md`).

Module: sevn.gateway.sessions_query
Depends: json, sqlite3, uuid, sevn.gateway.session_manager

Exports:
    cap_history_limit — clamp helper for history row caps.
    parse_session_metadata — decode ``gateway_sessions.metadata_json``.
    can_access_session — visibility guard for list/history/send.
    list_sessions — visibility-scoped session index.
    list_sessions_active_between — sessions with messages in a date window (by created_at).
    session_operator_timezone — operator IANA timezone for a session (UTC fallback).
    fetch_session_history — message rows for one session (optional keyword filter).
    search_messages — cross-session keyword search (visibility-scoped).
    send_to_session — append a user/system line to a session.
    insert_message — synchronous ``gateway_messages`` append helper.
    spawn_subagent — mint an isolated subagent session row.
    record_yield — persist yield payload and optional delegation.
    session_status_snapshot — run-state projection from SQLite.

Examples:
    >>> from sevn.gateway.sessions_query import parse_session_metadata
    >>> parse_session_metadata(None)
    {}
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from sevn.gateway.session_manager import load_session_row, unanswered_tail_message_id

_DEFAULT_LIST_LIMIT = 50
_DEFAULT_HISTORY_LIMIT = 20
_MAX_HISTORY_LIMIT = 200
MAX_HISTORY_LIMIT = _MAX_HISTORY_LIMIT
_DEFAULT_EXCERPT_CHARS = 500
_SUBAGENT_CHANNEL = "internal"


def _utc_now_iso() -> str:
    """Return UTC timestamp suitable for SQLite text columns.

    Returns:
        str: ISO-8601 string with naive tzinfo stripped.

    Examples:
        >>> isinstance(_utc_now_iso(), str)
        True
    """
    return datetime.now(tz=UTC).replace(tzinfo=None).isoformat()


def parse_session_metadata(raw: str | None) -> dict[str, Any]:
    """Decode ``gateway_sessions.metadata_json`` into a dict.

    Args:
        raw (str | None): Stored JSON blob.

    Returns:
        dict[str, Any]: Parsed metadata or empty dict.

    Examples:
        >>> parse_session_metadata('{"parent_session_id":"abc"}')["parent_session_id"]
        'abc'
        >>> parse_session_metadata(None)
        {}
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_metadata(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Return metadata for one session id.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str): Gateway session id.

    Returns:
        dict[str, Any]: Parsed metadata or empty dict.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_metadata(c, "missing")
        {}
    """
    row = conn.execute(
        "SELECT metadata_json FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return {}
    return parse_session_metadata(str(row[0]) if row[0] is not None else None)


def _parent_session_id(meta: dict[str, Any]) -> str | None:
    """Return parent session id from metadata when present.

    Args:
        meta (dict[str, Any]): Parsed session metadata.

    Returns:
        str | None: Parent id or ``None``.

    Examples:
        >>> _parent_session_id({"parent_session_id": "p1"})
        'p1'
    """
    pid = meta.get("parent_session_id")
    return str(pid) if pid else None


def _session_type(meta: dict[str, Any]) -> str:
    """Return session type marker from metadata.

    Args:
        meta (dict[str, Any]): Parsed session metadata.

    Returns:
        str: ``sub`` or ``main``.

    Examples:
        >>> _session_type({"session_type": "sub"})
        'sub'
    """
    st = meta.get("session_type")
    return str(st) if st else "main"


def can_access_session(
    conn: sqlite3.Connection,
    caller_session_id: str | None,
    target_session_id: str,
) -> bool:
    """Return whether ``caller_session_id`` may read or write ``target_session_id``.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        caller_session_id (str | None): Active gateway session; ``None`` is workspace admin.
        target_session_id (str): Candidate session id.

    Returns:
        bool: ``True`` when visibility rules allow access.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> can_access_session(c, None, "any")
        True
    """
    if caller_session_id is None:
        return True
    if caller_session_id == target_session_id:
        return True
    if load_session_row(conn, target_session_id) is None:
        return False
    caller_meta = _load_metadata(conn, caller_session_id)
    target_meta = _load_metadata(conn, target_session_id)
    caller_parent = _parent_session_id(caller_meta)
    target_parent = _parent_session_id(target_meta)
    if target_parent == caller_session_id or caller_parent == target_session_id:
        return True
    if caller_parent and caller_parent == target_parent:
        return True
    return _session_type(caller_meta) != "sub" and _session_type(target_meta) != "sub"


def _session_row_dict(
    conn: sqlite3.Connection,
    row: tuple[Any, ...],
) -> dict[str, Any]:
    """Project one ``gateway_sessions`` row to a JSON-friendly dict.

    Args:
        conn (sqlite3.Connection): Workspace DB (for message counts).
        row (tuple[Any, ...]): ``session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json``.

    Returns:
        dict[str, Any]: Session summary row.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> now = "2026-01-01T00:00:00"
        >>> _ = c.execute(
        ...     "INSERT INTO gateway_sessions (session_id, scope_key, channel, user_id, "
        ...     "created_at, updated_at) VALUES ('s1', 'web:u1', 'web', 'u1', ?, ?)",
        ...     (now, now),
        ... )
        >>> c.commit()
        >>> row = c.execute(
        ...     "SELECT session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json "
        ...     "FROM gateway_sessions WHERE session_id = 's1'"
        ... ).fetchone()
        >>> _session_row_dict(c, row)["session_id"]
        's1'
    """
    sid = str(row[0])
    meta = parse_session_metadata(str(row[6]) if row[6] is not None else None)
    count_row = conn.execute(
        "SELECT COUNT(*) FROM gateway_messages WHERE session_id = ?",
        (sid,),
    ).fetchone()
    msg_count = int(count_row[0]) if count_row else 0
    return {
        "session_id": sid,
        "scope_key": str(row[1]),
        "channel": str(row[2]),
        "user_id": str(row[3]),
        "created_at": str(row[4]),
        "updated_at": str(row[5]),
        "message_count": msg_count,
        "session_type": _session_type(meta),
        "parent_session_id": _parent_session_id(meta),
    }


def list_sessions(
    conn: sqlite3.Connection,
    *,
    caller_session_id: str | None = None,
    channel: str | None = None,
    user_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = _DEFAULT_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """Return visibility-scoped gateway sessions ordered by ``updated_at`` desc.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        caller_session_id (str | None, optional): Active session for visibility filter.
        channel (str | None, optional): Optional channel filter.
        user_id (str | None, optional): Optional user id filter.
        date_from (str | None, optional): Lower bound on ``updated_at`` (ISO date/time).
        date_to (str | None, optional): Upper bound on ``updated_at``.
        limit (int, optional): Max rows. Defaults to ``50``.

    Returns:
        list[dict[str, Any]]: Session summary rows.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> list_sessions(c)
        []
    """
    clauses = ["1=1"]
    params: list[Any] = []
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if date_from:
        clauses.append("datetime(updated_at) >= datetime(?)")
        params.append(date_from)
    if date_to:
        clauses.append("datetime(updated_at) <= datetime(?)")
        params.append(date_to)
    sql = f"""
        SELECT session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json
        FROM gateway_sessions
        WHERE {" AND ".join(clauses)}
        ORDER BY updated_at DESC
    """  # nosec B608 — clauses are fixed column predicates with bound params
    rows = conn.execute(sql, params).fetchall()
    items = [_session_row_dict(conn, row) for row in rows]
    if caller_session_id:
        items = [
            item
            for item in items
            if can_access_session(conn, caller_session_id, str(item["session_id"]))
        ]
    return items[: max(1, limit)]


def list_sessions_active_between(
    conn: sqlite3.Connection,
    *,
    since: str | None,
    until: str | None,
    caller_session_id: str | None = None,
    limit: int = _DEFAULT_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """Return sessions with at least one message in ``[since, until)``.

    Uses ``gateway_messages.created_at`` — the reliable per-message signal — rather
    than ``gateway_sessions.updated_at``, which is bulk-refreshed at gateway boot
    and therefore cannot indicate when a conversation was actually active. Rows are
    ordered by most-recent in-window message and carry window-scoped stats
    (``message_count``, ``first_message_at``, ``last_message_at``).

    Args:
        conn (sqlite3.Connection): Workspace DB.
        since (str | None): Inclusive lower bound (naive-UTC ISO), or ``None``.
        until (str | None): Exclusive upper bound (naive-UTC ISO), or ``None``.
        caller_session_id (str | None, optional): Visibility guard session id.
        limit (int, optional): Max rows. Defaults to ``50``.

    Returns:
        list[dict[str, Any]]: Session summaries active in the window.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> list_sessions_active_between(c, since="2026-07-02T00:00:00", until="2026-07-03T00:00:00")
        []
    """
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append("datetime(m.created_at) >= datetime(?)")
        params.append(since)
    if until:
        clauses.append("datetime(m.created_at) < datetime(?)")
        params.append(until)
    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"""
        SELECT m.session_id,
               COUNT(*) AS n,
               MIN(m.created_at) AS first_at,
               MAX(m.created_at) AS last_at,
               s.channel,
               s.user_id,
               s.metadata_json
        FROM gateway_messages m
        JOIN gateway_sessions s ON s.session_id = m.session_id
        WHERE {where}
        GROUP BY m.session_id
        ORDER BY MAX(m.created_at) DESC
    """  # nosec B608 — clauses are fixed column predicates with bound params
    rows = conn.execute(sql, params).fetchall()
    items: list[dict[str, Any]] = []
    for sid, count, first_at, last_at, channel, user_id, metadata_json in rows:
        sid_s = str(sid)
        if not can_access_session(conn, caller_session_id, sid_s):
            continue
        meta = parse_session_metadata(str(metadata_json) if metadata_json is not None else None)
        items.append(
            {
                "session_id": sid_s,
                "channel": str(channel or ""),
                "user_id": str(user_id or ""),
                "message_count": int(count),
                "first_message_at": str(first_at),
                "last_message_at": str(last_at),
                "session_type": _session_type(meta),
            }
        )
        if len(items) >= max(1, limit):
            break
    return items


def session_operator_timezone(conn: sqlite3.Connection, session_id: str | None) -> str:
    """Return the operator IANA timezone for ``session_id`` (``UTC`` fallback).

    Reads the session's ``(channel, user_id)`` and looks up the stored user
    profile timezone. Any lookup failure, missing session, or missing profile
    yields ``"UTC"`` so relative-date resolution never breaks.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str | None): Session id whose owner timezone is wanted.

    Returns:
        str: IANA timezone name, or ``"UTC"``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> session_operator_timezone(c, None)
        'UTC'
    """
    if not session_id:
        return "UTC"
    try:
        row = conn.execute(
            "SELECT channel, user_id FROM gateway_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return "UTC"
        from sevn.gateway.user_profile import get_user_profile

        profile = get_user_profile(conn, channel=str(row[0]), user_id=str(row[1]))
        return profile.timezone or "UTC"
    except (sqlite3.Error, ValueError):
        return "UTC"


def _sanitize_content(content: str, *, full: bool) -> tuple[str, bool]:
    """Compact message bodies for agent-facing history unless ``full`` is set.

    Args:
        content (str): Raw stored text.
        full (bool): When ``True``, return unchanged.

    Returns:
        tuple[str, bool]: ``(body, truncated)`` where ``truncated`` is ``True``
            when the body was shortened to :data:`_DEFAULT_EXCERPT_CHARS`.

    Examples:
        >>> body, truncated = _sanitize_content("x" * 600, full=False)
        >>> len(body) == 500 and truncated
        True
        >>> _sanitize_content("hi", full=False)[1]
        False
    """
    if full or len(content) <= _DEFAULT_EXCERPT_CHARS:
        return content, False
    return content[:_DEFAULT_EXCERPT_CHARS], True


def cap_history_limit(limit: int) -> int:
    """Clamp a history row cap to ``1..MAX_HISTORY_LIMIT``.

    Args:
        limit (int): Requested row cap.

    Returns:
        int: Clamped cap.

    Examples:
        >>> cap_history_limit(0)
        1
        >>> cap_history_limit(999)
        200
    """
    return max(1, min(int(limit), MAX_HISTORY_LIMIT))


def fetch_session_history(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    caller_session_id: str | None = None,
    query: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = _DEFAULT_HISTORY_LIMIT,
    offset: int = 0,
    full: bool = False,
) -> dict[str, Any]:
    """Return message history for one session.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str): Target session id.
        caller_session_id (str | None, optional): Visibility guard session id.
        query (str | None, optional): Case-insensitive substring filter on content.
        since (str | None, optional): Lower bound (inclusive) on ``created_at``
            as naive-UTC ISO; rows before it are dropped.
        until (str | None, optional): Upper bound (exclusive) on ``created_at``.
        limit (int, optional): Max messages. Defaults to ``20``.
        offset (int, optional): Skip first N rows after ordering.
        full (bool, optional): Disable content truncation. Defaults to ``False``.

    Returns:
        dict[str, Any]: ``session_id`` plus ``messages`` list.

    Raises:
        ValueError: When session is missing or not visible.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> try:
        ...     fetch_session_history(c, "missing")
        ... except ValueError:
        ...     raised = True
        ... else:
        ...     raised = False
        >>> raised
        True
    """
    if load_session_row(conn, session_id) is None:
        msg = f"session not found: {session_id}"
        raise ValueError(msg)
    if not can_access_session(conn, caller_session_id, session_id):
        msg = f"session not visible: {session_id}"
        raise ValueError(msg)
    capped_limit = cap_history_limit(limit)
    clauses = ["session_id = ?"]
    params: list[Any] = [session_id]
    if since:
        clauses.append("datetime(created_at) >= datetime(?)")
        params.append(since)
    if until:
        clauses.append("datetime(created_at) < datetime(?)")
        params.append(until)
    sql = f"""
        SELECT id, role, kind, content, status, created_at, visible_to_llm
        FROM gateway_messages
        WHERE {" AND ".join(clauses)}
        ORDER BY id ASC
    """  # nosec B608 — clauses are fixed column predicates with bound params
    rows = conn.execute(sql, params).fetchall()
    messages: list[dict[str, Any]] = []
    q = (query or "").strip().lower()
    for mid, role, kind, content, status, created_at, visible in rows:
        body = str(content or "")
        if q and q not in body.lower():
            continue
        compact, truncated = _sanitize_content(body, full=full)
        row: dict[str, Any] = {
            "id": int(mid),
            "role": str(role),
            "kind": str(kind),
            "content": compact,
            "status": str(status),
            "created_at": str(created_at),
            "visible_to_llm": bool(visible),
        }
        if truncated:
            row["truncated"] = True
        messages.append(row)
    window = messages[offset : offset + capped_limit]
    return {"session_id": session_id, "messages": window, "total": len(messages)}


def search_messages(
    conn: sqlite3.Connection,
    query: str,
    *,
    caller_session_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = _DEFAULT_HISTORY_LIMIT,
    full: bool = False,
) -> list[dict[str, Any]]:
    """Keyword- and/or date-search visible gateway messages across sessions.

    Either ``query`` (substring) or a date bound (``since``/``until``) must be
    given; when ``query`` is empty the search is date-only, returning every
    visible message in the window (answers "what did we talk about yesterday").

    Args:
        conn (sqlite3.Connection): Workspace DB.
        query (str): Case-insensitive substring; may be empty when a date bound
            is supplied.
        caller_session_id (str | None, optional): Visibility guard session id.
        since (str | None, optional): Lower bound (inclusive) on ``created_at``
            as naive-UTC ISO.
        until (str | None, optional): Upper bound (exclusive) on ``created_at``.
        limit (int, optional): Max hits. Defaults to ``20``.
        full (bool, optional): Disable content truncation. Defaults to ``False``.

    Returns:
        list[dict[str, Any]]: Hit rows with ``session_id`` and message fields.

    Raises:
        ValueError: When neither ``query`` nor a date bound is provided.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> search_messages(c, "hello")
        []
    """
    q = query.strip()
    if not q and not since and not until:
        msg = "query or a date bound (since/until) is required"
        raise ValueError(msg)
    capped_limit = cap_history_limit(limit)
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append("LOWER(m.content) LIKE ?")
        params.append(f"%{q.lower()}%")
    if since:
        clauses.append("datetime(m.created_at) >= datetime(?)")
        params.append(since)
    if until:
        clauses.append("datetime(m.created_at) < datetime(?)")
        params.append(until)
    params.append(max(capped_limit * 4, capped_limit))
    sql = f"""
        SELECT m.id, m.session_id, m.role, m.kind, m.content, m.status, m.created_at
        FROM gateway_messages m
        WHERE {" AND ".join(clauses)}
        ORDER BY m.id DESC
        LIMIT ?
    """  # nosec B608 — clauses are fixed column predicates with bound params
    rows = conn.execute(sql, params).fetchall()
    hits: list[dict[str, Any]] = []
    for mid, sid, role, kind, content, status, created_at in rows:
        sid_s = str(sid)
        if not can_access_session(conn, caller_session_id, sid_s):
            continue
        compact, truncated = _sanitize_content(str(content or ""), full=full)
        hit: dict[str, Any] = {
            "session_id": sid_s,
            "id": int(mid),
            "role": str(role),
            "kind": str(kind),
            "content": compact,
            "status": str(status),
            "created_at": str(created_at),
        }
        if truncated:
            hit["truncated"] = True
        hits.append(hit)
        if len(hits) >= capped_limit:
            break
    return hits


def insert_message(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    role: str,
    kind: str,
    content: str,
    visible_to_llm: int = 1,
    status: str = "sent",
    extras_json: str | None = None,
    turn_id: str = "-",
) -> int:
    """Append one ``gateway_messages`` row synchronously.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str): Owning session id.
        role (str): ``user``, ``assistant``, or ``system``.
        kind (str): Row kind (``message``, ``command``, ``steer``, ...).
        content (str): Stored body.
        visible_to_llm (int, optional): ``1`` when LLM-visible. Defaults to ``1``.
        status (str, optional): Delivery status. Defaults to ``sent``.
        extras_json (str | None, optional): Optional JSON extras blob.
        turn_id (str, optional): Turn correlation id; defaults to the
            ``SYSTEM_TURN_ID`` sentinel ``'-'`` for synchronous admin/test
            inserts that do not belong to a turn.

    Returns:
        int: New ``gateway_messages.id``.

    Raises:
        ValueError: When session id is unknown or ``turn_id`` is empty.
        RuntimeError: When SQLite omits ``lastrowid``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> now = "2026-01-01T00:00:00"
        >>> _ = c.execute(
        ...     "INSERT INTO gateway_sessions (session_id, scope_key, channel, user_id, "
        ...     "created_at, updated_at) VALUES ('s1', 'web:u1', 'web', 'u1', ?, ?)",
        ...     (now, now),
        ... )
        >>> c.commit()
        >>> insert_message(c, "s1", role="user", kind="message", content="hi") > 0
        True
    """
    if load_session_row(conn, session_id) is None:
        msg = f"session not found: {session_id}"
        raise ValueError(msg)
    if not turn_id:
        msg = "insert_message: turn_id must be non-empty; use '-' for non-turn rows"
        raise ValueError(msg)
    now = _utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status,
            extras_json, created_at, turn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            role,
            kind,
            content,
            visible_to_llm,
            status,
            extras_json,
            now,
            turn_id,
        ),
    )
    lid = cur.lastrowid
    if lid is None:
        msg = "sqlite lastrowid unavailable after message INSERT"
        raise RuntimeError(msg)
    conn.execute(
        "UPDATE gateway_sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()
    return int(lid)


def send_to_session(
    conn: sqlite3.Connection,
    session_id: str,
    text: str,
    *,
    caller_session_id: str | None = None,
    role: str = "user",
) -> dict[str, Any]:
    """Post one line to another session's history.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str): Target session id.
        text (str): Message body.
        caller_session_id (str | None, optional): Visibility guard session id.
        role (str, optional): Stored role. Defaults to ``user``.

    Returns:
        dict[str, Any]: ``session_id`` and new ``message_id``.

    Raises:
        ValueError: When session is missing, invisible, or text is empty.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> try:
        ...     send_to_session(c, "missing", "hi")
        ... except ValueError:
        ...     raised = True
        ... else:
        ...     raised = False
        >>> raised
        True
    """
    body = text.strip()
    if not body:
        msg = "text is required"
        raise ValueError(msg)
    if not can_access_session(conn, caller_session_id, session_id):
        msg = f"session not visible: {session_id}"
        raise ValueError(msg)
    mid = insert_message(conn, session_id, role=role, kind="message", content=body)
    return {"session_id": session_id, "message_id": mid}


def spawn_subagent(
    conn: sqlite3.Connection,
    parent_session_id: str,
    *,
    caller_session_id: str | None = None,
    system_prompt: str | None = None,
    tool_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Mint a new subagent session linked to ``parent_session_id``.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        parent_session_id (str): Owning parent gateway session id.
        caller_session_id (str | None, optional): Must match parent when set.
        system_prompt (str | None, optional): Optional system preamble row.
        tool_allowlist (list[str] | None, optional): Optional tool name allowlist.

    Returns:
        dict[str, Any]: New child ``session_id`` and metadata echo.

    Raises:
        ValueError: When parent is missing or caller cannot access it.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> try:
        ...     spawn_subagent(c, "missing")
        ... except ValueError:
        ...     raised = True
        ... else:
        ...     raised = False
        >>> raised
        True
    """
    if load_session_row(conn, parent_session_id) is None:
        msg = f"parent session not found: {parent_session_id}"
        raise ValueError(msg)
    if (
        caller_session_id
        and caller_session_id != parent_session_id
        and not can_access_session(conn, caller_session_id, parent_session_id)
    ):
        msg = f"parent session not visible: {parent_session_id}"
        raise ValueError(msg)
    child_id = uuid.uuid4().hex
    scope_key = f"subagent:{child_id}"
    user_id = f"subagent-{child_id[:8]}"
    now = _utc_now_iso()
    meta: dict[str, Any] = {
        "parent_session_id": parent_session_id,
        "session_type": "sub",
    }
    if tool_allowlist:
        meta["tool_allowlist"] = list(tool_allowlist)
    if system_prompt:
        meta["system_prompt"] = system_prompt.strip()
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            child_id,
            scope_key,
            _SUBAGENT_CHANNEL,
            user_id,
            now,
            now,
            json.dumps(meta, separators=(",", ":")),
        ),
    )
    conn.commit()
    if system_prompt and system_prompt.strip():
        insert_message(
            conn,
            child_id,
            role="system",
            kind="message",
            content=system_prompt.strip(),
            visible_to_llm=1,
        )
    return {
        "session_id": child_id,
        "parent_session_id": parent_session_id,
        "scope_key": scope_key,
        "channel": _SUBAGENT_CHANNEL,
        "tool_allowlist": list(tool_allowlist or []),
    }


def record_yield(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    caller_session_id: str | None = None,
    payload: dict[str, Any] | None = None,
    reason: str | None = None,
    delegate_to: str | None = None,
    delegate_message: str | None = None,
) -> dict[str, Any]:
    """Persist a yield marker and optional delegation for orchestrator turns.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str): Session yielding control.
        caller_session_id (str | None, optional): Must match ``session_id`` when set.
        payload (dict[str, Any] | None, optional): Hidden follow-up payload.
        reason (str | None, optional): Debug reason string.
        delegate_to (str | None, optional): Target session for delegation.
        delegate_message (str | None, optional): Message posted to delegate session.

    Returns:
        dict[str, Any]: Yield token and delegation echo.

    Raises:
        ValueError: When session is missing or caller mismatch.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> try:
        ...     record_yield(c, "missing")
        ... except ValueError:
        ...     raised = True
        ... else:
        ...     raised = False
        >>> raised
        True
    """
    if load_session_row(conn, session_id) is None:
        msg = f"session not found: {session_id}"
        raise ValueError(msg)
    if caller_session_id and caller_session_id != session_id:
        msg = "yield may only be recorded for the active session"
        raise ValueError(msg)
    meta = _load_metadata(conn, session_id)
    now = _utc_now_iso()
    yield_blob: dict[str, Any] = {"at": now}
    if payload:
        yield_blob["payload"] = payload
    if reason:
        yield_blob["reason"] = reason.strip()
    if delegate_to:
        yield_blob["delegate_to"] = delegate_to
    meta["yield"] = yield_blob
    conn.execute(
        "UPDATE gateway_sessions SET metadata_json = ?, updated_at = ? WHERE session_id = ?",
        (json.dumps(meta, separators=(",", ":")), now, session_id),
    )
    conn.commit()
    steer_body = f"YIELD:{session_id}"
    if reason:
        steer_body = f"{steer_body}:{reason.strip()}"
    insert_message(
        conn,
        session_id,
        role="system",
        kind="steer",
        content=steer_body,
        visible_to_llm=0,
    )
    delegation: dict[str, Any] | None = None
    if delegate_to:
        if load_session_row(conn, delegate_to) is None:
            msg = f"delegate session not found: {delegate_to}"
            raise ValueError(msg)
        if delegate_message and delegate_message.strip():
            send_to_session(
                conn,
                delegate_to,
                delegate_message.strip(),
                caller_session_id=session_id,
            )
        delegation = {"delegate_to": delegate_to, "message_sent": bool(delegate_message)}
    token = f"YIELD:{session_id}"
    if delegate_to:
        token = f"{token}:DELEGATE:{delegate_to}"
    return {"yield_token": token, "session_id": session_id, "delegation": delegation}


def session_status_snapshot(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    caller_session_id: str | None = None,
) -> dict[str, Any]:
    """Return run-state hints derived from gateway SQLite rows.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str): Target session id.
        caller_session_id (str | None, optional): Visibility guard session id.

    Returns:
        dict[str, Any]: Unanswered tail, pending counts, yield metadata, children.

    Raises:
        ValueError: When session is missing or not visible.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> try:
        ...     session_status_snapshot(c, "missing")
        ... except ValueError:
        ...     raised = True
        ... else:
        ...     raised = False
        >>> raised
        True
    """
    row = conn.execute(
        """
        SELECT session_id, scope_key, channel, user_id, updated_at,
               unanswered_tail_message_id, last_final_assistant_message_id, metadata_json
        FROM gateway_sessions WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        msg = f"session not found: {session_id}"
        raise ValueError(msg)
    if not can_access_session(conn, caller_session_id, session_id):
        msg = f"session not visible: {session_id}"
        raise ValueError(msg)
    meta = parse_session_metadata(str(row[7]) if row[7] is not None else None)
    pending_row = conn.execute(
        """
        SELECT COUNT(*) FROM gateway_messages
        WHERE session_id = ? AND status = 'pending'
        """,
        (session_id,),
    ).fetchone()
    pending_count = int(pending_row[0]) if pending_row else 0
    child_rows = conn.execute(
        """
        SELECT session_id FROM gateway_sessions
        WHERE metadata_json LIKE ?
        """,
        (f'%"parent_session_id":"{session_id}"%',),
    ).fetchall()
    children = [str(r[0]) for r in child_rows]
    tail = unanswered_tail_message_id(conn, session_id)
    return {
        "session_id": str(row[0]),
        "scope_key": str(row[1]),
        "channel": str(row[2]),
        "user_id": str(row[3]),
        "updated_at": str(row[4]),
        "unanswered_tail_message_id": tail,
        "last_final_assistant_message_id": int(row[6]) if row[6] is not None else None,
        "pending_message_count": pending_count,
        "session_type": _session_type(meta),
        "parent_session_id": _parent_session_id(meta),
        "yield": meta.get("yield"),
        "child_session_ids": children,
    }
