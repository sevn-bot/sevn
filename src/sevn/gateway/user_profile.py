"""Repo layer for ``gateway_user_profile`` (`PROBLEMS.md` §4 / Step §4).

Module: sevn.gateway.user_profile
Depends: sqlite3, zoneinfo, datetime

Per-user preferences keyed by ``(channel, user_id)`` — currently
``timezone`` (IANA name) and optional ``language_code``. The row survives
session rotation so users don't re-pick their timezone every conversation.

The IANA name is validated via ``zoneinfo.ZoneInfo`` at set-time so
malformed input never reaches downstream renderers. Default is ``UTC``.

Exports:
    UserProfile — projection dataclass for one row.
    get_user_profile — load by ``(channel, user_id)``, defaults applied.
    set_user_timezone — validate + persist (creates row on first call).
    set_user_language_code — persist a Telegram-style locale.

Examples:
    >>> import inspect
    >>> inspect.isfunction(get_user_profile)
    True
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _utc_now_iso() -> str:
    """Timezone-aware UTC ISO-8601 stamp (mirrors session_manager.

    Returns:
        str: ISO-8601 with explicit ``+00:00`` offset.

    Examples:
        >>> _utc_now_iso().endswith("+00:00")
        True
    """
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class UserProfile:
    """One row from ``gateway_user_profile``.

    Attributes:
        channel (str): Channel key (``telegram``, ``webchat``, …).
        user_id (str): Channel-specific user id.
        timezone (str): IANA timezone name (defaults to ``UTC``).
        language_code (str | None): Telegram-style locale (``en``, ``fr``…).
        created_at (str): UTC ISO-8601 with offset.
        updated_at (str): UTC ISO-8601 with offset.

    Examples:
        >>> from dataclasses import is_dataclass
        >>> is_dataclass(UserProfile)
        True
    """

    channel: str
    user_id: str
    timezone: str
    language_code: str | None
    created_at: str
    updated_at: str


def _validate_iana_timezone(tz: str) -> str:
    """Confirm ``tz`` resolves via :class:`zoneinfo.ZoneInfo`.

    Args:
        tz (str): Candidate IANA name (e.g. ``"Europe/Paris"``).

    Returns:
        str: The same ``tz`` value, trimmed.

    Raises:
        ValueError: When ``tz`` is empty or not a registered IANA name.

    Examples:
        >>> _validate_iana_timezone("UTC")
        'UTC'
        >>> _validate_iana_timezone("  Europe/Paris  ")
        'Europe/Paris'
    """
    stripped = (tz or "").strip()
    if not stripped:
        msg = "timezone must be a non-empty IANA name"
        raise ValueError(msg)
    try:
        ZoneInfo(stripped)
    except ZoneInfoNotFoundError as exc:
        msg = f"unknown IANA timezone: {stripped!r}"
        raise ValueError(msg) from exc
    return stripped


def get_user_profile(
    conn: sqlite3.Connection,
    *,
    channel: str,
    user_id: str,
) -> UserProfile:
    """Load the profile for ``(channel, user_id)`` or return a UTC default.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        channel (str): Channel key.
        user_id (str): Channel-specific user id.

    Returns:
        UserProfile: Hydrated row, or a fresh default with ``timezone="UTC"``
        and ``language_code=None`` when no row exists. The default is NOT
        persisted — callers that need to update fields call
        :func:`set_user_timezone` etc. which upserts.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(get_user_profile)
        True
    """
    row = conn.execute(
        """
        SELECT channel, user_id, timezone, language_code, created_at, updated_at
        FROM gateway_user_profile
        WHERE channel = ? AND user_id = ?
        """,
        (channel, user_id),
    ).fetchone()
    if row is None:
        now = _utc_now_iso()
        return UserProfile(
            channel=channel,
            user_id=user_id,
            timezone="UTC",
            language_code=None,
            created_at=now,
            updated_at=now,
        )
    return UserProfile(
        channel=str(row[0]),
        user_id=str(row[1]),
        timezone=str(row[2]),
        language_code=None if row[3] is None else str(row[3]),
        created_at=str(row[4]),
        updated_at=str(row[5]),
    )


def _upsert_profile(
    conn: sqlite3.Connection,
    *,
    channel: str,
    user_id: str,
    timezone: str | None = None,
    language_code: str | None = None,
) -> None:
    """Insert-or-update a profile row, leaving unset columns alone.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        channel (str): Channel key.
        user_id (str): Channel-specific user id.
        timezone (str | None): When set, validated + persisted.
        language_code (str | None): When set, persisted.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_upsert_profile)
        True
    """
    now = _utc_now_iso()
    existing = conn.execute(
        "SELECT 1 FROM gateway_user_profile WHERE channel = ? AND user_id = ?",
        (channel, user_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO gateway_user_profile (
                channel, user_id, timezone, language_code,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                channel,
                user_id,
                timezone if timezone is not None else "UTC",
                language_code,
                now,
                now,
            ),
        )
    else:
        fields = ["updated_at = ?"]
        params: list[str | None] = [now]
        if timezone is not None:
            fields.append("timezone = ?")
            params.append(timezone)
        if language_code is not None:
            fields.append("language_code = ?")
            params.append(language_code)
        params.extend([channel, user_id])
        conn.execute(
            f"UPDATE gateway_user_profile SET {', '.join(fields)} "  # nosec B608 — fields are a fixed allowlist; values bind via ?
            "WHERE channel = ? AND user_id = ?",
            params,
        )
    conn.commit()


def set_user_timezone(
    conn: sqlite3.Connection,
    *,
    channel: str,
    user_id: str,
    timezone: str,
) -> str:
    """Validate + persist a user's IANA timezone.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        channel (str): Channel key.
        user_id (str): Channel-specific user id.
        timezone (str): Candidate IANA name (``"Europe/Paris"``,
            ``"America/New_York"``, ``"UTC"``…).

    Returns:
        str: The validated + stored IANA name (trimmed).

    Raises:
        ValueError: When ``timezone`` is empty or not a recognised IANA name.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(set_user_timezone)
        True
    """
    validated = _validate_iana_timezone(timezone)
    _upsert_profile(conn, channel=channel, user_id=user_id, timezone=validated)
    return validated


def set_user_language_code(
    conn: sqlite3.Connection,
    *,
    channel: str,
    user_id: str,
    language_code: str,
) -> None:
    """Persist a Telegram-style language code (``en``, ``fr-FR``…).

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        channel (str): Channel key.
        user_id (str): Channel-specific user id.
        language_code (str): IETF BCP-47-ish locale string.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(set_user_language_code)
        True
    """
    _upsert_profile(
        conn,
        channel=channel,
        user_id=user_id,
        language_code=language_code.strip() or None,
    )


__all__ = [
    "UserProfile",
    "get_user_profile",
    "set_user_language_code",
    "set_user_timezone",
]
