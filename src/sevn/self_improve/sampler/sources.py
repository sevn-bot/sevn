"""Sampler candidate pool from ``trajectory_fact`` + ``feedback_events`` (`specs/33-self-improvement.md`).

Module: sevn.self_improve.sampler.sources
Depends: hashlib, json, sqlite3, sevn.self_improve.sampler

Exports:
    load_sampler_candidates — build :class:`ShortlistCandidate` rows for one job window.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3  # noqa: TC003 — runtime sampler pool queries
from typing import Literal

from sevn.self_improve.sampler import ShortlistCandidate

_EXPLICIT_KINDS: frozenset[str] = frozenset(
    {
        "thumbs_down",
        "structured_feedback_submit",
    },
)


def _bucket_for_turn(
    *,
    turn_id: str,
    explicit_turns: set[str],
    failure_turns: set[str],
    sampler_seed: int,
) -> Literal[
    "explicit_feedback",
    "heuristic_regressions",
    "execution_failures",
    "control_random_sample",
]:
    """Assign one trajectory turn to a sampler bucket.

    Args:
        turn_id (str): Trajectory primary key.
        explicit_turns (set[str]): Turns with explicit negative feedback.
        failure_turns (set[str]): Turns with tool/sandbox failures in signals.
        sampler_seed (int): Deterministic control-sample seed.

    Returns:
        Literal[...]: Bucket id for :func:`allocate_shortlist`.

    Examples:
        >>> _bucket_for_turn(
        ...     turn_id="t1",
        ...     explicit_turns={"t1"},
        ...     failure_turns=set(),
        ...     sampler_seed=1,
        ... )
        'explicit_feedback'
    """
    if turn_id in explicit_turns:
        return "explicit_feedback"
    if turn_id in failure_turns:
        return "execution_failures"
    digest = hashlib.sha256(f"{sampler_seed}:{turn_id}".encode()).hexdigest()
    if int(digest[:8], 16) % 20 == 0:
        return "control_random_sample"
    return "heuristic_regressions"


def _load_explicit_turns(conn: sqlite3.Connection) -> set[str]:
    """Return turn ids with explicit negative feedback events.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db``.

    Returns:
        set[str]: ``target_turn_id`` values for explicit bucket eligibility.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_explicit_turns(c) == set()
        True
        >>> c.close()
    """
    rows = conn.execute(
        """SELECT DISTINCT target_turn_id FROM feedback_events
            WHERE kind IN (?, ?) OR kind LIKE 'thumbs_down%'""",
        tuple(_EXPLICIT_KINDS),
    ).fetchall()
    explicit: set[str] = set()
    for row in rows:
        explicit.add(str(row[0]))
    sf_rows = conn.execute(
        """SELECT DISTINCT target_turn_id FROM structured_feedback
            WHERE body_text IS NOT NULL AND TRIM(body_text) != ''""",
    ).fetchall()
    for row in sf_rows:
        explicit.add(str(row[0]))
    return explicit


def _failure_turns_from_signals(signals_json: str) -> bool:
    """Return whether parsed trajectory signals indicate execution failure.

    Args:
        signals_json (str): Serialised ``trajectory_fact.signals`` column.

    Returns:
        bool: ``True`` when any tool row has non-ok status.

    Examples:
        >>> _failure_turns_from_signals(
        ...     '{"tools":[{"status":"error"}]}',
        ... )
        True
    """
    try:
        signals = json.loads(signals_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(signals, dict):
        return False
    tools = signals.get("tools")
    if not isinstance(tools, list):
        return False
    for row in tools:
        if isinstance(row, dict) and str(row.get("status", "ok")).lower() not in (
            "ok",
            "success",
            "passed",
        ):
            return True
    return False


def load_sampler_candidates(
    conn: sqlite3.Connection,
    *,
    sampler_seed: int,
    limit: int = 500,
) -> list[ShortlistCandidate]:
    """Build the sampler pool from persisted trajectory and feedback tables.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` with migrations applied.
        sampler_seed (int): Job seed for control-bucket hashing.
        limit (int): Maximum trajectory rows to consider.

    Returns:
        list[ShortlistCandidate]: Pool passed to :func:`allocate_shortlist`.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> load_sampler_candidates(c, sampler_seed=1) == []
        True
        >>> c.close()
    """
    explicit_turns = _load_explicit_turns(conn)
    rows = conn.execute(
        """SELECT turn_id, channel, intent, tier, signals_json
            FROM trajectory_fact
            ORDER BY created_at DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()
    failure_turns: set[str] = set()
    for turn_id, _ch, _intent, _tier, signals_json in rows:
        if signals_json and _failure_turns_from_signals(str(signals_json)):
            failure_turns.add(str(turn_id))

    candidates: list[ShortlistCandidate] = []
    for turn_id, channel, intent, tier, signals_json in rows:
        tid = str(turn_id)
        bucket = _bucket_for_turn(
            turn_id=tid,
            explicit_turns=explicit_turns,
            failure_turns=failure_turns,
            sampler_seed=sampler_seed,
        )
        score = 1.0 if bucket == "explicit_feedback" else 0.5
        candidates.append(
            ShortlistCandidate(
                turn_id=tid,
                bucket=bucket,
                channel=str(channel or "unknown"),
                intent=str(intent) if intent is not None else None,
                complexity_tier=str(tier) if tier is not None else None,
                score=score,
                signals=json.loads(signals_json) if signals_json else None,
            ),
        )
    return candidates


__all__ = ["load_sampler_candidates"]
