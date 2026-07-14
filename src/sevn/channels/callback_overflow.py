"""Telegram ``callback_data`` overflow via ``dispatcher_state`` (`specs/18-channel-telegram.md` §3.1, §4.5).
Module: sevn.channels.callback_overflow
Depends: json, secrets, sqlite3, time, sevn.config.defaults
Exports:
    telegram_callback_data_utf8_len — UTF-8 byte length for Bot API ``callback_data`` cap.
    tokenize_inline_keyboard_callback_data — replace overlong ``callback_data`` with ``ds:`` tokens.
    resolve_dispatcher_overflow_callback_data — expand inbound ``ds:`` token to stored payload.
Examples:
    >>> telegram_callback_data_utf8_len("a")
    1
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any

from loguru import logger

from sevn.config.defaults import (
    DISPATCHER_STATE_CALLBACK_OVERFLOW_TTL_S,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
)
from sevn.gateway.dispatcher.dispatcher_state import insert_dispatcher_state

_CALLBACK_OVERFLOW_PREFIX = "ds:"
_CALLBACK_OVERFLOW_HEX_BYTES = 16


def telegram_callback_data_utf8_len(data: str) -> int:
    """Return the UTF-8 byte length of *data* (Telegram ``callback_data`` uses a byte cap).
    Args:
        data (str): Raw callback string from the Bot API or gateway.
    Returns:
        int: Length of *data* encoded as UTF-8 bytes.
    Examples:
        >>> telegram_callback_data_utf8_len("café")
        5
    """
    return len(data.encode("utf-8"))


def tokenize_inline_keyboard_callback_data(
    markup: dict[str, Any],
    *,
    conn: sqlite3.Connection,
    chat_id: int,
    topic_id: int | None,
    ttl_seconds: int = DISPATCHER_STATE_CALLBACK_OVERFLOW_TTL_S,
    max_bytes: int = TELEGRAM_CALLBACK_DATA_MAX_BYTES,
) -> dict[str, Any]:
    """Deep-copy *markup* and persist overlong ``callback_data`` values in ``dispatcher_state``.
    Each replaced button stores a small JSON blob with keys ``v`` and ``callback_data`` under a random
    ``ds:<hex>`` token (35 UTF-8 bytes). Rows use ``kind='callback_overflow'`` and
    ``user_id=0`` (any member of *chat_id* may resolve while the row is unexpired).
    Args:
        markup (dict[str, Any]): Bot API ``InlineKeyboardMarkup``-shaped dict.
        conn (sqlite3.Connection): Open DB containing ``dispatcher_state``.
        chat_id (int): Destination chat for scoping lookups.
        topic_id (int | None): Forum thread id when applicable (stored for diagnostics).
        ttl_seconds (int): Row lifetime in seconds from insert time.
        max_bytes (int): Maximum UTF-8 length before tokenisation (Telegram allows 64).
    Returns:
        dict[str, Any]: New markup safe to pass to ``sendMessage`` / ``editMessageText``.
    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> long = "x" * 70
        >>> m = {"inline_keyboard": [[{"text": "b", "callback_data": long}]]}
        >>> out = tokenize_inline_keyboard_callback_data(
        ...     m, conn=conn, chat_id=1, topic_id=None,
        ... )
        >>> telegram_callback_data_utf8_len(
        ...     out["inline_keyboard"][0][0]["callback_data"],
        ... ) <= 64
        True
        >>> m["inline_keyboard"][0][0]["callback_data"] == long
        True
    """
    out: dict[str, Any] = json.loads(json.dumps(markup))
    kbd = out.get("inline_keyboard")
    if not isinstance(kbd, list):
        return out
    new_rows: list[Any] = []
    for row in kbd:
        if not isinstance(row, list):
            new_rows.append(row)
            continue
        new_row: list[Any] = []
        for cell in row:
            if not isinstance(cell, dict):
                new_row.append(cell)
                continue
            new_cell = dict(cell)
            cb = new_cell.get("callback_data")
            if isinstance(cb, str) and telegram_callback_data_utf8_len(cb) > max_bytes:
                tok = (
                    f"{_CALLBACK_OVERFLOW_PREFIX}{secrets.token_hex(_CALLBACK_OVERFLOW_HEX_BYTES)}"
                )
                payload = json.dumps({"v": 1, "callback_data": cb}, separators=(",", ":"))
                try:
                    insert_dispatcher_state(
                        conn,
                        token=tok,
                        kind="callback_overflow",
                        user_id=0,
                        chat_id=chat_id,
                        topic_id=topic_id,
                        payload_json=payload,
                        ttl_seconds=ttl_seconds,
                    )
                except sqlite3.Error:
                    logger.exception("dispatcher_state_callback_overflow_insert_failed")
                else:
                    new_cell["callback_data"] = tok
            new_row.append(new_cell)
        new_rows.append(new_row)
    out["inline_keyboard"] = new_rows
    return out


def resolve_dispatcher_overflow_callback_data(
    conn: sqlite3.Connection,
    *,
    data: str,
    chat_id: int,
) -> str | None:
    """If *data* is a ``ds:`` overflow token, return the stored full ``callback_data`` string.
    Args:
        conn (sqlite3.Connection): SQLite connection with ``dispatcher_state`` migrated.
        data (str): Raw ``callback_query.data`` from Telegram.
        chat_id (int): Chat id from the same update (authorisation scope).
    Returns:
        str | None: Expanded callback string, or ``None`` when *data* is not a known token.
    Examples:
        >>> import sqlite3, json, time
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> tok = "ds:" + "ab" * 16
        >>> payload = json.dumps({"v": 1, "callback_data": "hello"}, separators=(",", ":"))
        >>> now = int(time.time())
        >>> sql = (
        ...     "INSERT INTO dispatcher_state (token, kind, user_id, chat_id, topic_id, "
        ...     "payload_json, created_at, expires_at, consumed) VALUES (?, 'callback_overflow', "
        ...     "0, 1, NULL, ?, ?, ?, 0)"
        ... )
        >>> _ = conn.execute(sql, (tok, payload, now, now + 3600))
        >>> conn.commit()
        >>> resolve_dispatcher_overflow_callback_data(conn, data=tok, chat_id=1)
        'hello'
        >>> resolve_dispatcher_overflow_callback_data(conn, data="menu:home", chat_id=1) is None
        True
    """
    if not data.startswith(_CALLBACK_OVERFLOW_PREFIX):
        return None
    hx = data[len(_CALLBACK_OVERFLOW_PREFIX) :]
    if len(hx) != _CALLBACK_OVERFLOW_HEX_BYTES * 2:
        return None
    try:
        bytes.fromhex(hx)
    except ValueError:
        return None
    now = int(time.time())
    try:
        row = conn.execute(
            """
            SELECT payload_json FROM dispatcher_state
            WHERE token = ? AND chat_id = ? AND kind = 'callback_overflow'
              AND expires_at > ?
            """,
            (data, chat_id, now),
        ).fetchone()
    except sqlite3.Error:
        logger.exception("dispatcher_state_callback_overflow_select_failed")
        return None
    if row is None or row[0] is None:
        return None
    try:
        obj = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    inner = obj.get("callback_data")
    return inner if isinstance(inner, str) else None
