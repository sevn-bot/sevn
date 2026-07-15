"""Append-only workspace session mirror (`specs/17-gateway.md` §3.x).

Module: sevn.gateway.session.session_mirror
Depends: json, pathlib, sqlite3, sevn.config.workspace_config

Exports:
    session_mirror_enabled — read ``gateway.session_mirror.enabled``.
    mirror_gateway_message — append one JSONL line under ``sessions/``.
    mark_session_superseded — link archived session id to successor in ``_index.json``.
    format_named_path_segment — build ``{slug}--{id}`` or ID-only mirror segment.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.config.workspace_config import GatewaySessionMirrorConfig, WorkspaceConfig
from sevn.gateway.session.path_names import SessionPathNameLookup, SessionPathNameResolver

_INDEX_NAME = "_index.json"
_jsonl_lock_guard = threading.Lock()
_jsonl_locks: dict[str, threading.Lock] = {}


def _lock_for_jsonl_path(jsonl_path: Path) -> threading.Lock:
    """Return a process-wide lock for one JSONL file path.

    Args:
        jsonl_path (Path): Target append-only session log.

    Returns:
        threading.Lock: Exclusive lock for ``jsonl_path``.

    Examples:
        >>> from pathlib import Path
        >>> _lock_for_jsonl_path(Path("/tmp/s.jsonl")) is _lock_for_jsonl_path(Path("/tmp/s.jsonl"))
        True
    """
    key = str(jsonl_path.resolve())
    with _jsonl_lock_guard:
        lock = _jsonl_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _jsonl_locks[key] = lock
        return lock


def _append_jsonl_line(jsonl_path: Path, record: dict[str, Any]) -> None:
    """Validate and append one JSONL record with flush + fsync.

    Args:
        jsonl_path (Path): Destination JSONL file.
        record (dict[str, Any]): Serializable mirror row.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "s.jsonl"
        >>> _append_jsonl_line(p, {"id": 1, "content": "hi"})
        >>> json.loads(p.read_text(encoding="utf-8").strip())["content"]
        'hi'
    """
    line = json.dumps(record, ensure_ascii=False) + "\n"
    json.loads(line)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for_jsonl_path(jsonl_path), jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def _mirror_cfg(workspace: WorkspaceConfig) -> GatewaySessionMirrorConfig:
    """Resolve ``gateway.session_mirror`` with defaults.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        GatewaySessionMirrorConfig: Mirror subtree or default instance.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _mirror_cfg(WorkspaceConfig.minimal()).enabled
        True
    """
    gw = workspace.gateway
    if gw is not None and gw.session_mirror is not None:
        return gw.session_mirror
    return GatewaySessionMirrorConfig()


def session_mirror_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether workspace JSONL mirroring is on.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        bool: True when mirroring is enabled (default).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> session_mirror_enabled(WorkspaceConfig.minimal())
        True
    """
    return _mirror_cfg(workspace).enabled


def format_named_path_segment(name: str | None, entity_id: str) -> str:
    """Build a mirror path segment with optional ``{slug}--{id}`` suffix (D1/D2).

    Args:
        name (str | None): Human-readable title; ``None`` or blank → ID-only segment.
        entity_id (str): Stable Telegram id string used for uniqueness.

    Returns:
        str: Filesystem-safe path segment.

    Examples:
        >>> format_named_path_segment("My Group", "-1001234567890")
        'My_Group--1001234567890'
        >>> format_named_path_segment(None, "7")
        '7'
    """
    if name is None or not name.strip():
        return entity_id
    suffix_id = entity_id[1:] if entity_id.startswith("-") else entity_id
    return f"{_safe_segment(name)}--{suffix_id}"


def _safe_segment(value: str) -> str:
    """Sanitize a path segment for mirror directories and filenames.

    Args:
        value (str): Raw scope or id fragment.

    Returns:
        str: Filesystem-safe segment (never empty).

    Examples:
        >>> _safe_segment("telegram:123:topic:42")
        'telegram_123_topic_42'
    """
    cleaned = re.sub(r"[^\w.\-]+", "_", value.strip())
    return cleaned or "unknown"


