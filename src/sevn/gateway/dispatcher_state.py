"""``dispatcher_state`` insert + expiry sweeper (`specs/17-gateway.md` §3.4).

Module: sevn.gateway.dispatcher_state
Depends: sqlite3, time, sevn.config.defaults, sevn.gateway.commands.dispatcher_kinds

Exports:
    dispatcher_state_ttl_for_kind — resolve per-kind TTL from workspace overrides.
    insert_dispatcher_state — validated insert with ``expires_at`` from TTL.
    sweep_expired_dispatcher_state — delete rows past ``expires_at``.
Examples:
    >>> from sevn.gateway.commands.dispatcher_kinds import ALL_DISPATCHER_KINDS
    >>> len(ALL_DISPATCHER_KINDS) >= 10
    True
"""

from __future__ import annotations

import sqlite3
import time

from sevn.config.defaults import DEFAULT_DISPATCHER_STATE_TTL_SECONDS
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.dispatcher_kinds import ALL_DISPATCHER_KINDS


def dispatcher_state_ttl_for_kind(
    kind: str,
    workspace: WorkspaceConfig | None = None,
) -> int:
    """Return TTL seconds for *kind*, honouring workspace ``dispatcher_state.ttl_seconds``.
    Args:
        kind (str): ``dispatcher_state.kind`` discriminator.
        workspace (WorkspaceConfig | None): Optional workspace overrides.
    Returns:
        int: Row lifetime in seconds.
    Examples:
        >>> dispatcher_state_ttl_for_kind("plan_approval")
        900
        >>> dispatcher_state_ttl_for_kind("menu")
        86400
    """
    if workspace is not None and workspace.dispatcher_state is not None:
        return int(workspace.dispatcher_state.ttl_seconds[kind])
    return int(DEFAULT_DISPATCHER_STATE_TTL_SECONDS[kind])


def insert_dispatcher_state(
    conn: sqlite3.Connection,
    *,
    token: str,
    kind: str,
    user_id: int,
    chat_id: int,
    topic_id: int | None,
    payload_json: str,
    ttl_seconds: int,
    consumed: int = 0,
) -> None:
    """Insert one ``dispatcher_state`` row after validating *kind*.
    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle (migration ≥6).
        token (str): Primary key token (e.g. ``ds:<hex>``).
        kind (str): Row discriminator; must be in ``ALL_DISPATCHER_KINDS``.
        user_id (int): Creator or ``0`` when chat-scoped.
        chat_id (int): Telegram chat id for lookup scoping.
        topic_id (int | None): Forum thread id when applicable.
        payload_json (str): Serialised handoff payload.
        ttl_seconds (int): Row lifetime in seconds from insert time.
        consumed (int): Consumption flag (``0`` or ``1``).
    Examples:
        >>> import sqlite3, json, time
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> payload = json.dumps({"v": 1}, separators=(",", ":"))
        >>> insert_dispatcher_state(
        ...     c,
        ...     token="ds:ab",
        ...     kind="callback_overflow",
        ...     user_id=0,
        ...     chat_id=1,
        ...     topic_id=None,
        ...     payload_json=payload,
        ...     ttl_seconds=3600,
        ... )
        >>> row = c.execute(
        ...     "SELECT kind, expires_at FROM dispatcher_state WHERE token = ?",
        ...     ("ds:ab",),
        ... ).fetchone()
        >>> row is not None and row[0] == "callback_overflow"
        True
    """
    if kind not in ALL_DISPATCHER_KINDS:
        msg = f"unknown dispatcher_state kind: {kind!r}"
        raise ValueError(msg)
    now = int(time.time())
    expires_at = now + int(ttl_seconds)
    conn.execute(
        """
        INSERT INTO dispatcher_state (
            token, kind, user_id, chat_id, topic_id,
            payload_json, created_at, expires_at, consumed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (token, kind, user_id, chat_id, topic_id, payload_json, now, expires_at, consumed),
    )
    conn.commit()


def sweep_expired_dispatcher_state(
    conn: sqlite3.Connection,
    *,
    now: int | None = None,
) -> int:
    """Delete ``dispatcher_state`` rows whose ``expires_at`` is at or before *now*.
    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        now (int | None): Unix epoch seconds; defaults to ``time.time()``.
    Returns:
        int: Number of rows deleted.
    Examples:
        >>> import sqlite3, json, time
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> payload = json.dumps({"v": 1}, separators=(",", ":"))
        >>> past = int(time.time()) - 10
        >>> _ = c.execute(
        ...     "INSERT INTO dispatcher_state (token, kind, user_id, chat_id, topic_id, "
        ...     "payload_json, created_at, expires_at, consumed) "
        ...     "VALUES ('t-old', 'menu', 0, 1, NULL, ?, ?, ?, 0)",
        ...     (payload, past - 100, past),
        ... )
        >>> c.commit()
        >>> sweep_expired_dispatcher_state(c, now=past + 1) >= 1
        True
    """
    ts = int(time.time()) if now is None else int(now)
    cur = conn.execute("DELETE FROM dispatcher_state WHERE expires_at <= ?", (ts,))
    conn.commit()
    return int(cur.rowcount or 0)


__all__ = [
    "dispatcher_state_ttl_for_kind",
    "insert_dispatcher_state",
    "sweep_expired_dispatcher_state",
]
