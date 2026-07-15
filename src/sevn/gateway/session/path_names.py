"""Telegram display-name resolution for session mirror paths (#21).

Module: sevn.gateway.session.path_names
Depends: sqlite3, sevn.storage.telegram_names

Exports:
    SessionPathNameLookup — protocol for group/topic title lookup.
    SessionPathNameResolver — DB-backed resolver for mirror paths.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol, runtime_checkable

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
