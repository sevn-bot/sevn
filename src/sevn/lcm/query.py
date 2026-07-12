"""Read-only LCM query helpers for bundled skill scripts (`specs/15-memory-lcm.md` §3).

Module: sevn.lcm.query
Depends: sevn.lcm.search

Exports:
    resolve_conversation_id — map ``session_key`` → ``lcm_conversations.id``.
    conversation_ids_for_scope — fan-out filter for workspace / conversation / topic.
    grep_messages — keyword search over visible ``lcm_messages`` rows.
    describe_item — metadata for message, summary, or large-file id.
    fetch_message — full message body by id (char-capped).
    fetch_recent_messages — recent verbatim tail for one session.
    expand_summary — walk summary DAG edges and covered messages.
    expand_query — deterministic multi-term grep + lightweight synthesis.
    conversations_meta — conversation rows with message/summary counts.
    list_conversations — light conversation index with optional date bounds.
    search_summaries_scoped — sync scoped wrapper over :func:`search_session_summaries`.

Examples:
    >>> from sevn.lcm.query import LcmQueryScope
    >>> LcmQueryScope.__args__[0]
    'workspace'
"""

from __future__ import annotations

import re
import sqlite3  # noqa: TC003 — public API takes ``sqlite3.Connection``
import uuid
from typing import Any, Literal

from sevn.lcm.search import search_session_summaries

LcmQueryScope = Literal["workspace", "conversation", "same_telegram_topic"]

_DEFAULT_TOPIC_CAP = 32
_DEFAULT_GREP_LIMIT = 20
_DEFAULT_FETCH_LIMIT = 50
_DEFAULT_FETCH_MAX_CHARS = 12_000
_EXCERPT_CHARS = 512
_MAX_QUERY_LIMIT = 200


def _cap_query_limit(limit: int) -> int:
    """Clamp LCM query row caps to ``1.._MAX_QUERY_LIMIT``.

    Args:
        limit (int): Requested row cap.

    Returns:
        int: Clamped cap.

    Examples:
        >>> _cap_query_limit(0)
        1
        >>> _cap_query_limit(500)
        200
    """
    return max(1, min(int(limit), _MAX_QUERY_LIMIT))


def _like_pattern(query: str) -> str:
    """Escape ``query`` for SQL ``LIKE`` with leading/trailing wildcards.

    Args:
        query (str): Raw substring.

    Returns:
        str: Pattern suitable for ``LIKE ? ESCAPE '\\'``.

    Examples:
        >>> _like_pattern("a%b").startswith("%")
        True
    """
    escaped = query.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def resolve_conversation_id(conn: sqlite3.Connection, session_key: str) -> int | None:
    """Return ``lcm_conversations.id`` for ``session_key`` when present.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_key (str): Gateway session key.

    Returns:
        int | None: Conversation id or ``None`` when unknown.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> resolve_conversation_id(c, "missing") is None
        True
    """
    row = conn.execute(
        "SELECT id FROM lcm_conversations WHERE session_key = ?",
        (session_key,),
    ).fetchone()
    return int(row[0]) if row else None


