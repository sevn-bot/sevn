"""Tests for ``sevn.gateway.util.timestamps`` (`PROBLEMS.md` §4 / Step §4)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sevn.gateway.util.timestamps import resolve_time_range, to_user_tz


def test_utc_with_offset_renders_in_utc() -> None:
    """The base case — UTC in, UTC out."""
    assert to_user_tz("2026-05-27T10:00:00+00:00", "UTC") == "10:00:00 UTC"


def test_utc_renders_in_paris() -> None:
    """Europe/Paris in May is CEST (UTC+2)."""
    out = to_user_tz("2026-05-27T10:00:00+00:00", "Europe/Paris")
    assert out.startswith("12:00:00 ")
    # Abbreviation is CEST in summer; allow both for cross-platform safety.
    assert "CEST" in out or "CET" in out or "+02" in out


def test_utc_renders_in_new_york() -> None:
    """America/New_York in May is EDT (UTC-4)."""
    out = to_user_tz("2026-05-27T10:00:00+00:00", "America/New_York")
    assert out.startswith("06:00:00 ")


def test_naive_input_treated_as_utc() -> None:
    """Pre-§4 rows stored as naive timestamps fall back to UTC."""
    assert to_user_tz("2026-05-27T10:00:00", "UTC") == "10:00:00 UTC"


def test_dst_boundary_correctness() -> None:
    """Confirm DST handling — Paris is CET (UTC+1) in January."""
    out = to_user_tz("2026-01-15T10:00:00+00:00", "Europe/Paris")
    assert out.startswith("11:00:00 ")


def test_unknown_zone_falls_back_to_utc() -> None:
    """Bad IANA name doesn't crash — caller gets the UTC render instead."""
    assert to_user_tz("2026-05-27T10:00:00+00:00", "Mars/Olympus") == "10:00:00 UTC"


def test_malformed_input_passes_through_unchanged() -> None:
    """Best-effort: caller sees the original string when parsing fails."""
    assert to_user_tz("not-a-timestamp", "UTC") == "not-a-timestamp"


def test_explicit_offset_other_than_utc_is_respected() -> None:
    """Input already in CET (UTC+1) renders to America/Los_Angeles (UTC-7 in May)."""
    # ``10:00:00+01:00`` == ``09:00:00`` UTC → ``02:00:00`` LA (UTC-7 DST).
    out = to_user_tz("2026-05-27T10:00:00+01:00", "America/Los_Angeles")
    assert out.startswith("02:00:00 ")


def test_seconds_are_always_rendered() -> None:
    """Format is ``HH:MM:SS`` (Webchat needs seconds — `PROBLEMS.md` §4)."""
    out = to_user_tz("2026-05-27T10:30:45+00:00", "UTC")
    assert out == "10:30:45 UTC"


# --- resolve_time_range ------------------------------------------------------

_REF = datetime(2026, 7, 3, 9, 0, tzinfo=ZoneInfo("UTC"))  # Friday


def test_resolve_no_inputs_returns_none_pair() -> None:
    assert resolve_time_range(tz="UTC") == (None, None)


def test_resolve_yesterday_utc() -> None:
    assert resolve_time_range("yesterday", tz="UTC", now=_REF) == (
        "2026-07-02T00:00:00",
        "2026-07-03T00:00:00",
    )


def test_resolve_today_utc() -> None:
    assert resolve_time_range("today", tz="UTC", now=_REF) == (
        "2026-07-03T00:00:00",
        "2026-07-04T00:00:00",
    )


def test_resolve_relative_token_normalises_spaces_and_hyphens() -> None:
    assert resolve_time_range("Last 7 Days", tz="UTC", now=_REF) == (
        "2026-06-27T00:00:00",
        "2026-07-04T00:00:00",
    )


def test_resolve_this_week_starts_monday() -> None:
    # 2026-07-03 is a Friday → this week starts Monday 2026-06-29.
    start, end = resolve_time_range("this_week", tz="UTC", now=_REF)
    assert start == "2026-06-29T00:00:00"
    assert end == "2026-07-04T00:00:00"


def test_resolve_yesterday_local_tz_shifts_utc_window() -> None:
    # In Europe/Paris (UTC+2 in July) "yesterday" (2026-07-02 local) maps to a
    # UTC window offset by two hours, proving local-day resolution.
    start, end = resolve_time_range("yesterday", tz="Europe/Paris", now=_REF)
    assert start == "2026-07-01T22:00:00"
    assert end == "2026-07-02T22:00:00"


def test_resolve_explicit_since_until_dates_are_inclusive() -> None:
    assert resolve_time_range(since="2026-07-01", until="2026-07-01", tz="UTC") == (
        "2026-07-01T00:00:00",
        "2026-07-02T00:00:00",
    )


def test_resolve_since_only_leaves_end_open() -> None:
    assert resolve_time_range(since="2026-07-01", tz="UTC") == ("2026-07-01T00:00:00", None)


def test_resolve_iso_datetime_bound_preserved() -> None:
    start, _ = resolve_time_range(since="2026-07-01T13:30:00", tz="UTC")
    assert start == "2026-07-01T13:30:00"


def test_resolve_unknown_token_raises() -> None:
    with pytest.raises(ValueError, match="unknown relative range"):
        resolve_time_range("someday", tz="UTC", now=_REF)


def test_resolve_when_with_since_raises() -> None:
    with pytest.raises(ValueError, match=r"either .when. or .since"):
        resolve_time_range("today", since="2026-07-01", tz="UTC", now=_REF)


def test_resolve_bad_bound_raises() -> None:
    with pytest.raises(ValueError, match="invalid date/time"):
        resolve_time_range(since="not-a-date", tz="UTC")


def test_resolve_unknown_tz_falls_back_to_utc() -> None:
    assert resolve_time_range("yesterday", tz="Mars/Olympus", now=_REF) == (
        "2026-07-02T00:00:00",
        "2026-07-03T00:00:00",
    )
