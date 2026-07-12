"""Repo layer for ``gateway_turn_metadata`` (`PROBLEMS.md` §7 / Step §7).

Module: sevn.gateway.turn_metadata
Depends: sqlite3, datetime, sevn.gateway.session_manager._utc_now_iso

The sibling ``gateway_turn_metadata`` table (migration 21) stores the
routing-classifier output that historically leaked into the assistant
message ``content`` as an ``_intent=… · tier=… · conf=…_`` footer. By
keeping it next to the row instead of inside ``content``, the LLM never
re-reads it on the next turn and the per-channel renderer can choose
whether to display it at all (gated on
``gateway.output.show_intent_footer``).

Exports:
    TurnMetadata — projection dataclass for one row.
    record_turn_start — INSERT (or upsert) when the triager classification
        lands; called once from ``_run`` after the triage decision.
    record_turn_finished — UPDATE with ``status`` + ``finished_at`` once the
        executor (or cascade) terminates.
    load_turn_metadata — SELECT by ``turn_id``.
    format_intent_footer_from_metadata — render the ``intent=… · tier=… ·
        conf=…`` line from a loaded row (mirrors the legacy shape).

Examples:
    >>> import inspect
    >>> inspect.isfunction(record_turn_start)
    True
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from loguru import logger


def _utc_now_iso() -> str:
    """Return a timezone-aware UTC ISO-8601 timestamp.

    Mirrors :func:`sevn.gateway.session_manager._utc_now_iso` so this module
    can be imported without pulling the session manager's connection state.

    Returns:
        str: ISO-8601 with explicit ``+00:00`` offset (`PROBLEMS.md` §4).

    Examples:
        >>> _utc_now_iso().endswith("+00:00")
        True
    """
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class TurnMetadata:
    """One row from ``gateway_turn_metadata``.

    Attributes:
        turn_id (str): Stable turn correlation id (also the row PK).
        session_id (str): Owning session id.
        intent (str): Triager classification (``GREETING``, ``NEW_REQUEST``…).
        tier (str): Complexity tier (``A`` / ``B`` / ``C`` / ``D``).
        confidence (float): Triager confidence in ``[0, 1]``.
        model_id (str | None): Resolved executor model id when known.
        started_at (str): UTC ISO-8601 with offset.
        finished_at (str | None): UTC ISO-8601 with offset once the turn
            terminates; ``None`` while in flight.
        status (str): ``in_flight`` / ``ok`` / ``timeout`` / ``error`` /
            ``escalated`` / ``cancelled``.

    Examples:
        >>> from dataclasses import is_dataclass
        >>> is_dataclass(TurnMetadata)
        True
    """

    turn_id: str
    session_id: str
    intent: str
    tier: str
    confidence: float
    model_id: str | None
    started_at: str
    finished_at: str | None
    status: str


def record_turn_start(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    session_id: str,
    intent: str,
    tier: str,
    confidence: float,
    model_id: str | None = None,
) -> None:
    """Insert a fresh ``gateway_turn_metadata`` row at turn start.

    Idempotent on ``turn_id`` (PK conflict is silently logged + dropped) so
    re-tries inside the cascade don't insert a second row for the same turn.
    Status defaults to ``in_flight`` from the migration's ``DEFAULT``.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        turn_id (str): Stable turn correlation id.
        session_id (str): Owning session id.
        intent (str): Triager intent label.
        tier (str): Complexity tier label.
        confidence (float): Triager confidence (clamped to ``[0, 1]``).
        model_id (str | None): Resolved executor model id when known.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(record_turn_start)
        True
    """
    confidence_clamped = max(0.0, min(1.0, float(confidence)))
    # Check-then-upsert: distinguishes "row already exists" (cascade re-call)
    # from "FK violation against ``gateway_sessions``" — the latter must
    # propagate so a programming error in ``session_id`` lookup surfaces.
    existing = conn.execute(
        "SELECT 1 FROM gateway_turn_metadata WHERE turn_id = ?",
        (turn_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO gateway_turn_metadata (
                turn_id, session_id, intent, tier, confidence, model_id,
                started_at, finished_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'in_flight')
            """,
            (
                turn_id,
                session_id,
                intent,
                tier,
                confidence_clamped,
                model_id,
                _utc_now_iso(),
            ),
        )
        conn.commit()
    else:
        # Cascade re-call: keep ``started_at`` / ``status``, refresh the
        # classification fields so the post-retriage decision wins.
        logger.debug(
            "gateway_turn_metadata existing row — updating classification turn_id={} new_tier={}",
            turn_id,
            tier,
        )
        conn.execute(
            """
            UPDATE gateway_turn_metadata
            SET intent = ?, tier = ?, confidence = ?, model_id = COALESCE(?, model_id)
            WHERE turn_id = ?
            """,
            (intent, tier, confidence_clamped, model_id, turn_id),
        )
        conn.commit()


