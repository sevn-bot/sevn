"""Five-field cron for routines (plan fleet-dashboards, phase 4).

``minute hour day-of-month month day-of-week``, each a ``*``, a number, a
range ``a-b``, a step ``*/n`` or ``a-b/n``, or a comma list of those. Month
and weekday also take three-letter names. Weekday 0 and 7 are Sunday. When
both day fields are restricted a day matches either one, as in standard cron.
``@hourly``, ``@daily``, ``@weekly``, ``@monthly`` and ``@yearly`` are short
forms.

Times are matched on the wall clock of the routine's timezone. A wall time
that daylight saving skips does not run that day. A wall time that happens
twice runs once, at the first occurrence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_MACROS = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
_MONTHS = {
    name: index
    for index, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_DAYS = {
    name: index for index, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])
}
# Long enough for Feb 29 behind a leap-year gap (eight years at most).
_SEARCH_DAYS = 366 * 9


@dataclass(frozen=True, slots=True)
class CronSpec:
    """A parsed expression. ``weekdays`` uses 0 for Sunday."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    days_any: bool
    weekdays_any: bool


def parse(expr: str) -> CronSpec:
    """Parse ``expr``. ``ValueError`` names what is wrong."""
    text = _MACROS.get(expr.strip().lower(), expr.strip())
    if text.startswith("@"):
        raise ValueError(f"unknown schedule {expr!r}")
    fields = text.split()
    if len(fields) != 5:
        raise ValueError("a schedule has five fields: minute hour day month weekday")
    minute, hour, day, month, weekday = fields
    spec = CronSpec(
        minutes=_field(minute, 0, 59, {}),
        hours=_field(hour, 0, 23, {}),
        days=_field(day, 1, 31, {}),
        months=_field(month, 1, 12, _MONTHS),
        weekdays=frozenset(value % 7 for value in _field(weekday, 0, 7, _DAYS)),
        days_any=day.startswith("*"),
        weekdays_any=weekday.startswith("*"),
    )
    if not _can_match(spec):
        raise ValueError("the schedule never matches a real date")
    return spec


def next_after(spec: CronSpec, after: datetime, tz: ZoneInfo) -> datetime:
    """The first matching time strictly after ``after``, in UTC."""
    if after.tzinfo is None:
        raise ValueError("after needs a timezone")
    local = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    hours = sorted(spec.hours)
    minutes = sorted(spec.minutes)
    day = local.date()
    for _ in range(_SEARCH_DAYS):
        if _day_matches(spec, day):
            first_day = day == local.date()
            for hour in hours:
                if first_day and hour < local.hour:
                    continue
                for minute in minutes:
                    if first_day and hour == local.hour and minute < local.minute:
                        continue
                    found = _wall(day, hour, minute, tz)
                    if found is not None and found > after:
                        return found
        day += timedelta(days=1)
    raise ValueError("no run in the next eight years")


def runs_between(
    spec: CronSpec,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    *,
    limit: int = 10_000,
) -> int:
    """How many runs fall in ``(start, end]``, counting at most ``limit``."""
    count = 0
    cursor = start
    while count < limit:
        found = next_after(spec, cursor, tz)
        if found > end:
            break
        count += 1
        cursor = found
    return count


def _field(raw: str, low: int, high: int, names: dict[str, int]) -> frozenset[int]:
    values: set[int] = set()
    for part in raw.lower().split(","):
        if part == "":
            raise ValueError(f"empty item in {raw!r}")
        base, _, step_text = part.partition("/")
        step = 1
        if step_text != "":
            step = _number(step_text, names={})
            if step <= 0:
                raise ValueError(f"step must be positive in {raw!r}")
        if base == "*":
            start, stop = low, high
        elif "-" in base:
            first, _, last = base.partition("-")
            start, stop = _number(first, names), _number(last, names)
        else:
            start = _number(base, names)
            stop = high if step_text != "" else start
        if start < low or stop > high or start > stop:
            raise ValueError(f"{part!r} is outside {low}-{high}")
        values.update(range(start, stop + 1, step))
    return frozenset(values)


def _number(text: str, names: dict[str, int]) -> int:
    if text in names:
        return names[text]
    if not text.isdigit():
        raise ValueError(f"{text!r} is not a number")
    return int(text)


def _day_matches(spec: CronSpec, day: date) -> bool:
    if day.month not in spec.months:
        return False
    by_date = day.day in spec.days
    by_weekday = (day.weekday() + 1) % 7 in spec.weekdays
    if spec.days_any and spec.weekdays_any:
        return True
    if spec.days_any:
        return by_weekday
    if spec.weekdays_any:
        return by_date
    return by_date or by_weekday


def _can_match(spec: CronSpec) -> bool:
    """False for a date that never exists, such as 30 February."""
    if not spec.days_any and spec.weekdays_any:
        longest = {2: 29, 4: 30, 6: 30, 9: 30, 11: 30}
        return any(day <= longest.get(month, 31) for day in spec.days for month in spec.months)
    return True


def _wall(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime | None:
    """The UTC time of a local wall time, or ``None`` when DST skips it."""
    naive = datetime.combine(day, time(hour, minute))
    first = naive.replace(tzinfo=tz, fold=0)
    back = first.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    if back != naive:
        return None
    return first.astimezone(UTC)
