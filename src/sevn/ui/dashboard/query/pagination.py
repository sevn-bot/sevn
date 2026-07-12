"""Pagination helpers for Mission Control list APIs.

Module: sevn.ui.dashboard.query.pagination
Depends: sevn.config.defaults

Exports:
    PageParams — normalized cursor/limit pair.
    clamp_limit — enforce dashboard max page sizes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sevn.config.defaults import DEFAULT_DASHBOARD_TRACE_LIMIT_MAX


@dataclass(frozen=True)
class PageParams:
    """Normalized cursor pagination parameters.

    Attributes:
        cursor (str | None): Opaque cursor, route-specific.
        limit (int): Clamped page size.
    """

    cursor: str | None
    limit: int


def clamp_limit(
    value: int | str | None,
    *,
    default: int = 50,
    maximum: int = DEFAULT_DASHBOARD_TRACE_LIMIT_MAX,
) -> int:
    """Clamp a query ``limit`` value to dashboard bounds.

    Args:
        value (int | str | None): Raw query value.
        default (int): Value used when missing or invalid.
        maximum (int): Upper bound for the route.

    Returns:
        int: Integer in ``[1, maximum]``.

    Examples:
        >>> clamp_limit(None)
        50
        >>> clamp_limit("1000", maximum=200)
        200
        >>> clamp_limit("-5", default=25)
        25
    """

    try:
        parsed = int(value) if value is not None else int(default)
    except (TypeError, ValueError):
        parsed = int(default)
    if parsed < 1:
        parsed = int(default)
    if parsed > int(maximum):
        return int(maximum)
    return parsed
