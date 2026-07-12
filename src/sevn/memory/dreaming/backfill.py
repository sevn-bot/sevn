"""Daily-log replay utilities (`specs/31-memory-dreaming.md` §3.3).

Module: sevn.memory.dreaming.backfill
Depends: datetime, pathlib

Exports:
    iter_backfill_dates — inclusive ``date`` bounds with cost guard.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def iter_backfill_dates(
    *,
    date_from: str | None,
    date_to: str | None,
    default_days: int,
    workspace_root: Path,
    unbounded_acknowledged: bool,
) -> tuple[date, date]:
    """Resolve inclusive date bounds for grounded backfill.

    Args:
        date_from (str | None): Optional ISO ``YYYY-MM-DD`` lower bound.
        date_to (str | None): Optional ISO upper bound (defaults to today).
        default_days (int): ``memory.dreaming.backfill_days`` ceiling.
        workspace_root (Path): Workspace root (reserved for future hints).
        unbounded_acknowledged (bool): Operator ack for wide windows.

    Returns:
        tuple[date, date]: ``(start, end)`` inclusive.

    Raises:
        ValueError: When the window exceeds ``default_days`` without ``unbounded_acknowledged``.

    Examples:
        >>> from datetime import date
        >>> from pathlib import Path
        >>> s, e = iter_backfill_dates(
        ...     date_from="2099-01-01",
        ...     date_to="2099-01-02",
        ...     default_days=400,
        ...     workspace_root=Path("."),
        ...     unbounded_acknowledged=True,
        ... )
        >>> s == date(2099, 1, 1) and e == date(2099, 1, 2)
        True
    """
    today = datetime.now(tz=UTC).date()
    end = today
    if date_to:
        end = date.fromisoformat(date_to)
    if date_from:
        start = date.fromisoformat(date_from)
    else:
        start = end - timedelta(days=max(1, default_days - 1))
    span = (end - start).days + 1
    if span > default_days and not unbounded_acknowledged:
        raise ValueError(
            "backfill window exceeds memory.dreaming.backfill_days — "
            "pass --i-know-the-cost or narrow --from/--to",
        )
    _ = workspace_root
    return start, end
