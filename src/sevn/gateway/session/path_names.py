"""Telegram display-name resolution for session mirror paths (#21).

Module: sevn.gateway.session.path_names
Depends: re, sqlite3, sevn.storage.telegram_names

Exports:
    SessionPathNameLookup — protocol for group/topic title lookup.
    SessionPathNameResolver — DB-backed resolver for mirror paths.
    safe_path_segment — filesystem-safe slug for mirror directories.
    format_named_path_segment — build ``{slug}--{id}`` or ID-only segment.
    coerce_name_lookup — wrap bare SQLite connections as resolvers.
    chat_path_segment — ``telegram/chats/{segment}`` folder name.
    topic_path_segment — ``topics/{segment}`` folder name.
    parse_telegram_scope_rel — map ``telegram:…`` scope keys to mirror rel paths.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Protocol, runtime_checkable

from sevn.storage.telegram_names import get_telegram_chat_name, get_telegram_topic_name


@runtime_checkable
class SessionPathNameLookup(Protocol):
    """Minimal resolver surface for ``_parse_scope_key`` name enrichment."""

    def get_chat_name(self, chat_id: str) -> str | None:
        """Return a group/supergroup title for ``chat_id``, or ``None`` when unknown.

        Args:
            chat_id (str): Telegram chat id string.

        Returns:
            str | None: Display title when known.

        Examples:
            >>> class _Stub:
            ...     def get_chat_name(self, chat_id: str) -> str | None:
            ...         return None
            >>> _Stub().get_chat_name("-1") is None
            True
        """

    def get_topic_name(self, chat_id: str, topic_id: str) -> str | None:
        """Return a forum topic title, or ``None`` when unknown.

        Args:
            chat_id (str): Telegram group chat id string.
            topic_id (str): Forum topic id string.

        Returns:
            str | None: Display title when known.

        Examples:
            >>> class _Stub:
            ...     def get_topic_name(self, chat_id: str, topic_id: str) -> str | None:
            ...         return None
            >>> _Stub().get_topic_name("-1", "7") is None
            True
        """


class SessionPathNameResolver:
    """Resolve Telegram group and forum topic titles from SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind a SQLite connection for name lookups.

        Args:
            conn (sqlite3.Connection): Open connection with migrations applied.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> SessionPathNameResolver(conn).get_chat_name("-1") is None
            True
            >>> conn.close()
        """
        self._conn = conn

    def get_chat_name(self, chat_id: str) -> str | None:
        """Return a persisted group/supergroup title.

        Args:
            chat_id (str): Telegram chat id string.

        Returns:
            str | None: Stored title, or ``None`` when unknown.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> SessionPathNameResolver(conn).get_chat_name("-55") is None
            True
            >>> conn.close()
        """
        try:
            cid = int(chat_id)
        except ValueError:
            return None
        return get_telegram_chat_name(self._conn, cid)

    def get_topic_name(self, chat_id: str, topic_id: str) -> str | None:
        """Return a persisted forum topic title.

        Args:
            chat_id (str): Telegram group chat id string.
            topic_id (str): Forum topic id string.

        Returns:
            str | None: Stored title, or ``None`` when unknown.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> SessionPathNameResolver(conn).get_topic_name("-100", "7") is None
            True
            >>> conn.close()
        """
        try:
            cid = int(chat_id)
            tid = int(topic_id)
        except ValueError:
            return None
        return get_telegram_topic_name(self._conn, cid, tid)


def safe_path_segment(value: str) -> str:
    """Sanitize a path segment for mirror directories and filenames.

    Args:
        value (str): Raw scope or id fragment.

    Returns:
        str: Filesystem-safe segment (never empty).

    Examples:
        >>> safe_path_segment("telegram:123:topic:42")
        'telegram_123_topic_42'
    """
    cleaned = re.sub(r"[^\w.\-]+", "_", value.strip())
    return cleaned or "unknown"


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
    return f"{safe_path_segment(name)}--{suffix_id}"


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


def coerce_name_lookup(
    value: SessionPathNameLookup | sqlite3.Connection | None,
) -> SessionPathNameLookup | None:
    """Normalize lookup arguments, wrapping bare SQLite connections.

    Args:
        value (SessionPathNameLookup | sqlite3.Connection | None): Lookup source.

    Returns:
        SessionPathNameLookup | None: Coerced resolver, or ``None``.

    Examples:
        >>> coerce_name_lookup(None) is None
        True
    """
    if value is None:
        return None
    if isinstance(value, sqlite3.Connection):
        return SessionPathNameResolver(value)
    return value


def chat_path_segment(chat_id: str, lookup: SessionPathNameLookup | None) -> str:
    """Build the ``telegram/chats/{segment}`` folder name for one chat id.

    Args:
        chat_id (str): Parsed chat id from a scope key.
        lookup (SessionPathNameLookup | None): Optional title lookup.

    Returns:
        str: Filesystem-safe chat folder segment.

    Examples:
        >>> chat_path_segment("99", None)
        '99'
    """
    if lookup is not None and _should_enrich_telegram_names(chat_id):
        return format_named_path_segment(lookup.get_chat_name(chat_id), chat_id)
    return safe_path_segment(chat_id)


def topic_path_segment(
    chat_id: str,
    topic_id: str,
    lookup: SessionPathNameLookup | None,
) -> str:
    """Build the ``topics/{segment}`` folder name for one forum topic id.

    Args:
        chat_id (str): Parsed chat id from a scope key.
        topic_id (str): Parsed topic id from a scope key.
        lookup (SessionPathNameLookup | None): Optional title lookup.

    Returns:
        str: Filesystem-safe topic folder segment.

    Examples:
        >>> topic_path_segment("-100", "7", None)
        '7'
    """
    if lookup is not None and _should_enrich_telegram_names(chat_id):
        return format_named_path_segment(lookup.get_topic_name(chat_id, topic_id), topic_id)
    return safe_path_segment(topic_id)


def parse_telegram_scope_rel(
    scope_key: str,
    lookup: SessionPathNameLookup | None,
) -> tuple[str, dict[str, Any]] | None:
    """Map a ``telegram:…`` scope key to mirror path parts.

    Args:
        scope_key (str): Session scope key.
        lookup (SessionPathNameLookup | None): Optional title lookup.

    Returns:
        tuple[str, dict[str, Any]] | None: Relative path under ``sessions/`` and extras,
        or ``None`` when ``scope_key`` is not a telegram scope.

    Examples:
        >>> parse_telegram_scope_rel("telegram:99:topic:7", None)[0]
        'telegram/chats/99/topics/7'
    """
    if not scope_key.startswith("telegram:"):
        return None
    parts = scope_key.split(":")
    chat_id = parts[1] if len(parts) > 1 else "0"
    chat_seg = chat_path_segment(chat_id, lookup)
    if len(parts) >= 4 and parts[2] == "topic":
        topic_id = parts[3]
        topic_seg = topic_path_segment(chat_id, topic_id, lookup)
        rel = f"telegram/chats/{chat_seg}/topics/{topic_seg}"
        return rel, {"chat_id": chat_id, "topic_id": topic_id}
    rel = f"telegram/chats/{chat_seg}/general"
    return rel, {"chat_id": chat_id, "topic_id": None}