def conversation_ids_for_scope(
    conn: sqlite3.Connection,
    *,
    session_key: str | None,
    scope: LcmQueryScope,
    topic_search_max_sessions: int = _DEFAULT_TOPIC_CAP,
) -> list[int] | None:
    """Resolve conversation id filter for scoped LCM queries.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_key (str | None): Active session key (required for non-workspace scopes).
        scope (LcmQueryScope): ``workspace``, ``conversation``, or ``same_telegram_topic``.
        topic_search_max_sessions (int, optional): Cap for topic fan-out. Defaults to ``32``.

    Returns:
        list[int] | None: Conversation ids to restrict queries; ``None`` means workspace-wide.

    Raises:
        ValueError: When ``scope`` requires ``session_key`` and it is missing or unknown.

    Examples:
        >>> import sqlite3
        >>> conversation_ids_for_scope(
        ...     sqlite3.connect(":memory:"), session_key=None, scope="workspace") is None
        True
    """
    if scope == "workspace":
        return None
    if not session_key:
        msg = f"session_key required when scope={scope!r}"
        raise ValueError(msg)
    cid = resolve_conversation_id(conn, session_key)
    if cid is None:
        msg = f"unknown session_key: {session_key!r}"
        raise ValueError(msg)
    if scope == "conversation":
        return [cid]
    row = conn.execute(
        """
        SELECT group_name, topic FROM lcm_conversations WHERE id = ?
        """,
        (cid,),
    ).fetchone()
    if row is None:
        msg = f"unknown session_key: {session_key!r}"
        raise ValueError(msg)
    gn = row[0] or ""
    tp = row[1] or ""
    rows = conn.execute(
        """
        SELECT id FROM lcm_conversations
        WHERE COALESCE(group_name, '') = ?
          AND COALESCE(topic, '') = ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (gn, tp, int(topic_search_max_sessions)),
    ).fetchall()
    return [int(r[0]) for r in rows]


def grep_messages(
    conn: sqlite3.Connection,
    *,
    query: str,
    scope: LcmQueryScope = "conversation",
    session_key: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = _DEFAULT_GREP_LIMIT,
    topic_search_max_sessions: int = _DEFAULT_TOPIC_CAP,
) -> list[dict[str, Any]]:
    """Keyword search over LLM-visible ``lcm_messages`` rows.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        query (str): Substring matched against ``content``.
        scope (LcmQueryScope, optional): Fan-out selector. Defaults to ``conversation``.
        session_key (str | None, optional): Session key for scoped searches.
        date_from (str | None, optional): Inclusive ``created_at`` lower bound.
        date_to (str | None, optional): Inclusive ``created_at`` upper bound.
        limit (int, optional): Row cap. Defaults to ``20``.
        topic_search_max_sessions (int, optional): Topic scope cap. Defaults to ``32``.

    Returns:
        list[dict[str, Any]]: Hits newest-first with excerpt + conversation metadata.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> grep_messages(c, query="x", session_key="k")
        Traceback (most recent call last):
        ...
        ValueError: ...
    """
    conv_filter = conversation_ids_for_scope(
        conn,
        session_key=session_key,
        scope=scope,
        topic_search_max_sessions=topic_search_max_sessions,
    )
    sql_parts = [
        """
        SELECT m.id, m.conversation_id, m.seq, m.role,
               substr(m.content, 1, ?) AS excerpt,
               m.created_at, c.session_key, c.channel,
               COALESCE(c.group_name, '') AS group_name,
               COALESCE(c.topic, '') AS topic
        FROM lcm_messages m
        JOIN lcm_conversations c ON c.id = m.conversation_id
        WHERE m.kind = 'message'
          AND m.visible_to_llm = 1
          AND m.status = 'sent'
          AND m.content LIKE ? ESCAPE '\\'
        """,
    ]
    params: list[Any] = [_EXCERPT_CHARS, _like_pattern(query)]
    if conv_filter is not None:
        placeholders = ",".join("?" for _ in conv_filter)
        sql_parts.append(f"AND m.conversation_id IN ({placeholders})")
        params.extend(conv_filter)
    if date_from:
        sql_parts.append("AND m.created_at >= ?")
        params.append(date_from)
    if date_to:
        sql_parts.append("AND m.created_at <= ?")
        params.append(date_to)
    sql_parts.append("ORDER BY m.created_at DESC LIMIT ?")
    params.append(_cap_query_limit(limit))
    cur = conn.execute("".join(sql_parts), params)
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append(
            {
                "message_id": int(row[0]),
                "conversation_id": int(row[1]),
                "seq": int(row[2]),
                "role": str(row[3]),
                "excerpt": str(row[4]),
                "created_at": str(row[5]),
                "session_key": str(row[6]),
                "channel": str(row[7]),
                "group_name": str(row[8]) or None,
                "topic": str(row[9]) or None,
            },
        )
    return out


def _detect_id_kind(item_id: str) -> Literal["message", "summary", "large_file"]:
    """Infer id type from string shape.

    Args:
        item_id (str): Operator-supplied id.

    Returns:
        Literal["message", "summary", "large_file"]: Best-effort kind.

    Examples:
        >>> _detect_id_kind("42")
        'message'
    """
    if item_id.isdigit():
        return "message"
    try:
        uuid.UUID(item_id)
        return "large_file"
    except ValueError:
        return "summary"


def describe_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    id_kind: Literal["auto", "message", "summary", "large_file"] = "auto",
) -> dict[str, Any]:
    """Return metadata for a message, summary, or large-file row.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        item_id (str): ``lcm_messages.id``, ``lcm_summaries.summary_id``, or ``file_id``.
        id_kind (Literal["auto", "message", "summary", "large_file"], optional):
            Explicit kind or ``auto`` detection. Defaults to ``auto``.

    Returns:
        dict[str, Any]: Typed payload under ``kind`` plus row fields.

    Raises:
        LookupError: When no matching row exists.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> describe_item(c, item_id="1")
        Traceback (most recent call last):
        ...
        LookupError: ...
    """
    kind = _detect_id_kind(item_id) if id_kind == "auto" else id_kind
    if kind == "message":
        row = conn.execute(
            """
            SELECT m.id, m.conversation_id, m.seq, m.role, m.content, m.token_count,
                   m.kind, m.visible_to_llm, m.status, m.created_at,
                   c.session_key, c.channel
            FROM lcm_messages m
            JOIN lcm_conversations c ON c.id = m.conversation_id
            WHERE m.id = ?
            """,
            (int(item_id),),
        ).fetchone()
        if row is None:
            msg = f"message not found: {item_id}"
            raise LookupError(msg)
        return {
            "kind": "message",
            "message_id": int(row[0]),
            "conversation_id": int(row[1]),
            "seq": int(row[2]),
            "role": str(row[3]),
            "content_excerpt": str(row[4])[:_EXCERPT_CHARS],
            "token_count": int(row[5] or 0),
            "message_kind": str(row[6]),
            "visible_to_llm": bool(row[7]),
            "status": str(row[8]),
            "created_at": str(row[9]),
            "session_key": str(row[10]),
            "channel": str(row[11]),
        }
    if kind == "large_file":
        row = conn.execute(
            """
            SELECT file_id, conversation_id, file_name, mime_type,
                   substr(content, 1, ?) AS content_excerpt,
                   exploration_summary, byte_size, created_at
            FROM lcm_large_files
            WHERE file_id = ?
            """,
            (_EXCERPT_CHARS, item_id),
        ).fetchone()
        if row is None:
            msg = f"large_file not found: {item_id}"
            raise LookupError(msg)
        return {
            "kind": "large_file",
            "file_id": str(row[0]),
            "conversation_id": int(row[1]),
            "file_name": row[2],
            "mime_type": row[3],
            "content_excerpt": str(row[4]),
            "exploration_summary": row[5],
            "byte_size": int(row[6] or 0),
            "created_at": str(row[7]),
        }
    row = conn.execute(
        """
        SELECT s.summary_id, s.conversation_id, s.content, s.depth, s.token_count,
               s.summary_kind, s.created_at, c.session_key, c.channel
        FROM lcm_summaries s
        JOIN lcm_conversations c ON c.id = s.conversation_id
        WHERE s.summary_id = ?
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        msg = f"summary not found: {item_id}"
        raise LookupError(msg)
    summary_id = str(row[0])
    parent_rows = conn.execute(
        "SELECT parent_id FROM lcm_summary_parents WHERE child_id = ?",
        (summary_id,),
    ).fetchall()
    child_rows = conn.execute(
        "SELECT child_id FROM lcm_summary_parents WHERE parent_id = ?",
        (summary_id,),
    ).fetchall()
    msg_rows = conn.execute(
        "SELECT message_id FROM lcm_summary_messages WHERE summary_id = ?",
        (summary_id,),
    ).fetchall()
    return {
        "kind": "summary",
        "summary_id": summary_id,
        "conversation_id": int(row[1]),
        "content_excerpt": str(row[2])[:_EXCERPT_CHARS],
        "depth": int(row[3]),
        "token_count": int(row[4] or 0),
        "summary_kind": str(row[5]),
        "created_at": str(row[6]),
        "session_key": str(row[7]),
        "channel": str(row[8]),
        "parent_summary_ids": [str(r[0]) for r in parent_rows],
        "child_summary_ids": [str(r[0]) for r in child_rows],
        "message_ids": [int(r[0]) for r in msg_rows],
    }


def fetch_message(
    conn: sqlite3.Connection,
    *,
    message_id: int,
    max_chars: int = _DEFAULT_FETCH_MAX_CHARS,
) -> dict[str, Any]:
    """Return one message row with full (capped) content.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        message_id (int): ``lcm_messages.id``.
        max_chars (int, optional): Truncation cap. Defaults to ``12000``.

    Returns:
        dict[str, Any]: Message payload.

    Raises:
        LookupError: When the id is missing.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> fetch_message(c, message_id=1)
        Traceback (most recent call last):
        ...
        LookupError: ...
    """
    row = conn.execute(
        """
        SELECT m.id, m.conversation_id, m.seq, m.role, m.content, m.created_at,
               c.session_key, c.channel
        FROM lcm_messages m
        JOIN lcm_conversations c ON c.id = m.conversation_id
        WHERE m.id = ?
        """,
        (message_id,),
    ).fetchone()
    if row is None:
        msg = f"message not found: {message_id}"
        raise LookupError(msg)
    body = str(row[4])
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]
    return {
        "message_id": int(row[0]),
        "conversation_id": int(row[1]),
        "seq": int(row[2]),
        "role": str(row[3]),
        "content": body,
        "truncated": truncated,
        "created_at": str(row[5]),
        "session_key": str(row[6]),
        "channel": str(row[7]),
    }


