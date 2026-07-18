"""Always-available session history tools for the current gateway session.

The harness already injects up to ``triager.history_turns_n`` recent turns into the
tier-B system prompt. When the executor needs more (e.g. "what did you ask me
ten minutes ago?", "what file path did I mention earlier?"), it can call
``history`` (gateway SQLite) or ``read_transcript`` (``workspace/sessions/…`` JSONL)
without re-walking the registry.

Module: sevn.tools.transcript
Depends: sevn.tools.base, sevn.tools.context, sevn.tools.decorator,
    sevn.gateway.session.sessions_query, sevn.storage

Exports:
    history_tool — ``@sevn_tool`` gateway session history (inline bounded rows).
    read_transcript_tool — ``@sevn_tool`` JSONL transcript reader for the active session.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sevn.agent.provider_history_keys import (
    PROVIDER_TURN_MESSAGES_KEY,
    SUCCESSFUL_TOOLS_KEY,
)
from sevn.gateway.session.sessions_query import (
    MAX_HISTORY_LIMIT,
    cap_history_limit,
    fetch_session_history,
    list_sessions_active_between,
    search_messages,
    session_operator_timezone,
)
from sevn.gateway.util.timestamps import resolve_time_range
from sevn.storage import open_sevn_sqlite
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool

_INDEX_NAME: Final[str] = "_index.json"
_DEFAULT_LIMIT: Final[int] = 20
_MAX_LIMIT: Final[int] = MAX_HISTORY_LIMIT
_PREVIEW_CONTENT_CHARS: Final[int] = 500
_MAX_SOURCES: Final[int] = 10
_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://[^\s\"'<>]+")


def _tool_result_succeeded(content: object) -> bool:
    """Return whether a mirrored ``tool_result`` block indicates ``ok=true``.

    Args:
        content (object): Raw ``tool_result.content`` (usually JSON text).

    Returns:
        bool: ``True`` only when parsed envelope has ``ok`` truthy.

    Examples:
        >>> _tool_result_succeeded('{"ok": true}')
        True
        >>> _tool_result_succeeded('{"ok": false, "error": "denied"}')
        False
        >>> _tool_result_succeeded("42")
        False
        >>> _tool_result_succeeded("null")
        False
    """
    if isinstance(content, str):
        try:
            blob = json.loads(content)
        except json.JSONDecodeError:
            return False
    elif isinstance(content, dict):
        blob = content
    else:
        return False
    # Tool mirrors sometimes store bare JSON scalars/arrays (``"42"``, ``"null"``,
    # ``[{...}]``). Those are not envelopes — never call ``.get`` on a non-dict.
    if not isinstance(blob, dict):
        return False
    return bool(blob.get("ok"))


def _extract_turn_provenance(extras: object) -> dict[str, object]:
    """Pull attempted/successful tools and source URLs from transcript extras.

    ``successful_tools`` prefers the gateway-persisted ``extras.successful_tools``
    list (authoritative ``ok=true`` set). When absent, derives success by pairing
    each ``tool_use`` id with its ``tool_result`` and checking ``ok`` in the envelope.

    Args:
        extras (object): JSONL ``extras`` dict or parsed ``extras_json``.

    Returns:
        dict[str, object]: Optional ``tools_attempted``, ``successful_tools``, and
            ``sources`` lists.

    Examples:
        >>> prov = _extract_turn_provenance({
        ...     "provider_turn_messages": [
        ...         {"role": "assistant", "content": [
        ...             {"type": "tool_use", "name": "web_search", "id": "t0"},
        ...             {"type": "tool_use", "name": "serp", "id": "t1"},
        ...         ]},
        ...         {"role": "user", "content": [
        ...             {"type": "tool_result", "tool_use_id": "t0",
        ...              "content": '{"ok": false}'},
        ...             {"type": "tool_result", "tool_use_id": "t1",
        ...              "content": '{"ok": true}'},
        ...         ]},
        ...     ],
        ... })
        >>> prov["tools_attempted"]
        ['web_search', 'serp']
        >>> prov["successful_tools"]
        ['serp']
    """
    if not isinstance(extras, dict):
        return {}
    raw = extras.get(PROVIDER_TURN_MESSAGES_KEY)
    if not isinstance(raw, list):
        stored = extras.get(SUCCESSFUL_TOOLS_KEY)
        if isinstance(stored, list):
            names = [str(item).strip() for item in stored if str(item).strip()]
            return {"successful_tools": names} if names else {}
        return {}
    tools_attempted: list[str] = []
    derived_successful: list[str] = []
    sources: list[str] = []
    seen_attempted: set[str] = set()
    seen_successful: set[str] = set()
    seen_urls: set[str] = set()
    tool_id_to_name: dict[str, str] = {}

    def _scan_tool_result_text(text: str) -> None:
        for match in _URL_PATTERN.findall(text):
            if match in seen_urls:
                continue
            seen_urls.add(match)
            sources.append(match)
            if len(sources) >= _MAX_SOURCES:
                return

    for msg in raw:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        role = str(msg.get("role", ""))
        if role == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                name = str(block.get("name", "")).strip()
                tool_id = str(block.get("id", "")).strip()
                if tool_id and name:
                    tool_id_to_name[tool_id] = name
                if name and name not in seen_attempted:
                    seen_attempted.add(name)
                    tools_attempted.append(name)
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                body = block.get("content")
                if isinstance(body, str):
                    _scan_tool_result_text(body)
                elif body is not None:
                    _scan_tool_result_text(json.dumps(body, default=str))
                tool_use_id = str(block.get("tool_use_id", "")).strip()
                tool_name = tool_id_to_name.get(tool_use_id, "")
                if tool_name and _tool_result_succeeded(body) and tool_name not in seen_successful:
                    seen_successful.add(tool_name)
                    derived_successful.append(tool_name)
                if len(sources) >= _MAX_SOURCES:
                    break
    out: dict[str, object] = {}
    if tools_attempted:
        out["tools_attempted"] = tools_attempted
    stored = extras.get(SUCCESSFUL_TOOLS_KEY)
    if isinstance(stored, list):
        stored_names = [str(item).strip() for item in stored if str(item).strip()]
        if stored_names:
            out["successful_tools"] = stored_names
    elif derived_successful:
        out["successful_tools"] = derived_successful
    if sources:
        out["sources"] = sources
    return out


def _sqlite_extras_for_message(
    conn: sqlite3.Connection,
    session_id: str,
    message_id: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Load ``extras_json`` and ``turn_id`` for one gateway message row.

    Args:
        conn (sqlite3.Connection): Workspace DB handle.
        session_id (str): Owning session id.
        message_id (int): ``gateway_messages.id``.

    Returns:
        tuple[dict[str, Any] | None, str | None]: Parsed extras and turn id.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _sqlite_extras_for_message(c, "missing", 1)
        (None, None)
    """
    row = conn.execute(
        """
        SELECT extras_json, turn_id FROM gateway_messages
        WHERE session_id = ? AND id = ?
        """,
        (session_id, message_id),
    ).fetchone()
    if row is None:
        return None, None
    extras_json, turn_id = row
    parsed: dict[str, Any] | None = None
    if extras_json:
        try:
            raw = json.loads(str(extras_json))
            if isinstance(raw, dict):
                parsed = raw
        except json.JSONDecodeError:
            parsed = None
    tid = str(turn_id) if turn_id and str(turn_id) != "-" else None
    return parsed, tid


