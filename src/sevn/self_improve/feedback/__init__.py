"""Explicit feedback inserts (`specs/33-self-improvement.md` §3.4).

Module: sevn.self_improve.feedback
Depends: datetime, json, sqlite3, uuid

Exports:
    insert_feedback_event — immutable projection row into ``feedback_events``.
    mirror_structured_feedback_to_events — project Q&A submits into ``feedback_events``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def insert_feedback_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    target_turn_id: str,
    schema_version: int,
    payload: dict[str, object],
) -> str:
    """Persist one structured feedback envelope.

    Args:
    conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
    kind (str): Lifecycle event (``thumbs_up``, ``thumbs_down``, ``thumbs_up_clear``,
        ``thumbs_down_clear``, ``thumbs_switch``, …).
    target_turn_id (str): Join key into trajectory facts.
    schema_version (int): Wire envelope schema version (currently ``1``).
    payload (dict[str, object]): Redacted JSON payload.

    Returns:
        str: New ``feedback_id``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> fid = insert_feedback_event(
        ...     conn,
        ...     kind="thumbs_down",
        ...     target_turn_id="t1",
        ...     schema_version=1,
        ...     payload={"note": "x"},
        ... )
        >>> len(fid) > 0
        True
        >>> conn.close()
    """
    feedback_id = uuid.uuid4().hex
    created_at = datetime.now(tz=UTC).isoformat()
    conn.execute(
        """INSERT INTO feedback_events (
            feedback_id, kind, target_turn_id, schema_version, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            feedback_id,
            kind,
            target_turn_id,
            schema_version,
            json.dumps(payload, sort_keys=True),
            created_at,
        ),
    )
    conn.commit()
    return feedback_id


def mirror_structured_feedback_to_events(
    conn: sqlite3.Connection,
    *,
    feedback_id: str,
    target_turn_id: str,
    channel: str,
    body_text: str,
    dropdowns: dict[str, str],
) -> str:
    """Also insert a ``structured_feedback_submit`` row into ``feedback_events``.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` connection.
        feedback_id (str): Primary key from ``structured_feedback``.
        target_turn_id (str): Join key for sampler buckets.
        channel (str): Ingress channel label.
        body_text (str): Free-text body (may be empty).
        dropdowns (dict[str, str]): Structured dropdown answers.

    Returns:
        str: New ``feedback_events.feedback_id``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> fid = mirror_structured_feedback_to_events(
        ...     c,
        ...     feedback_id="sf1",
        ...     target_turn_id="t1",
        ...     channel="web",
        ...     body_text="bad routing",
        ...     dropdowns={"severity": "high"},
        ... )
        >>> len(fid) > 0
        True
        >>> c.close()
    """
    payload: dict[str, object] = {
        "structured_feedback_id": feedback_id,
        "channel": channel,
        "body_text": body_text,
        "dropdowns": dropdowns,
    }
    return insert_feedback_event(
        conn,
        kind="structured_feedback_submit",
        target_turn_id=target_turn_id,
        schema_version=1,
        payload=payload,
    )


__all__ = ["insert_feedback_event", "mirror_structured_feedback_to_events"]
