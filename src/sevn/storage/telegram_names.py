"""Telegram group/topic display name lookups for gateway session paths.

Module: sevn.storage.telegram_names

Exports:
    get_telegram_chat_name — latest persisted group/supergroup title by chat id.
    get_telegram_topic_name — latest persisted forum topic title by chat + topic id.

Examples:
    >>> import sqlite3
    >>> from sevn.storage.migrate import apply_migrations
    >>> from sevn.storage.telegram_names import get_telegram_chat_name
    >>> conn = sqlite3.connect(":memory:")
    >>> apply_migrations(conn)
    >>> get_telegram_chat_name(conn, -100) is None
    True
    >>> conn.close()
"""

from __future__ import annotations

import sqlite3


def get_telegram_chat_name(conn: sqlite3.Connection, chat_id: int) -> str | None:
    """Return the latest persisted group/supergroup title, or ``None`` when unknown.

    Args:
        conn (sqlite3.Connection): Open SQLite connection with migrations applied.
        chat_id (int): Telegram chat id (negative for groups/supergroups).

    Returns:
        str | None: Stored display name, or ``None`` when no row exists.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> get_telegram_chat_name(conn, -55) is None
        True
        >>> conn.close()
    """
    row = conn.execute(
        "SELECT name FROM telegram_chat_names WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])


def get_telegram_topic_name(
    conn: sqlite3.Connection,
    chat_id: int,
    topic_id: int,
) -> str | None:
    """Return the latest persisted forum topic title, or ``None`` when unknown.

    Args:
        conn (sqlite3.Connection): Open SQLite connection with migrations applied.
        chat_id (int): Telegram group/supergroup chat id.
        topic_id (int): Forum topic id within the chat.

    Returns:
        str | None: Stored display name, or ``None`` when no row exists.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> get_telegram_topic_name(conn, -100, 7) is None
        True
        >>> conn.close()
    """
    row = conn.execute(
        "SELECT name FROM telegram_topic_names WHERE chat_id = ? AND topic_id = ?",
        (chat_id, topic_id),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])