def _should_enrich_telegram_names(chat_id: str) -> bool:
    """Return whether D7 allows slug lookup for this Telegram chat id.

    Args:
        chat_id (str): Parsed chat id from a scope key.

    Returns:
        bool: True for group/supergroup ids (negative integers).

    Examples:
        >>> _should_enrich_telegram_names("-1001234567890")
        True
        >>> _should_enrich_telegram_names("99")
        False
    """
    try:
        return int(chat_id) < 0
    except ValueError:
        return False


def _chat_path_segment(chat_id: str, resolver: SessionPathNameLookup | None) -> str:
    """Build the ``telegram/chats/{segment}`` folder name for one chat id.

    Args:
        chat_id (str): Parsed chat id from a scope key.
        resolver (SessionPathNameLookup | None): Optional title lookup.

    Returns:
        str: Filesystem-safe chat folder segment.

    Examples:
        >>> _chat_path_segment("99", None)
        '99'
    """
    if resolver is not None and _should_enrich_telegram_names(chat_id):
        return format_named_path_segment(resolver.get_chat_name(chat_id), chat_id)
    return _safe_segment(chat_id)


def _topic_path_segment(
    chat_id: str,
    topic_id: str,
    resolver: SessionPathNameLookup | None,
) -> str:
    """Build the ``topics/{segment}`` folder name for one forum topic id.

    Args:
        chat_id (str): Parsed chat id from a scope key.
        topic_id (str): Parsed topic id from a scope key.
        resolver (SessionPathNameLookup | None): Optional title lookup.

    Returns:
        str: Filesystem-safe topic folder segment.

    Examples:
        >>> _topic_path_segment("-100", "7", None)
        '7'
    """
    if resolver is not None and _should_enrich_telegram_names(chat_id):
        return format_named_path_segment(resolver.get_topic_name(chat_id, topic_id), topic_id)
    return _safe_segment(topic_id)


def _coerce_name_lookup(
    value: SessionPathNameLookup | sqlite3.Connection | None,
) -> SessionPathNameLookup | None:
    """Normalize resolver arguments, wrapping bare SQLite connections.

    Args:
        value (SessionPathNameLookup | sqlite3.Connection | None): Lookup source.

    Returns:
        SessionPathNameLookup | None: Coerced resolver, or ``None``.

    Examples:
        >>> _coerce_name_lookup(None) is None
        True
    """
    if value is None:
        return None
    if isinstance(value, sqlite3.Connection):
        return SessionPathNameResolver(value)
    return value


def _resolve_name_lookup(
    *,
    name_resolver: SessionPathNameLookup | sqlite3.Connection | None = None,
    resolver: SessionPathNameLookup | sqlite3.Connection | None = None,
    conn: sqlite3.Connection | None = None,
) -> SessionPathNameLookup | None:
    """Pick the first available name lookup source.

    Args:
        name_resolver (SessionPathNameLookup | sqlite3.Connection | None): Explicit resolver.
        resolver (SessionPathNameLookup | sqlite3.Connection | None): Alias for ``name_resolver``.
        conn (sqlite3.Connection | None): SQLite connection for DB lookup.

    Returns:
        SessionPathNameLookup | None: Resolver instance, or ``None`` when absent.

    Examples:
        >>> _resolve_name_lookup() is None
        True
    """
    for candidate in (name_resolver, resolver):
        lookup = _coerce_name_lookup(candidate)
        if lookup is not None:
            return lookup
    return _coerce_name_lookup(conn)


