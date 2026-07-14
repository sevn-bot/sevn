"""Render-time timezone conversion for outbound payloads (`PROBLEMS.md` §4).

Module: sevn.gateway.util.timestamps
Depends: zoneinfo, datetime

Storage canonicalises every persisted timestamp to UTC with explicit
``+00:00`` offset (`PROBLEMS.md` §4, Step 8). Per-channel renderers call
:func:`to_user_tz` at display time to convert into the user's local zone
(loaded from ``gateway_user_profile``). The helper is pure — it does not
touch SQLite — so it stays cheap to call inside any render loop.

Exports:
    to_user_tz — convert a UTC-with-offset ISO-8601 string into the
        user's IANA zone, returning ``HH:MM:SS`` plus a short abbreviation.
    operator_local_date_iso — operator-local calendar date ``YYYY-MM-DD``.
    resolve_time_range — turn a relative token (``"yesterday"``) or explicit
        ISO ``since``/``until`` into naive-UTC ISO bounds for querying
        persisted ``created_at`` columns.

Examples:
    >>> to_user_tz("2026-05-27T10:00:00+00:00", "UTC")
    '10:00:00 UTC'
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def to_user_tz(iso_utc_with_offset: str, user_tz: str) -> str:
    """Convert a UTC-with-offset timestamp into the user's local zone.

    Args:
        iso_utc_with_offset (str): ISO-8601 timestamp with an explicit
            offset, e.g. ``"2026-05-27T10:00:00+00:00"``. Naive timestamps
            (no offset) are treated as UTC for backward compatibility with
            pre-§4 rows that were stored as naive.
        user_tz (str): IANA timezone name from ``gateway_user_profile``.
            Falls back to ``UTC`` when the name doesn't resolve so a
            malformed config never crashes a renderer.

    Returns:
        str: ``HH:MM:SS <ABBR>`` where ``<ABBR>`` is the zone abbreviation
        (``UTC``, ``CET``, ``EST``…). On malformed input the function
        returns the original timestamp string unchanged — callers can
        treat that as "render best-effort" without special-casing errors.

    Examples:
        >>> to_user_tz("2026-05-27T10:00:00+00:00", "UTC")
        '10:00:00 UTC'

        Naive input is treated as UTC for backward compatibility.

        >>> to_user_tz("2026-05-27T10:00:00", "UTC")
        '10:00:00 UTC'

        Unknown zone falls back to UTC (best-effort).

        >>> to_user_tz("2026-05-27T10:00:00+00:00", "Mars/Olympus")
        '10:00:00 UTC'

        Malformed input round-trips unchanged.

        >>> to_user_tz("not-a-timestamp", "UTC")
        'not-a-timestamp'
    """
    try:
        ts = datetime.fromisoformat(iso_utc_with_offset)
    except ValueError:
        return iso_utc_with_offset
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    try:
        target = ZoneInfo(user_tz)
    except ZoneInfoNotFoundError:
        target = ZoneInfo("UTC")
    local = ts.astimezone(target)
    abbr = local.strftime("%Z") or user_tz
    return f"{local.strftime('%H:%M:%S')} {abbr}"


def operator_local_date_iso(user_tz: str = "UTC") -> str:
    """Return the operator's local calendar date as ``YYYY-MM-DD``.

    Args:
        user_tz (str): IANA timezone name. Falls back to UTC when unknown.

    Returns:
        str: ISO calendar date in the operator's zone.

    Examples:
        >>> operator_local_date_iso("UTC")  # doctest: +SKIP
        '2026-06-10'
    """
    try:
        target = ZoneInfo(user_tz)
    except ZoneInfoNotFoundError:
        target = ZoneInfo("UTC")
    return datetime.now(tz=target).date().isoformat()


def _safe_zone(tz: str) -> ZoneInfo:
    """Return ``ZoneInfo(tz)`` or the UTC zone when ``tz`` does not resolve.

    Args:
        tz (str): IANA timezone name.

    Returns:
        ZoneInfo: The requested zone, or UTC on an unknown/invalid name.

    Examples:
        >>> _safe_zone("Mars/Olympus").key
        'UTC'
    """
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _to_naive_utc_iso(dt_local: datetime) -> str:
    """Convert a tz-aware datetime to a naive-UTC ISO string.

    Persisted ``created_at`` columns store naive UTC (`sessions_query.py`), so
    bounds must match that shape for correct lexicographic SQL comparison.

    Args:
        dt_local (datetime): Timezone-aware datetime to convert.

    Returns:
        str: Naive-UTC ISO-8601 string (no offset).

    Examples:
        >>> from zoneinfo import ZoneInfo
        >>> _to_naive_utc_iso(datetime(2026, 7, 2, 2, 0, tzinfo=ZoneInfo("Europe/Paris")))
        '2026-07-02T00:00:00'
    """
    return dt_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat()


def _relative_local_range(token: str, today: date) -> tuple[date, date]:
    """Map a relative token to a ``[start_date, end_date_exclusive)`` day range.

    Args:
        token (str): Normalised token (lowercase, ``_``-separated).
        today (date): Operator-local calendar date "now" falls on.

    Returns:
        tuple[date, date]: Inclusive start day and exclusive end day.

    Raises:
        ValueError: When ``token`` is not a recognised relative range.

    Examples:
        >>> _relative_local_range("yesterday", date(2026, 7, 3))
        (datetime.date(2026, 7, 2), datetime.date(2026, 7, 3))
    """
    tomorrow = today + timedelta(days=1)
    if token == "today":  # nosec B105 — relative-date token label, not a secret
        return today, tomorrow
    if token == "yesterday":  # nosec B105 — relative-date token label, not a secret
        return today - timedelta(days=1), today
    if token in {"last_7_days", "past_7_days", "7d"}:
        return today - timedelta(days=6), tomorrow
    if token in {"last_30_days", "past_30_days", "30d"}:
        return today - timedelta(days=29), tomorrow
    if token == "this_week":  # nosec B105 — relative-date token label (week starts Monday)
        return today - timedelta(days=today.weekday()), tomorrow
    if token == "last_week":  # nosec B105 — relative-date token label, not a secret
        this_monday = today - timedelta(days=today.weekday())
        return this_monday - timedelta(days=7), this_monday
    if token == "this_month":  # nosec B105 — relative-date token label, not a secret
        return today.replace(day=1), tomorrow
    if token == "last_month":  # nosec B105 — relative-date token label, not a secret
        first_this = today.replace(day=1)
        last_month_end = first_this  # exclusive
        prev = (first_this - timedelta(days=1)).replace(day=1)
        return prev, last_month_end
    msg = (
        f"unknown relative range {token!r}; use one of: today, yesterday, "
        "last_7_days, last_30_days, this_week, last_week, this_month, last_month "
        "(or explicit since/until dates)"
    )
    raise ValueError(msg)


def _parse_bound(value: str, *, zone: ZoneInfo, end: bool) -> datetime:
    """Parse a ``since``/``until`` bound into a tz-aware datetime.

    Accepts a bare ``YYYY-MM-DD`` (interpreted as the local day; ``end=True``
    rolls to the next day's start so the whole day is included) or a full ISO
    timestamp (naive is treated as local).

    Args:
        value (str): User-supplied date or datetime string.
        zone (ZoneInfo): Operator-local zone.
        end (bool): When ``True`` and ``value`` is a bare date, return the
            exclusive next-day start instead of that day's start.

    Returns:
        datetime: Timezone-aware bound.

    Raises:
        ValueError: When ``value`` is neither a date nor an ISO timestamp.

    Examples:
        >>> from zoneinfo import ZoneInfo
        >>> _parse_bound("2026-07-02", zone=ZoneInfo("UTC"), end=True).isoformat()
        '2026-07-03T00:00:00+00:00'
    """
    text = value.strip()
    try:
        day = date.fromisoformat(text)
    except ValueError:
        day = None
    if day is not None:
        anchor = day + timedelta(days=1) if end else day
        return datetime.combine(anchor, time.min, tzinfo=zone)
    try:
        ts = datetime.fromisoformat(text)
    except ValueError as exc:
        msg = f"invalid date/time {value!r}; use YYYY-MM-DD or ISO-8601"
        raise ValueError(msg) from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=zone)
    return ts


def resolve_time_range(
    when: str | None = None,
    since: str | None = None,
    until: str | None = None,
    *,
    tz: str = "UTC",
    now: datetime | None = None,
) -> tuple[str | None, str | None]:
    """Resolve relative/explicit date inputs into naive-UTC ISO query bounds.

    The returned bounds are half-open — ``start`` inclusive, ``end`` exclusive —
    and formatted as naive UTC ISO strings so they compare lexicographically
    against persisted ``created_at`` columns (``WHERE created_at >= start AND
    created_at < end``). Relative tokens are resolved against the operator's
    local calendar day, so ``"yesterday"`` covers the correct UTC window even
    across the local↔UTC offset.

    Args:
        when (str | None): Relative token (``"today"``, ``"yesterday"``,
            ``"last_7_days"``, ``"this_week"``, …). Spaces/hyphens are accepted
            (``"last week"``). Sets both bounds; ignored when ``None``.
        since (str | None): Lower bound (inclusive) — ``YYYY-MM-DD`` or ISO.
        until (str | None): Upper bound — ``YYYY-MM-DD`` (whole day included)
            or ISO (exclusive).
        tz (str): Operator IANA timezone; unknown names fall back to UTC.
        now (datetime | None): Injected "now" for tests; defaults to real now.

    Returns:
        tuple[str | None, str | None]: ``(start_iso, end_iso)``; each element is
        ``None`` when that bound is unconstrained. ``(None, None)`` means no
        inputs were given (callers should skip date filtering).

    Raises:
        ValueError: When a token or explicit bound cannot be parsed, or when
            ``when`` is combined with ``since``/``until``.

    Examples:
        >>> ref = datetime(2026, 7, 3, 9, 0, tzinfo=ZoneInfo("UTC"))
        >>> resolve_time_range("yesterday", tz="UTC", now=ref)
        ('2026-07-02T00:00:00', '2026-07-03T00:00:00')
        >>> resolve_time_range(since="2026-07-01", until="2026-07-01", tz="UTC")
        ('2026-07-01T00:00:00', '2026-07-02T00:00:00')
        >>> resolve_time_range(tz="UTC")
        (None, None)
    """
    zone = _safe_zone(tz)
    if when is not None:
        token = when.strip().lower().replace(" ", "_").replace("-", "_")
        if not token:
            return None, None
        if since is not None or until is not None:
            msg = "pass either `when` or `since`/`until`, not both"
            raise ValueError(msg)
        ref = now.astimezone(zone) if now is not None else datetime.now(tz=zone)
        start_day, end_day = _relative_local_range(token, ref.date())
        start = datetime.combine(start_day, time.min, tzinfo=zone)
        end = datetime.combine(end_day, time.min, tzinfo=zone)
        return _to_naive_utc_iso(start), _to_naive_utc_iso(end)
    start_iso = None
    end_iso = None
    if since is not None and since.strip():
        start_iso = _to_naive_utc_iso(_parse_bound(since, zone=zone, end=False))
    if until is not None and until.strip():
        end_iso = _to_naive_utc_iso(_parse_bound(until, zone=zone, end=True))
    return start_iso, end_iso


__all__ = ["operator_local_date_iso", "resolve_time_range", "to_user_tz"]
