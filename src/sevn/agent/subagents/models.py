"""Domain model for the level-1/level-2 sub-agent registry (D1/D3/D5).

Module: sevn.agent.subagents.models
Depends: dataclasses, enum, secrets, sevn.config.sections.subagents

Also exports the ``ACTIVE_STATUSES`` frozenset — the statuses counted against
concurrency limits.

Exports:
    SubAgentStatus — registry lifecycle states (``pending``..``orphaned``).
    SubAgentRun — one tracked level-1/level-2 run (D3 fields).
    SubAgentLimitExceeded — typed spawn-rejection result (D5), never raised.
    generate_short_id — collision-checked short id generator (D3).

Examples:
    >>> SubAgentStatus.RUNNING in ACTIVE_STATUSES
    True
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Container

    from sevn.config.sections.subagents import Role

__all__ = [
    "ACTIVE_STATUSES",
    "SubAgentLimitExceeded",
    "SubAgentRun",
    "SubAgentStatus",
    "generate_short_id",
]


class SubAgentStatus(StrEnum):
    """Registry lifecycle states for one tracked sub-agent run (D3).

    ``orphaned`` is boot-only: a previous process's ``running``/``pending``
    row that could not have survived a restart (no in-memory task exists to
    finish it), reconciled by the storage orphan sweep, not by the
    in-process supervisor.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"
    ORPHANED = "orphaned"


ACTIVE_STATUSES: frozenset[SubAgentStatus] = frozenset(
    {SubAgentStatus.PENDING, SubAgentStatus.RUNNING},
)
"""Statuses that count against level-1/level-2/specialist concurrency caps."""


@dataclass(frozen=True, slots=True)
class SubAgentRun:
    """One tracked level-1 or level-2 sub-agent run (D3).

    Args:
        id (str): Short collision-checked id (e.g. ``a1f3``), see
            :func:`generate_short_id`.
        level (Literal[1, 2]): ``1`` for a tracked tier role run, ``2`` for a
            worker spawned by a level-1 run (hard depth cap — D1).
        role (Role): Owning level-1 role (``triager``/``tier_b``/``tier_c``/
            ``tier_d``). Level-2 runs inherit their **parent's** role, since
            per-role limits (``agents.<role>.max_level2``) are attributed to
            the spawning level-1 role, not to the worker itself.
        specialist (str | None): ``subagents.specialists.<name>`` id when this
            is a specialist level-2 run (D8); ``None`` for generic workers and
            all level-1 runs.
        parent_id (str | None): ``None`` for level-1 runs; the spawning
            level-1 run's id for level-2 runs.
        session_id (str): Gateway session this run belongs to.
        channel (str): Channel name (for reply attribution — D7).
        task_summary (str): Short human-readable description of the task.
        status (SubAgentStatus): Current lifecycle state.
        started_at (int): Registration time, epoch nanoseconds.
        finished_at (int | None): Terminal-transition time, epoch nanoseconds;
            ``None`` while ``pending``/``running``.
        trace_id (str | None): OTel span id once tracing is wired (W5); ``None``
            until then.

    Examples:
        >>> run = SubAgentRun(
        ...     id="a1f3", level=1, role="tier_b", specialist=None,
        ...     parent_id=None, session_id="s1", channel="telegram",
        ...     task_summary="reply to user", status=SubAgentStatus.PENDING,
        ...     started_at=1, finished_at=None, trace_id=None,
        ... )
        >>> run.level
        1
    """

    id: str
    level: Literal[1, 2]
    role: Role
    specialist: str | None
    parent_id: str | None
    session_id: str
    channel: str
    task_summary: str
    status: SubAgentStatus
    started_at: int
    finished_at: int | None
    trace_id: str | None


@dataclass(frozen=True, slots=True)
class SubAgentLimitExceeded:
    """Typed spawn-rejection result (D5) — never raised into the turn.

    Callers fall back per D5/D6: ``multi`` queue mode steers with an operator
    notice; the ``spawn_subagent`` tool (W3) turns this into tool-error text
    the model can act on.

    Args:
        level (Literal[1, 2]): Level that was denied.
        role (Role): Owning level-1 role for the check.
        reason (Literal["level1_limit", "level2_limit", "specialist_limit"]):
            Which cap was hit.
        limit (int): The effective cap that was reached.
        current (int): Active count observed at rejection time.
        specialist (str | None): Specialist name when ``reason ==
            "specialist_limit"``.

    Examples:
        >>> exceeded = SubAgentLimitExceeded(
        ...     level=1, role="tier_b", reason="level1_limit", limit=5, current=5,
        ... )
        >>> str(exceeded)
        'sub-agent limit exceeded: level1_limit (tier_b, level 1): 5/5'
    """

    level: Literal[1, 2]
    role: Role
    reason: Literal["level1_limit", "level2_limit", "specialist_limit"]
    limit: int
    current: int
    specialist: str | None = None

    def __str__(self) -> str:
        """Human-readable summary suitable for a tool-error string or operator notice.

        Returns:
            str: One-line ``sub-agent limit exceeded: …`` summary.

        Examples:
            >>> str(SubAgentLimitExceeded(
            ...     level=2, role="tier_b", reason="specialist_limit",
            ...     limit=2, current=2, specialist="media_generator",
            ... ))
            'sub-agent limit exceeded: specialist_limit (media_generator): 2/2'
        """
        subject = self.specialist if self.specialist else f"{self.role}, level {self.level}"
        return f"sub-agent limit exceeded: {self.reason} ({subject}): {self.current}/{self.limit}"


def generate_short_id(
    existing: Container[str],
    *,
    length: int = 4,
    max_attempts: int = 8,
) -> str:
    """Generate a short lowercase-hex sub-agent id, retrying on collision (D3).

    Args:
        existing (Container[str]): Container supporting ``in`` (e.g. a ``dict``
            of registered ids, or a ``set``/``frozenset``) — candidates already
            present are rejected.
        length (int): Hex digits per attempt (default 4, e.g. ``a1f3``).
        max_attempts (int): Attempts at ``length`` before widening by one digit
            (guards against pathological collision runs without ever raising).

    Returns:
        str: A lowercase hex id not present in ``existing``.

    Examples:
        >>> new_id = generate_short_id({})
        >>> len(new_id)
        4
        >>> all(c in "0123456789abcdef" for c in new_id)
        True
        >>> generate_short_id({"aaaa"}, length=1, max_attempts=1) != "aaaa"
        True
    """
    attempt_length = max(1, length)
    while True:
        for _ in range(max_attempts):
            candidate = secrets.token_hex((attempt_length + 1) // 2)[:attempt_length]
            if candidate not in existing:
                return candidate
        attempt_length += 1
