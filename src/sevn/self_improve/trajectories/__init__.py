"""Trajectory turn keys and denormalised rows (`specs/33-self-improvement.md` §3.1).

Module: sevn.self_improve.trajectories
Depends: dataclasses, hashlib

Exports:
    stable_turn_id — deterministic id for a single user→assistant turn.
    TrajectoryTurn — lightweight fact carrier for sampler inputs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal


def stable_turn_id(*, session_id: str, user_message_id: str, trace_root: str) -> str:
    """Compute the canonical ``turn_id`` for sampler keys.

    Args:
    session_id (str): Gateway session identifier.
    user_message_id (str): Channel message id for the inbound user turn.
    trace_root (str): Trace root id (may be empty when tracing is absent).

    Returns:
        str: Hex digest used as ``turn_id``.

    Examples:
        >>> stable_turn_id(session_id="s", user_message_id="m", trace_root="t") == stable_turn_id(
        ...     session_id="s",
        ...     user_message_id="m",
        ...     trace_root="t",
        ... )
        True
    """
    payload = f"{session_id}\n{user_message_id}\n{trace_root}".encode()
    return hashlib.sha256(payload).hexdigest()


ChannelName = Literal["telegram", "web", "voice", "claude_agent", "webhook", "unknown"]
ComplexityTier = Literal["A", "B", "C", "D"]


@dataclass(frozen=True, slots=True)
class TrajectoryTurn:
    """Minimal turn projection consumed by deterministic detectors."""

    turn_id: str
    session_id: str
    trace_id: str | None
    channel: ChannelName
    intent: str | None
    complexity_tier: ComplexityTier | None
    signals: dict[str, Any]
