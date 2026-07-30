"""Delivery-obligation ledger for adapter-confirmed outbound idempotency (#75).

Module: sevn.storage.delivery

Every assistant delivery persists a row before ``adapter.send`` and records the
platform message id on confirmation so boot replay can distinguish "sent but
unconfirmed" from "never sent".

Exports:
    count_open_obligations — count non-terminal obligation rows.
    create_delivery_obligation — persist a pending obligation before send.
    confirm_delivery_obligation — record adapter-confirmed platform id.
    fail_delivery_obligation — mark an obligation failed with error text.
    get_delivery_obligation — load one obligation by gateway message id.
    hash_delivery_payload — stable hash for payload metadata.
    is_delivery_confirmed — whether replay must skip ``adapter.send``.
    reconcile_confirmed_obligation — mark ``gateway_messages`` sent when confirmed.

Examples:
    >>> import sqlite3
    >>> from sevn.storage.migrate import apply_migrations
    >>> from sevn.storage.delivery import count_open_obligations
    >>> conn = sqlite3.connect(":memory:")
    >>> apply_migrations(conn)
    >>> count_open_obligations(conn)
    0
    >>> conn.close()
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any, Literal

DeliveryObligationStatus = Literal["pending", "confirmed", "failed"]


def hash_delivery_payload(content: str) -> str:
    """Return a stable hash for outbound payload metadata.

    Args:
        content (str): Assistant text persisted for delivery.

    Returns:
        str: Hex digest suitable for ``delivery_obligations.payload_hash``.

    Examples:
        >>> hash_delivery_payload("hello") == hash_delivery_payload("hello")
        True
        >>> hash_delivery_payload("a") != hash_delivery_payload("b")
        True
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_delivery_obligation(
    conn: sqlite3.Connection,
    *,
    message_id: int,
    session_id: str,
    channel: str,
    user_id: str,
    payload_hash: str,
    now_ns: int | None = None,
) -> dict[str, Any]:
    """Insert a pending delivery obligation before ``adapter.send``.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        message_id (int): ``gateway_messages.id`` for the pending assistant row.
        session_id (str): Owning gateway session id.
        channel (str): Destination channel name.
        user_id (str): Destination user id.
        payload_hash (str): Hash of the outbound payload body.
        now_ns (int | None): Optional monotonic timestamp; defaults to ``time.time_ns()``.

    Returns:
        dict[str, Any]: Snapshot of the inserted obligation row.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> conn.execute(
        ...     "INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)"
        ...     " VALUES ('s', 'telegram:1', 'telegram', '1', 'now', 'now')"
        ... )
        >>> conn.execute(
        ...     "INSERT INTO gateway_messages(session_id, role, kind, content, visible_to_llm, status, created_at)"
        ...     " VALUES ('s', 'assistant', 'message', 'hi', 1, 'pending', 'now')"
        ... )
        >>> mid = int(conn.execute("SELECT id FROM gateway_messages").fetchone()[0])
        >>> row = create_delivery_obligation(
        ...     conn, message_id=mid, session_id='s', channel='telegram', user_id='1', payload_hash='h'
        ... )
        >>> row["status"]
        'pending'
        >>> conn.close()
    """
    ts = time.time_ns() if now_ns is None else now_ns
    conn.execute(
        """
        INSERT INTO delivery_obligations (
            message_id, session_id, channel, user_id, payload_hash,
            adapter_message_id, status, error_details, created_at_ns, updated_at_ns
        ) VALUES (?, ?, ?, ?, ?, NULL, 'pending', NULL, ?, ?)
        ON CONFLICT(message_id) DO NOTHING
        """,
        (message_id, session_id, channel, user_id, payload_hash, ts, ts),
    )
    conn.commit()
    row = get_delivery_obligation(conn, message_id)
    if row is None:
        msg = f"delivery obligation missing after insert message_id={message_id}"
        raise RuntimeError(msg)
    return row


def confirm_delivery_obligation(
    conn: sqlite3.Connection,
    *,
    message_id: int,
    adapter_message_id: str,
    now_ns: int | None = None,
) -> None:
    """Record adapter-confirmed platform id for an obligation.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        message_id (int): ``gateway_messages.id`` tied to the obligation.
        adapter_message_id (str): Platform message id returned by the adapter.
        now_ns (int | None): Optional monotonic timestamp; defaults to ``time.time_ns()``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> conn.execute(
        ...     "INSERT INTO gateway_sessions(session_id, scope_key, channel, user_id, created_at, updated_at)"
        ...     " VALUES ('s', 'telegram:1', 'telegram', '1', 'now', 'now')"
        ... )
        >>> conn.execute(
        ...     "INSERT INTO gateway_messages(session_id, role, kind, content, visible_to_llm, status, created_at)"
        ...     " VALUES ('s', 'assistant', 'message', 'hi', 1, 'pending', 'now')"
        ... )
        >>> mid = int(conn.execute("SELECT id FROM gateway_messages").fetchone()[0])
        >>> create_delivery_obligation(
        ...     conn, message_id=mid, session_id='s', channel='telegram', user_id='1', payload_hash='h'
        ... )
        >>> confirm_delivery_obligation(conn, message_id=mid, adapter_message_id='tg-1')
        >>> get_delivery_obligation(conn, mid)["status"]
        'confirmed'
        >>> conn.close()
    """
    ts = time.time_ns() if now_ns is None else now_ns
    conn.execute(
        """
        UPDATE delivery_obligations
        SET adapter_message_id = ?, status = 'confirmed', updated_at_ns = ?
        WHERE message_id = ?
        """,
        (adapter_message_id, ts, message_id),
    )
    conn.commit()