def _compact_content(content: str, *, full: bool) -> tuple[str, bool]:
    """Return a preview slice and whether the body was truncated.

    Args:
        content (str): Raw message body.
        full (bool): When ``True``, return the body unchanged.

    Returns:
        tuple[str, bool]: ``(body, truncated)``.

    Examples:
        >>> body, truncated = _compact_content("x" * 600, full=False)
        >>> len(body) == 500 and truncated
        True
    """
    if full or len(content) <= _PREVIEW_CONTENT_CHARS:
        return content, False
    return content[:_PREVIEW_CONTENT_CHARS], True


def _normalize_history_row(row: dict[str, object]) -> dict[str, object]:
    """Ensure gateway history rows expose ``ts`` for tool consumers.

    Args:
        row (dict[str, object]): Row from :func:`fetch_session_history` or
            :func:`search_messages`.

    Returns:
        dict[str, object]: Row with ``ts`` populated from ``created_at`` when absent.

    Examples:
        >>> _normalize_history_row({"id": 1, "created_at": "t", "role": "user"})["ts"]
        't'
    """
    if "ts" not in row and "created_at" in row:
        return {**row, "ts": row["created_at"]}
    return row


def _compact_turn_row(record: dict[str, object], *, full: bool) -> dict[str, object]:
    """Project one JSONL transcript row with optional content preview.

    Args:
        record (dict[str, object]): Source row with ``content`` and metadata.
        full (bool): When ``True``, omit per-row truncation.

    Returns:
        dict[str, object]: Compact row with ``id``, ``role``, ``ts``, ``content``,
            and optional ``turn_id``, ``tools_attempted``, ``successful_tools``,
            ``sources``.

    Examples:
        >>> row = _compact_turn_row(
        ...     {"id": 1, "role": "user", "ts": "t", "content": "hi"},
        ...     full=True,
        ... )
        >>> row["content"]
        'hi'
    """
    content = str(record.get("content", ""))
    body, truncated = _compact_content(content, full=full)
    row: dict[str, object] = {
        "id": record.get("id"),
        "role": record.get("role"),
        "ts": record.get("ts") or record.get("created_at"),
        "content": body,
    }
    turn_id = record.get("turn_id")
    if isinstance(turn_id, str) and turn_id and turn_id != "-":
        row["turn_id"] = turn_id
    provenance = _extract_turn_provenance(record.get("extras"))
    for key in ("tools_attempted", "successful_tools", "sources"):
        if key in provenance:
            row[key] = provenance[key]
    if truncated:
        row["truncated"] = True
    return row