def record_turn_finished(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    status: str,
) -> None:
    """Stamp ``finished_at`` + ``status`` on the metadata row.

    No-op when no row exists for ``turn_id`` (e.g., a turn that bypassed the
    triager classification). Safe to call multiple times — the last call wins.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        turn_id (str): Turn correlation id.
        status (str): Terminal disposition.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(record_turn_finished)
        True
    """
    conn.execute(
        "UPDATE gateway_turn_metadata SET status = ?, finished_at = ? WHERE turn_id = ?",
        (status, _utc_now_iso(), turn_id),
    )
    conn.commit()


def load_turn_metadata(
    conn: sqlite3.Connection,
    turn_id: str,
) -> TurnMetadata | None:
    """Return the metadata row for ``turn_id`` or ``None`` when missing.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        turn_id (str): Turn correlation id.

    Returns:
        TurnMetadata | None: Hydrated dataclass or ``None`` when no row
        matches.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(load_turn_metadata)
        True
    """
    row = conn.execute(
        """
        SELECT turn_id, session_id, intent, tier, confidence, model_id,
               started_at, finished_at, status
        FROM gateway_turn_metadata
        WHERE turn_id = ?
        """,
        (turn_id,),
    ).fetchone()
    if row is None:
        return None
    return TurnMetadata(
        turn_id=str(row[0]),
        session_id=str(row[1]),
        intent=str(row[2]),
        tier=str(row[3]),
        confidence=float(row[4]),
        model_id=None if row[5] is None else str(row[5]),
        started_at=str(row[6]),
        finished_at=None if row[7] is None else str(row[7]),
        status=str(row[8]),
    )


def format_intent_footer_from_metadata(
    meta: TurnMetadata,
    *,
    triager_ms: int | None = None,
) -> str:
    """Build the human-readable ``intent=… · tier=… · conf=…`` line.

    Mirrors the historical
    :func:`sevn.gateway.routing_footer.format_routing_footer` shape so
    Telegram / webchat renderers can drop in the new metadata-based render
    path without changing the visible string.

    Args:
        meta (TurnMetadata): Loaded row.
        triager_ms (int | None): Wall-clock milliseconds spent inside
            ``triage_turn`` for this turn. Rendered as whole seconds
            (``triager_s``) when provided.

    Returns:
        str: Footer body (caller wraps in italics for MarkdownV2 if needed).

    Examples:
        >>> m = TurnMetadata(
        ...     turn_id="t1", session_id="s1", intent="GREETING",
        ...     tier="A", confidence=0.95, model_id=None,
        ...     started_at="2026-01-01T00:00:00+00:00",
        ...     finished_at=None, status="in_flight",
        ... )
        >>> format_intent_footer_from_metadata(m)
        'intent=GREETING · tier=A · conf=0.95'
        >>> format_intent_footer_from_metadata(m, triager_ms=8635)
        'intent=GREETING · tier=A · conf=0.95 · triager_s=9'
    """
    parts = [
        f"intent={meta.intent}",
        f"tier={meta.tier}",
        f"conf={meta.confidence:.2f}",
    ]
    if triager_ms is not None:
        parts.append(f"triager_s={round(triager_ms / 1000)}")
    return " · ".join(parts)


__all__ = [
    "TurnMetadata",
    "format_intent_footer_from_metadata",
    "load_turn_metadata",
    "record_turn_finished",
    "record_turn_start",
]