def _parse_scope_key(
    scope_key: str,
    *,
    name_resolver: SessionPathNameLookup | sqlite3.Connection | None = None,
    resolver: SessionPathNameLookup | sqlite3.Connection | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[str, dict[str, Any]]:
    """Map ``gateway_sessions.scope_key`` to mirror path parts.

    Args:
        scope_key (str): Session scope key.
        name_resolver (SessionPathNameLookup | None): Optional title lookup.
        resolver (SessionPathNameLookup | None): Alias for ``name_resolver``.
        conn (sqlite3.Connection | None): SQLite connection for DB-backed lookup.

    Returns:
        tuple[str, dict[str, Any]]: Relative path under ``sessions/`` and extras.

    Examples:
        >>> rel, extra = _parse_scope_key("telegram:99:topic:7")
        >>> "topics/7" in rel
        True
        >>> extra["topic_id"]
        '7'
    """
    lookup = _resolve_name_lookup(name_resolver=name_resolver, resolver=resolver, conn=conn)
    if scope_key.startswith("telegram:"):
        parts = scope_key.split(":")
        chat_id = parts[1] if len(parts) > 1 else "0"
        chat_seg = _chat_path_segment(chat_id, lookup)
        if len(parts) >= 4 and parts[2] == "topic":
            topic_id = parts[3]
            topic_seg = _topic_path_segment(chat_id, topic_id, lookup)
            rel = f"telegram/chats/{chat_seg}/topics/{topic_seg}"
            return rel, {"chat_id": chat_id, "topic_id": topic_id}
        rel = f"telegram/chats/{chat_seg}/general"
        return rel, {"chat_id": chat_id, "topic_id": None}
    if scope_key.startswith("webchat:"):
        sub = scope_key.split(":", 1)[1] if ":" in scope_key else "user"
        rel = f"webchat/users/{_safe_segment(sub)}"
        return rel, {"webchat_sub": sub}
    channel = scope_key.split(":", 1)[0] if ":" in scope_key else "other"
    rel = f"{_safe_segment(channel)}/scopes/{_safe_segment(scope_key)}"
    return rel, {"scope_key": scope_key}


def _load_index(index_path: Path) -> dict[str, Any]:
    """Load ``sessions/_index.json`` or return an empty sessions map.

    Args:
        index_path (Path): Path to ``_index.json``.

    Returns:
        dict[str, Any]: Parsed index with a ``sessions`` dict key.

    Examples:
        >>> from pathlib import Path
        >>> data = _load_index(Path("/nonexistent/_index.json"))
        >>> data["sessions"]
        {}
    """
    if not index_path.is_file():
        return {"sessions": {}}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}
    if not isinstance(data, dict):
        return {"sessions": {}}
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        data["sessions"] = {}
    return data


def _update_index(
    *,
    content_root: Path,
    session_id: str,
    scope_key: str,
    channel: str,
    jsonl_rel: str,
) -> None:
    """Upsert one session row in ``sessions/_index.json``.

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        scope_key (str): Session scope key.
        channel (str): Channel name.
        jsonl_rel (str): Relative path to the session JSONL file.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     _update_index(
        ...         content_root=root,
        ...         session_id="s1",
        ...         scope_key="webchat:u1",
        ...         channel="webchat",
        ...         jsonl_rel="sessions/webchat/u1/s1.jsonl",
        ...     )
        ...     (root / "sessions" / "_index.json").is_file()
        True
    """
    index_path = content_root / "sessions" / _INDEX_NAME
    index_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_index(index_path)
    sessions = data.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        data["sessions"] = sessions
    sessions[session_id] = {
        "scope_key": scope_key,
        "channel": channel,
        "jsonl": jsonl_rel,
        "updated_at": datetime.now(tz=UTC).replace(tzinfo=None).isoformat(),
    }
    index_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mark_session_superseded(
    *,
    content_root: Path,
    old_session_id: str,
    new_session_id: str,
) -> None:
    """Record ``superseded_by`` on the archived session index entry (best-effort).

    Args:
        content_root (Path): Workspace content root.
        old_session_id (str): Archived gateway session id.
        new_session_id (str): Successor session id after ``/new``.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     _update_index(
        ...         content_root=root,
        ...         session_id="old",
        ...         scope_key="webchat:u1",
        ...         channel="webchat",
        ...         jsonl_rel="webchat/users/u1/old.jsonl",
        ...     )
        ...     mark_session_superseded(
        ...         content_root=root,
        ...         old_session_id="old",
        ...         new_session_id="new",
        ...     )
        ...     import json
        ...     data = json.loads((root / "sessions" / "_index.json").read_text())
        ...     data["sessions"]["old"]["superseded_by"]
        'new'
    """
    try:
        index_path = content_root / "sessions" / _INDEX_NAME
        if not index_path.is_file():
            return
        data = _load_index(index_path)
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            return
        entry = sessions.get(old_session_id)
        if not isinstance(entry, dict):
            return
        entry["superseded_by"] = new_session_id
        entry["updated_at"] = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
        index_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "session_mirror superseded index failed old={} new={} err={}",
            old_session_id,
            new_session_id,
            exc,
        )