def fetch_recent_messages(
    conn: sqlite3.Connection,
    *,
    session_key: str,
    limit: int = _DEFAULT_FETCH_LIMIT,
    max_chars: int = _DEFAULT_FETCH_MAX_CHARS,
) -> list[dict[str, Any]]:
    """Return recent verbatim messages for one LCM conversation.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_key (str): Gateway session key.
        limit (int, optional): Row cap. Defaults to ``50``.
        max_chars (int, optional): Per-message truncation. Defaults to ``12000``.

    Returns:
        list[dict[str, Any]]: Messages ordered newest-first.

    Raises:
        ValueError: When ``session_key`` is unknown.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> fetch_recent_messages(c, session_key="k")
        Traceback (most recent call last):
        ...
        ValueError: ...
    """
    cid = resolve_conversation_id(conn, session_key)
    if cid is None:
        msg = f"unknown session_key: {session_key!r}"
        raise ValueError(msg)
    rows = conn.execute(
        """
        SELECT id, seq, role, content, created_at
        FROM lcm_messages
        WHERE conversation_id = ?
          AND kind = 'message'
          AND visible_to_llm = 1
          AND status = 'sent'
        ORDER BY seq DESC
        LIMIT ?
        """,
        (cid, _cap_query_limit(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        body = str(row[3])
        truncated = len(body) > max_chars
        if truncated:
            body = body[:max_chars]
        out.append(
            {
                "message_id": int(row[0]),
                "seq": int(row[1]),
                "role": str(row[2]),
                "content": body,
                "truncated": truncated,
                "created_at": str(row[4]),
                "session_key": session_key,
            },
        )
    return out


def expand_summary(
    conn: sqlite3.Connection,
    *,
    summary_id: str,
    message_char_cap: int = _DEFAULT_FETCH_MAX_CHARS,
) -> dict[str, Any]:
    """Walk summary DAG edges and return covered message bodies.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        summary_id (str): ``lcm_summaries.summary_id``.
        message_char_cap (int, optional): Per-message truncation. Defaults to ``12000``.

    Returns:
        dict[str, Any]: Summary node plus ``messages`` and ``child_summaries`` lists.

    Raises:
        LookupError: When ``summary_id`` is missing.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> expand_summary(c, summary_id="s1")
        Traceback (most recent call last):
        ...
        LookupError: ...
    """
    base = describe_item(conn, item_id=summary_id, id_kind="summary")
    messages: list[dict[str, Any]] = []
    for mid in base.get("message_ids", []):
        try:
            messages.append(fetch_message(conn, message_id=int(mid), max_chars=message_char_cap))
        except LookupError:
            continue
    child_summaries: list[dict[str, Any]] = []
    for child_id in base.get("child_summary_ids", []):
        try:
            child_summaries.append(
                describe_item(conn, item_id=str(child_id), id_kind="summary"),
            )
        except LookupError:
            continue
    return {
        "summary": base,
        "messages": messages,
        "child_summaries": child_summaries,
    }


def _query_terms(query: str) -> list[str]:
    """Split a free-text query into deduplicated search terms.

    Args:
        query (str): User query string.

    Returns:
        list[str]: Lowercased terms length ≥ 2.

    Examples:
        >>> _query_terms("Deploy  API  fix")
        ['deploy', 'api', 'fix']
    """
    raw = re.split(r"[^\w\-]+", query.strip().lower())
    seen: set[str] = set()
    terms: list[str] = []
    for token in raw:
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms or ([query.strip().lower()] if query.strip() else [])


def expand_query(
    conn: sqlite3.Connection,
    *,
    query: str,
    scope: LcmQueryScope = "conversation",
    session_key: str | None = None,
    limit: int = _DEFAULT_GREP_LIMIT,
    topic_search_max_sessions: int = _DEFAULT_TOPIC_CAP,
) -> dict[str, Any]:
    """Expand ``query`` into terms and merge grep hits with a short synthesis.

    Deterministic v1 expansion (no LLM). Each term runs :func:`grep_messages`; hits
    dedupe by ``message_id``.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        query (str): Original operator query.
        scope (LcmQueryScope, optional): Fan-out selector. Defaults to ``conversation``.
        session_key (str | None, optional): Session key for scoped searches.
        limit (int, optional): Per-term grep cap. Defaults to ``20``.
        topic_search_max_sessions (int, optional): Topic scope cap. Defaults to ``32``.

    Returns:
        dict[str, Any]: ``expanded_terms``, ``hits``, and ``synthesis`` text.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> expand_query(c, query="x", session_key="k")
        Traceback (most recent call last):
        ...
        ValueError: ...
    """
    terms = _query_terms(query)
    merged: dict[int, dict[str, Any]] = {}
    for term in terms:
        for hit in grep_messages(
            conn,
            query=term,
            scope=scope,
            session_key=session_key,
            limit=limit,
            topic_search_max_sessions=topic_search_max_sessions,
        ):
            merged[int(hit["message_id"])] = hit
    hits = sorted(merged.values(), key=lambda h: str(h.get("created_at", "")), reverse=True)
    capped = _cap_query_limit(limit)
    snippets = [str(h.get("excerpt", "")).strip() for h in hits[:3] if h.get("excerpt")]
    synthesis = " | ".join(s for s in snippets if s)
    if not synthesis:
        synthesis = f"No LCM message hits for query {query!r}."
    return {
        "query": query,
        "expanded_terms": terms,
        "hits": hits[:capped],
        "synthesis": synthesis,
    }


def conversations_meta(
    conn: sqlite3.Connection,
    *,
    conversation_ids: list[int],
) -> list[dict[str, Any]]:
    """Return conversation metadata and aggregate counts.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        conversation_ids (list[int]): ``lcm_conversations.id`` values.

    Returns:
        list[dict[str, Any]]: Rows in input order (missing ids omitted).

    Examples:
        >>> import sqlite3
        >>> conversations_meta(sqlite3.connect(":memory:"), conversation_ids=[])
        []
    """
    if not conversation_ids:
        return []
    out: list[dict[str, Any]] = []
    for cid in conversation_ids:
        row = conn.execute(
            """
            SELECT id, session_key, channel, group_name, topic,
                   created_at, updated_at
            FROM lcm_conversations
            WHERE id = ?
            """,
            (int(cid),),
        ).fetchone()
        if row is None:
            continue
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM lcm_messages WHERE conversation_id = ?",
            (int(cid),),
        ).fetchone()
        sum_count = conn.execute(
            "SELECT COUNT(*) FROM lcm_summaries WHERE conversation_id = ?",
            (int(cid),),
        ).fetchone()
        out.append(
            {
                "conversation_id": int(row[0]),
                "session_key": str(row[1]),
                "channel": str(row[2]),
                "group_name": row[3],
                "topic": row[4],
                "created_at": str(row[5]),
                "updated_at": str(row[6]),
                "message_count": int(msg_count[0]) if msg_count else 0,
                "summary_count": int(sum_count[0]) if sum_count else 0,
            },
        )
    return out


def list_conversations(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List LCM conversations (light index).

    Args:
        conn (sqlite3.Connection): Workspace DB.
        date_from (str | None, optional): Inclusive ``updated_at`` lower bound.
        date_to (str | None, optional): Inclusive ``updated_at`` upper bound.
        limit (int, optional): Row cap. Defaults to ``50``.

    Returns:
        list[dict[str, Any]]: Conversations newest-first.

    Examples:
        >>> import sqlite3
        >>> list_conversations(sqlite3.connect(":memory:"))
        Traceback (most recent call last):
        ...
        sqlite3.OperationalError: ...
    """
    sql_parts = [
        """
        SELECT id, session_key, channel, group_name, topic, updated_at
        FROM lcm_conversations
        WHERE 1=1
        """,
    ]
    params: list[Any] = []
    if date_from:
        sql_parts.append("AND updated_at >= ?")
        params.append(date_from)
    if date_to:
        sql_parts.append("AND updated_at <= ?")
        params.append(date_to)
    sql_parts.append("ORDER BY updated_at DESC LIMIT ?")
    params.append(_cap_query_limit(limit))
    cur = conn.execute("".join(sql_parts), params)
    return [
        {
            "conversation_id": int(row[0]),
            "session_key": str(row[1]),
            "channel": str(row[2]),
            "group_name": row[3],
            "topic": row[4],
            "updated_at": str(row[5]),
        }
        for row in cur.fetchall()
    ]


def search_summaries_scoped(
    conn: sqlite3.Connection,
    *,
    query: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
    scope: LcmQueryScope = "workspace",
    session_key: str | None = None,
    topic_search_max_sessions: int = _DEFAULT_TOPIC_CAP,
) -> list[dict[str, Any]]:
    """Scoped keyword search over ``session_end`` summaries.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        query (str): Keyword substring.
        date_from (str | None): Inclusive ``created_at`` lower bound.
        date_to (str | None): Inclusive ``created_at`` upper bound.
        limit (int): Row cap.
        scope (LcmQueryScope, optional): Fan-out selector. Defaults to ``workspace``.
        session_key (str | None, optional): Session key for scoped searches.
        topic_search_max_sessions (int, optional): Topic scope cap. Defaults to ``32``.

    Returns:
        list[dict[str, Any]]: Hits with 512-char excerpt.

    Examples:
        >>> import sqlite3
        >>> search_summaries_scoped(
        ...     sqlite3.connect(":memory:"), query="x",
        ...     date_from=None, date_to=None, limit=1)
        Traceback (most recent call last):
        ...
        sqlite3.OperationalError: ...
    """
    conv_filter = conversation_ids_for_scope(
        conn,
        session_key=session_key,
        scope=scope,
        topic_search_max_sessions=topic_search_max_sessions,
    )
    rows = search_session_summaries(
        conn,
        query=query,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        conversation_ids_filter=conv_filter,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        content = str(row["content"])
        out.append(
            {
                "summary_id": str(row["summary_id"]),
                "conversation_id": int(row["conversation_id"]),
                "excerpt": content[:_EXCERPT_CHARS],
                "created_at": str(row["created_at"]),
                "session_key": str(row["session_key"]),
                "channel": str(row["channel"]),
            },
        )
    return out
