"""Five-field cron, evaluated in the routine's timezone (phase 4)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest


def _next(expr: str, after: str, tz: str = "UTC") -> str:
    from sevn.domain.cron import next_after, parse

    found = next_after(parse(expr), datetime.fromisoformat(after), ZoneInfo(tz))
    assert found.tzinfo is not None
    return found.astimezone(UTC).isoformat()


@pytest.mark.parametrize(
    ("expr", "after", "expected"),
    [
        ("* * * * *", "2026-11-01T10:00:30+00:00", "2026-11-01T10:01:00+00:00"),
        ("0 * * * *", "2026-11-01T10:00:00+00:00", "2026-11-01T11:00:00+00:00"),
        ("*/15 * * * *", "2026-11-01T10:07:00+00:00", "2026-11-01T10:15:00+00:00"),
        ("0 9 * * 1-5", "2026-10-31T12:00:00+00:00", "2026-11-02T09:00:00+00:00"),
        ("0 9 * * mon-fri", "2026-10-31T12:00:00+00:00", "2026-11-02T09:00:00+00:00"),
        ("30 8 1 * *", "2026-11-01T09:00:00+00:00", "2026-12-01T08:30:00+00:00"),
        ("0 0 29 2 *", "2026-03-01T00:00:00+00:00", "2028-02-29T00:00:00+00:00"),
        ("0 12 * jan,jul *", "2026-11-01T00:00:00+00:00", "2027-01-01T12:00:00+00:00"),
        ("0 6 * * 0", "2026-11-01T07:00:00+00:00", "2026-11-08T06:00:00+00:00"),
        ("0 6 * * 7", "2026-11-01T07:00:00+00:00", "2026-11-08T06:00:00+00:00"),
        ("@daily", "2026-11-01T10:00:00+00:00", "2026-11-02T00:00:00+00:00"),
        ("@hourly", "2026-11-01T10:59:00+00:00", "2026-11-01T11:00:00+00:00"),
        ("0 10-12/2 * * *", "2026-11-01T10:30:00+00:00", "2026-11-01T12:00:00+00:00"),
    ],
)
def test_next_after_in_utc(expr: str, after: str, expected: str) -> None:
    assert _next(expr, after) == expected


def test_day_of_month_or_day_of_week() -> None:
    # Both restricted: either may match, as in standard cron.
    # Nov 2026: the 13th is a Friday, the first Monday is the 2nd.
    assert _next("0 0 13 * 1", "2026-11-01T00:00:00+00:00") == "2026-11-02T00:00:00+00:00"
    assert _next("0 0 13 * 1", "2026-11-12T00:00:00+00:00") == "2026-11-13T00:00:00+00:00"


def test_evaluated_in_the_routine_timezone() -> None:
    # 09:00 in Amsterdam on Monday 2 Nov 2026 (CET, +01:00) is 08:00 UTC.
    assert (
        _next("0 9 * * 1", "2026-11-01T12:00:00+00:00", "Europe/Amsterdam")
        == "2026-11-02T08:00:00+00:00"
    )


def test_a_time_skipped_by_dst_does_not_run_that_day() -> None:
    # Europe/Amsterdam skips 02:00-03:00 on 29 Mar 2026.
    assert (
        _next("30 2 * * *", "2026-03-28T12:00:00+00:00", "Europe/Amsterdam")
        == "2026-03-30T00:30:00+00:00"
    )


def test_a_repeated_dst_hour_runs_once() -> None:
    # 02:30 happens twice on 25 Oct 2026 in Amsterdam; run the first one.
    first = _next("30 2 * * *", "2026-10-24T12:00:00+00:00", "Europe/Amsterdam")
    assert first == "2026-10-25T00:30:00+00:00"
    assert _next("30 2 * * *", first, "Europe/Amsterdam") == "2026-10-26T01:30:00+00:00"


def test_runs_between_counts_within_a_window() -> None:
    from sevn.domain.cron import parse, runs_between

    start = datetime.fromisoformat("2026-11-01T00:00:00+00:00")
    end = datetime.fromisoformat("2026-11-08T00:00:00+00:00")
    assert runs_between(parse("0 9 * * 1-5"), start, end, ZoneInfo("UTC")) == 5
    assert runs_between(parse("0 */2 * * *"), start, end, ZoneInfo("UTC")) == 84
    assert runs_between(parse("* * * * *"), start, end, ZoneInfo("UTC"), limit=100) == 100


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "a * * * *",
        "@sometimes",
    ],
)
def test_bad_expressions_are_refused(expr: str) -> None:
    from sevn.domain.cron import parse

    with pytest.raises(ValueError):
        parse(expr)


def test_never_matching_schedule_is_refused() -> None:
    from sevn.domain.cron import parse

    with pytest.raises(ValueError):
        parse("0 0 30 2 *")