def mirror_gateway_message(
    *,
    content_root: Path,
    workspace: WorkspaceConfig,
    message_id: int,
    session_id: str,
    scope_key: str,
    channel: str,
    user_id: str,
    role: str,
    kind: str,
    content: str,
    visible_to_llm: int,
    status: str,
    created_at: str,
    extras_json: str | None,
    turn_id: str | None = None,
    name_resolver: SessionPathNameLookup | sqlite3.Connection | None = None,
    resolver: SessionPathNameLookup | sqlite3.Connection | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Append one gateway message row to the workspace JSONL mirror (best-effort).

    Args:
        content_root (Path): Workspace content root.
        workspace (WorkspaceConfig): Parsed workspace (mirror toggle).
        message_id (int): ``gateway_messages.id``.
        scope_key (str): ``gateway_sessions.scope_key``.
        channel (str): Session channel.
        user_id (str): Session user id.
        session_id (str): Owning session.
        role (str): Message role.
        kind (str): Message kind.
        content (str): Body text.
        visible_to_llm (int): LLM visibility flag.
        status (str): Delivery status.
        created_at (str): Row timestamp.
        extras_json (str | None): Adapter metadata JSON.
        turn_id (str | None): Optional turn correlation id.
        name_resolver (SessionPathNameLookup | None): Optional title lookup.
        resolver (SessionPathNameLookup | None): Alias for ``name_resolver``.
        conn (sqlite3.Connection | None): SQLite connection for DB-backed lookup.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> mirror_gateway_message(
        ...     content_root=Path(tempfile.mkdtemp()),
        ...     workspace=WorkspaceConfig.minimal(),
        ...     message_id=1,
        ...     session_id="s",
        ...     scope_key="webchat:u",
        ...     channel="webchat",
        ...     user_id="u",
        ...     role="user",
        ...     kind="message",
        ...     content="hi",
        ...     visible_to_llm=1,
        ...     status="sent",
        ...     created_at="2026-01-01T00:00:00",
        ...     extras_json=None,
        ...     turn_id="t1",
        ... )
    """
    if not session_mirror_enabled(workspace):
        return
    try:
        scope_rel, scope_extras = _parse_scope_key(
            scope_key,
            name_resolver=name_resolver,
            resolver=resolver,
            conn=conn,
        )
        extras: dict[str, Any] = dict(scope_extras)
        if extras_json:
            try:
                parsed = json.loads(extras_json)
                if isinstance(parsed, dict):
                    extras.update(parsed)
            except json.JSONDecodeError:
                pass
        record = {
            "id": message_id,
            "ts": created_at,
            "role": role,
            "kind": kind,
            "content": content,
            "status": status,
            "visible_to_llm": bool(visible_to_llm),
            "turn_id": turn_id,
            "from_user_id": user_id,
            "session_id": session_id,
            "scope_key": scope_key,
            "channel": channel,
            "extras": extras,
        }
        base = content_root / "sessions" / scope_rel
        base.mkdir(parents=True, exist_ok=True)
        # §3 (`PROBLEMS.md`): non-LLM command callbacks (menu clicks, qa buttons,
        # restart confirms) belong in ``actions.jsonl``, not the session log. They
        # never reach the agent and just pollute the user-visible transcript.
        if kind == "command" and not bool(visible_to_llm):
            actions_path = base / "actions.jsonl"
            _append_jsonl_line(actions_path, record)
            return
        jsonl_path = base / f"{_safe_segment(session_id)}.jsonl"
        _append_jsonl_line(jsonl_path, record)
        jsonl_rel = str(jsonl_path.relative_to(content_root / "sessions"))
        _update_index(
            content_root=content_root,
            session_id=session_id,
            scope_key=scope_key,
            channel=channel,
            jsonl_rel=jsonl_rel,
        )
        if channel == "telegram":
            users_dir = content_root / "sessions" / "telegram" / "users"
            users_dir.mkdir(parents=True, exist_ok=True)
            user_path = users_dir / f"{_safe_segment(user_id)}.json"
            user_path.write_text(
                json.dumps(
                    {"telegram_user_id": user_id, "last_seen_at": created_at},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    except OSError as exc:
        logger.warning("session_mirror append failed session_id={} err={}", session_id, exc)