def _open_workspace_db(workspace: Path) -> sqlite3.Connection:
    """Open migrated workspace ``sevn.db``.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        sqlite3.Connection: Migrated connection (caller must close).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / ".sevn").mkdir(parents=True)
        >>> conn = _open_workspace_db(ws)
        >>> isinstance(conn, sqlite3.Connection)
        True
        >>> conn.close()
    """
    return open_sevn_sqlite(workspace / ".sevn")


def _operator_tz(conn: sqlite3.Connection, session_id: str | None) -> str:
    """Best-effort operator IANA timezone for relative-date resolution.

    Reads the current session's user profile timezone; falls back to ``UTC`` so
    a missing profile or channel never breaks a date query.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_id (str | None): Active session id.

    Returns:
        str: IANA timezone name (``UTC`` when unresolved).

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _operator_tz(c, None)
        'UTC'
    """
    return session_operator_timezone(conn, session_id)


def _ts_in_range(ts_raw: object, start_iso: str | None, end_iso: str | None) -> bool:
    """Return whether a transcript ``ts`` falls in ``[start, end)`` (UTC).

    Bounds are naive-UTC ISO strings (from ``resolve_time_range``); ``ts`` is a
    local-offset ISO string (e.g. ``…+02:00``) which is normalised to UTC before
    comparison. When both bounds are ``None`` every row passes; a row with an
    unparseable/absent ``ts`` is dropped only while a bound is active.

    Args:
        ts_raw (object): Candidate ``ts`` value from the transcript record.
        start_iso (str | None): Inclusive lower bound, naive-UTC ISO.
        end_iso (str | None): Exclusive upper bound, naive-UTC ISO.

    Returns:
        bool: ``True`` when the timestamp is within the window.

    Examples:
        >>> _ts_in_range("2026-07-02T12:00:00+00:00", "2026-07-02T00:00:00", "2026-07-03T00:00:00")
        True
        >>> _ts_in_range("2026-07-03T01:00:00+02:00", "2026-07-03T00:00:00", "2026-07-04T00:00:00")
        False
        >>> _ts_in_range("anything", None, None)
        True
    """
    if start_iso is None and end_iso is None:
        return True
    if not isinstance(ts_raw, str):
        return False
    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        return False
    ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    if start_iso is not None and ts_utc < datetime.fromisoformat(start_iso).replace(tzinfo=UTC):
        return False
    return not (
        end_iso is not None and ts_utc >= datetime.fromisoformat(end_iso).replace(tzinfo=UTC)
    )


