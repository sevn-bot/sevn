"""Throttle helper tests (`specs/32-memory-honcho.md` §3.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sevn.memory.user_model.throttle import personality_bump_allowed


def test_personality_bump_allowed_first_time() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert personality_bump_allowed(last_bump_at=None, now=now, throttle_minutes=60) is True


def test_personality_bump_respects_throttle() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=30)
    assert personality_bump_allowed(last_bump_at=t0, now=t1, throttle_minutes=60) is False
    t2 = t0 + timedelta(minutes=61)
    assert personality_bump_allowed(last_bump_at=t0, now=t2, throttle_minutes=60) is True