def fail_delivery_obligation(
    conn: sqlite3.Connection,
    *,
    message_id: int,
    error_details: str,
    now_ns: int | None = None,
) -> None:
    """Mark a delivery obligation failed with operator-safe error text.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        message_id (int): ``gateway_messages.id`` tied to the obligation.
        error_details (str): Sanitized failure reason.
        now_ns (int | None): Optional monotonic timestamp; defaults to ``time.time_ns()``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> fail_delivery_obligation(conn, message_id=1, error_details="boom")
        >>> conn.close()
    """
    ts = time.time_ns() if now_ns is None else now_ns
    conn.execute(
        """
        UPDATE delivery_obligations
        SET status = 'failed', error_details = ?, updated_at_ns = ?
        WHERE message_id = ?
        """,
        (error_details, ts, message_id),
    )
    conn.commit()


def get_delivery_obligation(
    conn: sqlite3.Connection,
    message_id: int,
) -> dict[str, Any] | None:
    """Load one delivery obligation by gateway message id.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        message_id (int): ``gateway_messages.id`` to look up.

    Returns:
        dict[str, Any] | None: Row snapshot, or ``None`` when absent.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> get_delivery_obligation(conn, 1) is None
        True
        >>> conn.close()
    """
    row = conn.execute(
        """
        SELECT message_id, session_id, channel, user_id, payload_hash,
               adapter_message_id, status, error_details, created_at_ns, updated_at_ns
        FROM delivery_obligations
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "message_id": int(row[0]),
        "session_id": str(row[1]),
        "channel": str(row[2]),
        "user_id": str(row[3]),
        "payload_hash": str(row[4]),
        "adapter_message_id": str(row[5]) if row[5] is not None else None,
        "status": str(row[6]),
        "error_details": str(row[7]) if row[7] is not None else None,
        "created_at_ns": int(row[8]),
        "updated_at_ns": int(row[9]),
    }


def is_delivery_confirmed(conn: sqlite3.Connection, message_id: int) -> bool:
    """Return whether the platform already confirmed delivery for ``message_id``.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        message_id (int): ``gateway_messages.id`` to inspect.

    Returns:
        bool: ``True`` when a confirmed obligation with platform id exists.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> is_delivery_confirmed(conn, 999)
        False
        >>> conn.close()
    """
    row = conn.execute(
        """
        SELECT 1 FROM delivery_obligations
        WHERE message_id = ? AND status = 'confirmed' AND adapter_message_id IS NOT NULL
        """,
        (message_id,),
    ).fetchone()
    return row is not None


def reconcile_confirmed_obligation(conn: sqlite3.Connection, message_id: int) -> bool:
    """Mark ``gateway_messages`` sent when the obligation is already confirmed.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        message_id (int): ``gateway_messages.id`` to reconcile.

    Returns:
        bool: ``True`` when the message row was updated to ``sent``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> reconcile_confirmed_obligation(conn, 1)
        False
        >>> conn.close()
    """
    if not is_delivery_confirmed(conn, message_id):
        return False
    conn.execute(
        "UPDATE gateway_messages SET status = 'sent' WHERE id = ?",
        (message_id,),
    )
    conn.commit()
    return True


def count_open_obligations(conn: sqlite3.Connection) -> int:
    """Count obligations that are not terminal.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.

    Returns:
        int: Rows with ``status`` in ``pending`` or ``failed``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> count_open_obligations(conn)
        0
        >>> conn.close()
    """
    row = conn.execute(
        """
        SELECT COUNT(*) FROM delivery_obligations
        WHERE status IN ('pending', 'failed')
        """,
    ).fetchone()
    return int(row[0]) if row else 0


__all__ = [
    "DeliveryObligationStatus",
    "confirm_delivery_obligation",
    "count_open_obligations",
    "create_delivery_obligation",
    "fail_delivery_obligation",
    "get_delivery_obligation",
    "hash_delivery_payload",
    "is_delivery_confirmed",
    "reconcile_confirmed_obligation",
]