def _resolve_jsonl_for_session(workspace: Path, session_id: str) -> Path | None:
    """Look up the JSONL path for ``session_id`` in ``sessions/_index.json``.

    Args:
        workspace (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        Path | None: Absolute JSONL path, or ``None`` when the index has no entry.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     _resolve_jsonl_for_session(Path(tmp), "missing") is None
        True
    """
    index_path = workspace / "sessions" / _INDEX_NAME
    if not index_path.is_file():
        return None
    try:
        raw = index_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    sessions = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(sessions, dict):
        return None
    entry = sessions.get(session_id)
    if not isinstance(entry, dict):
        return None
    jsonl_rel = entry.get("jsonl")
    if not isinstance(jsonl_rel, str) or not jsonl_rel:
        return None
    candidate = (workspace / "sessions" / jsonl_rel).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


@sevn_tool(
    name="history",
    category="file_ops",
    description=(
        "Recall past conversations/sessions: search prior message history "
        "(what was asked or said before, earlier/previous sessions) as inline rows. "
        "Prefer this over ``read`` on session files. "
        "Pass ``query`` to search across visible sessions; ``session_id`` for one session. "
        'To find history by date, pass ``when`` (e.g. "yesterday", "today", '
        '"last_7_days", "this_week") or explicit ``since``/``until`` dates — relative '
        "terms are resolved server-side, so you do NOT need to compute the date yourself. "
        "``when``/``since``/``until`` combine with ``query`` and work with no query at all "
        "(e.g. what did we talk about yesterday)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": (
                    "Target session id; defaults to the current session. "
                    "Required when ``query`` is omitted."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Case-insensitive substring search across visible sessions. "
                    "When set without ``session_id``, returns cross-session hits."
                ),
            },
            "when": {
                "type": "string",
                "description": (
                    "Relative date range resolved server-side: one of today, yesterday, "
                    "last_7_days, last_30_days, this_week, last_week, this_month, last_month. "
                    "Do not combine with ``since``/``until``."
                ),
            },
            "since": {
                "type": "string",
                "description": "Lower bound (inclusive), YYYY-MM-DD or ISO-8601.",
            },
            "until": {
                "type": "string",
                "description": "Upper bound (a bare YYYY-MM-DD includes that whole day).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LIMIT,
                "description": f"Max rows to return (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT}).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Skip first N matching rows after ordering (session mode only).",
            },
            "full": {
                "type": "boolean",
                "description": (
                    "When true, return untruncated message bodies up to ``limit``. "
                    "Default false previews ~500 chars per row."
                ),
            },
        },
        "required": [],
    },
)
async def history_tool(
    ctx: ToolContext,
    session_id: str | None = None,
    query: str | None = None,
    when: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    full: bool = False,
) -> str:
    """Return bounded gateway session history rows inline (never spilled).

    Args:
        ctx (ToolContext): Invocation context.
        session_id (str | None): Target session; defaults to ``ctx.session_id``.
        query (str | None): Optional substring filter or cross-session search.
        when (str | None): Relative date range (``"yesterday"``, ``"last_7_days"``…)
            resolved server-side against the operator timezone.
        since (str | None): Explicit lower bound (``YYYY-MM-DD`` or ISO).
        until (str | None): Explicit upper bound (bare date includes the whole day).
        limit (int): Row cap (default 20).
        offset (int): Pagination offset for single-session fetches.
        full (bool): When ``True``, do not truncate per-row ``content``.

    Returns:
        str: §3.1 JSON envelope with ``messages``, ``hits``, or ``sessions`` rows.

    Examples:
        >>> history_tool.__name__
        'history_tool'
    """
    if limit < 1 or limit > _MAX_LIMIT:
        return enveloped_failure(
            f"limit must be 1..{_MAX_LIMIT}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if offset < 0:
        return enveloped_failure(
            "offset must be >= 0",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    q = (query or "").strip() or None
    explicit_session = (session_id or "").strip() or None
    has_dates = bool((when or "").strip() or (since or "").strip() or (until or "").strip())
    capped = cap_history_limit(limit)
    conn = _open_workspace_db(ctx.workspace_path)
    try:
        try:
            start, end = resolve_time_range(
                when=when,
                since=since,
                until=until,
                tz=_operator_tz(conn, ctx.session_id),
            )
        except ValueError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)

        # Date-only, cross-session, no keyword → sessions active in that window.
        # Keyed on message ``created_at`` (not session ``updated_at``, which the
        # gateway bulk-refreshes at boot and cannot indicate real activity).
        if has_dates and not q and not explicit_session:
            sessions = list_sessions_active_between(
                conn,
                since=start,
                until=end,
                caller_session_id=ctx.session_id,
                limit=capped,
            )
            return enveloped_success(
                {"sessions": sessions, "count": len(sessions), "since": start, "until": end}
            )

        # Single-session mode: explicit session, or a bare recall of the current one.
        target_session = explicit_session or (ctx.session_id if not q and not has_dates else None)
        if target_session:
            data = fetch_session_history(
                conn,
                target_session,
                caller_session_id=ctx.session_id,
                query=q,
                since=start,
                until=end,
                limit=capped,
                offset=offset,
                full=full,
            )
            rows = data.get("messages")
            if isinstance(rows, list):
                data["messages"] = [
                    _normalize_history_row(row) if isinstance(row, dict) else row for row in rows
                ]
            return enveloped_success(data)

        hits = search_messages(
            conn,
            q or "",
            caller_session_id=ctx.session_id,
            since=start,
            until=end,
            limit=capped,
            full=full,
        )
        normalized = [_normalize_history_row(hit) if isinstance(hit, dict) else hit for hit in hits]
        return enveloped_success(
            {
                "hits": normalized,
                "count": len(normalized),
                "query": q,
                "since": start,
                "until": end,
            }
        )
    except ValueError as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
    finally:
        conn.close()


@sevn_tool(
    name="read_transcript",
    category="file_ops",
    description=(
        "Recall earlier turns of the current conversation: read this session's "
        "transcript JSONL when you need more history than the system prompt provides. "
        "Pass ``search`` to find turns whose content contains a specific word or phrase. "
        'Filter by time with ``when`` (e.g. "yesterday", "today", "last_7_days") or '
        "explicit ``since``/``until`` dates — relative terms are resolved server-side. "
        "Assistant rows include ``tools_attempted``, ``successful_tools``, and "
        "``sources`` when provenance was persisted; use ``turn_id`` with "
        "``log_query`` for log confirmation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LIMIT,
                "description": f"Number of most recent turns to return (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT}).",
            },
            "before_id": {
                "type": "integer",
                "minimum": 0,
                "description": "Cursor: return turns with id strictly less than this (for pagination).",
            },
            "when": {
                "type": "string",
                "description": (
                    "Relative date range resolved server-side: today, yesterday, "
                    "last_7_days, last_30_days, this_week, last_week, this_month, last_month. "
                    "Do not combine with ``since``/``until``."
                ),
            },
            "since": {
                "type": "string",
                "description": "Lower bound (inclusive), YYYY-MM-DD or ISO-8601.",
            },
            "until": {
                "type": "string",
                "description": "Upper bound (a bare YYYY-MM-DD includes that whole day).",
            },
            "role": {
                "type": "string",
                "enum": ["user", "assistant", "any"],
                "description": "Filter by role; default 'any'.",
            },
            "search": {
                "type": "string",
                "description": (
                    "Case-insensitive substring to match against turn content. "
                    "When set, only turns whose content contains this string are returned. "
                    "Still capped by ``limit`` and filtered by ``role``."
                ),
            },
            "full": {
                "type": "boolean",
                "description": (
                    "When true, return untruncated turn bodies up to ``limit``. "
                    "Default false previews ~500 chars per row."
                ),
            },
        },
        "required": [],
    },
)
async def read_transcript_tool(
    ctx: ToolContext,
    limit: int = _DEFAULT_LIMIT,
    before_id: int | None = None,
    role: str = "any",
    search: str | None = None,
    when: str | None = None,
    since: str | None = None,
    until: str | None = None,
    full: bool = False,
) -> str:
    """Return recent transcript rows for the current session.

    Args:
        ctx (ToolContext): Invocation context.
        limit (int): Number of most recent turns to return.
        before_id (int | None): Cursor for pagination.
        role (str): ``"user"``, ``"assistant"``, or ``"any"``.
        search (str | None): Optional case-insensitive substring filter applied
            to turn content. ``None`` (default) returns all turns matching the
            other filters — preserving backward compatibility.
        when (str | None): Relative date range (``"yesterday"``…) resolved
            server-side against the operator timezone.
        since (str | None): Explicit lower bound (``YYYY-MM-DD`` or ISO).
        until (str | None): Explicit upper bound (bare date includes the whole day).
        full (bool): When ``True``, do not truncate per-row ``content``.

    Returns:
        str: §3.1 JSON envelope with ``turns`` list and ``next_before_id`` cursor.

    Examples:
        >>> read_transcript_tool.__name__
        'read_transcript_tool'
    """
    if limit < 1 or limit > _MAX_LIMIT:
        return enveloped_failure(
            f"limit must be 1..{_MAX_LIMIT}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if role not in ("user", "assistant", "any"):
        return enveloped_failure(
            "role must be one of: user, assistant, any",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    search_pattern: re.Pattern[str] | None = None
    if search is not None:
        if not search:
            return enveloped_failure(
                "search must be a non-empty string",
                code=ToolResultCode.VALIDATION_ERROR,
            )
        search_pattern = re.compile(re.escape(search), re.IGNORECASE)
    workspace = ctx.workspace_path
    jsonl_path = _resolve_jsonl_for_session(workspace, ctx.session_id)
    if jsonl_path is None:
        return enveloped_success(
            {
                "session_id": ctx.session_id,
                "turns": [],
                "next_before_id": None,
                "note": "no transcript JSONL found for this session",
            },
        )
    try:
        text = jsonl_path.read_text(encoding="utf-8")
    except OSError as exc:
        return enveloped_failure(
            f"transcript read failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    conn = _open_workspace_db(workspace)
    rows: list[dict[str, object]] = []
    try:
        try:
            start, end = resolve_time_range(
                when=when,
                since=since,
                until=until,
                tz=_operator_tz(conn, ctx.session_id),
            )
        except ValueError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.VALIDATION_ERROR)
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("kind") != "message":
                continue
            if not _ts_in_range(record.get("ts"), start, end):
                continue
            if before_id is not None:
                rid = record.get("id")
                if isinstance(rid, int) and rid >= before_id:
                    continue
            if role != "any" and record.get("role") != role:
                continue
            content = str(record.get("content", ""))
            if search_pattern is not None and not search_pattern.search(content):
                continue
            extras = record.get("extras")
            turn_id = record.get("turn_id")
            message_id = record.get("id")
            if (not isinstance(extras, dict) or not extras) and isinstance(message_id, int):
                sqlite_extras, sqlite_turn = _sqlite_extras_for_message(
                    conn,
                    ctx.session_id,
                    message_id,
                )
                if sqlite_extras:
                    extras = sqlite_extras
                if not turn_id and sqlite_turn:
                    turn_id = sqlite_turn
            rows.append(
                _compact_turn_row(
                    {
                        "id": message_id,
                        "ts": record.get("ts"),
                        "role": record.get("role"),
                        "content": content,
                        "turn_id": turn_id,
                        "extras": extras,
                    },
                    full=full,
                ),
            )
    finally:
        conn.close()
    selected = rows[-limit:]
    next_cursor: int | None = None
    if selected:
        first_id = selected[0].get("id")
        if isinstance(first_id, int) and first_id > 0 and len(rows) > limit:
            # If we trimmed older rows, expose a cursor for the next page.
            next_cursor = first_id
    result: dict[str, object] = {
        "session_id": ctx.session_id,
        "turns": selected,
        "next_before_id": next_cursor,
        "total_returned": len(selected),
    }
    if search is not None:
        result["search"] = search
    if start is not None or end is not None:
        result["since"] = start
        result["until"] = end
    return enveloped_success(result)


__all__ = ["history_tool", "read_transcript_tool"]
