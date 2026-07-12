"""Throttle helper for ``personality_version`` bumps (`specs/32-memory-honcho.md` §3.2).

Module: sevn.memory.user_model.throttle
Depends: datetime

Exports:
    personality_bump_allowed — spacing gate for cache-bump policy.

Examples:
    >>> from datetime import UTC, datetime
    >>> personality_bump_allowed(last_bump_at=None, now=datetime(2026, 1, 1, tzinfo=UTC), throttle_minutes=60)
    True
"""

from __future__ import annotations

from datetime import datetime


def personality_bump_allowed(
    *,
    last_bump_at: datetime | None,
    now: datetime,
    throttle_minutes: int,
) -> bool:
    """Return True when a bump is allowed after ``throttle_minutes`` spacing.

    Args:
        last_bump_at (datetime | None): Last recorded bump instant, if any.
        now (datetime): Current instant (timezone-aware recommended).
        throttle_minutes (int): Minimum spacing; non-positive values always allow.

    Returns:
        bool: ``True`` when a new bump may be applied.

    Examples:
        >>> from datetime import UTC, datetime, timedelta
        >>> t0 = datetime(2026, 1, 1, tzinfo=UTC)
        >>> personality_bump_allowed(last_bump_at=t0, now=t0 + timedelta(minutes=30), throttle_minutes=60)
        False
    """

    if last_bump_at is None:
        return True
    if throttle_minutes <= 0:
        return True
    delta = now - last_bump_at
    return delta.total_seconds() >= throttle_minutes * 60


__all__ = ["personality_bump_allowed"]
