"""Tests for ``sevn.gateway.user_profile`` (`PROBLEMS.md` §4 / Step §4)."""

from __future__ import annotations

import sqlite3

import pytest

from sevn.gateway.user_profile import (
    UserProfile,
    get_user_profile,
    set_user_language_code,
    set_user_timezone,
)
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def test_get_user_profile_returns_utc_default_when_missing() -> None:
    """No row → caller gets a UTC default that is NOT persisted."""
    conn = _memory_conn()
    profile = get_user_profile(conn, channel="telegram", user_id="42")
    assert isinstance(profile, UserProfile)
    assert profile.timezone == "UTC"
    assert profile.language_code is None
    # And the default did not create a row.
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM gateway_user_profile",
        ).fetchone()[0]
        == 0
    )


def test_set_user_timezone_validates_iana_name() -> None:
    """Unknown zones raise ``ValueError`` so bad input never reaches renderers."""
    conn = _memory_conn()
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        set_user_timezone(
            conn,
            channel="telegram",
            user_id="42",
            timezone="Mars/Olympus",
        )


def test_set_user_timezone_rejects_empty_string() -> None:
    conn = _memory_conn()
    with pytest.raises(ValueError, match="non-empty IANA name"):
        set_user_timezone(conn, channel="telegram", user_id="42", timezone="   ")


def test_set_user_timezone_creates_row_then_updates_in_place() -> None:
    """First call inserts; second updates timezone in-place (same PK)."""
    conn = _memory_conn()
    stored = set_user_timezone(
        conn,
        channel="telegram",
        user_id="42",
        timezone="  Europe/Paris  ",
    )
    assert stored == "Europe/Paris"  # trimmed
    profile = get_user_profile(conn, channel="telegram", user_id="42")
    assert profile.timezone == "Europe/Paris"
    assert profile.created_at.endswith("+00:00")
    assert profile.updated_at == profile.created_at
    set_user_timezone(
        conn,
        channel="telegram",
        user_id="42",
        timezone="America/New_York",
    )
    profile2 = get_user_profile(conn, channel="telegram", user_id="42")
    assert profile2.timezone == "America/New_York"
    assert profile2.created_at == profile.created_at  # creation time preserved


def test_set_user_language_code_persists_value() -> None:
    """Language code stamps the row without touching the (default) timezone."""
    conn = _memory_conn()
    set_user_language_code(
        conn,
        channel="telegram",
        user_id="42",
        language_code="fr-FR",
    )
    profile = get_user_profile(conn, channel="telegram", user_id="42")
    assert profile.language_code == "fr-FR"
    assert profile.timezone == "UTC"  # untouched default


def test_set_user_language_code_strips_whitespace_to_none() -> None:
    """Empty/whitespace-only locale persists as ``NULL``."""
    conn = _memory_conn()
    set_user_language_code(
        conn,
        channel="telegram",
        user_id="42",
        language_code="   ",
    )
    profile = get_user_profile(conn, channel="telegram", user_id="42")
    assert profile.language_code is None


def test_timezone_and_language_code_independent() -> None:
    """Setting one doesn't clobber the other on a subsequent update."""
    conn = _memory_conn()
    set_user_timezone(conn, channel="webchat", user_id="u1", timezone="Asia/Tokyo")
    set_user_language_code(
        conn,
        channel="webchat",
        user_id="u1",
        language_code="ja",
    )
    profile = get_user_profile(conn, channel="webchat", user_id="u1")
    assert profile.timezone == "Asia/Tokyo"
    assert profile.language_code == "ja"


def test_profiles_keyed_by_channel_user_pair() -> None:
    """``(telegram, 42)`` and ``(webchat, 42)`` are distinct rows."""
    conn = _memory_conn()
    set_user_timezone(
        conn,
        channel="telegram",
        user_id="42",
        timezone="Europe/Paris",
    )
    set_user_timezone(
        conn,
        channel="webchat",
        user_id="42",
        timezone="America/Los_Angeles",
    )
    tg = get_user_profile(conn, channel="telegram", user_id="42")
    web = get_user_profile(conn, channel="webchat", user_id="42")
    assert tg.timezone == "Europe/Paris"
    assert web.timezone == "America/Los_Angeles"
