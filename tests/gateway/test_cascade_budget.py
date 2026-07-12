"""Unit tests for ``CascadeBudget`` wall-clock accounting."""

from __future__ import annotations

import pytest

from sevn.gateway.cascade_budget import CascadeBudget


@pytest.fixture
def clock_ns() -> dict[str, int]:
    return {"ns": 0}


def test_fresh_budget_has_full_cap(clock_ns: dict[str, int]) -> None:
    budget = CascadeBudget(180.0, clock_ns=lambda: clock_ns["ns"])
    assert budget.remaining_s() == 180.0
    assert budget.exhausted() is False


def test_partial_elapsed_reduces_remaining(clock_ns: dict[str, int]) -> None:
    budget = CascadeBudget(100.0, clock_ns=lambda: clock_ns["ns"])
    clock_ns["ns"] = 25_000_000_000
    assert budget.remaining_s() == 75.0
    assert budget.exhausted() is False


def test_past_cap_is_exhausted_with_zero_floor(clock_ns: dict[str, int]) -> None:
    budget = CascadeBudget(10.0, clock_ns=lambda: clock_ns["ns"])
    clock_ns["ns"] = 15_000_000_000
    assert budget.exhausted() is True
    assert budget.remaining_s() == 0.0


def test_clamp_returns_phase_timeout_when_budget_ample(clock_ns: dict[str, int]) -> None:
    budget = CascadeBudget(300.0, clock_ns=lambda: clock_ns["ns"])
    assert budget.clamp(180.0) == 180.0


def test_clamp_returns_remaining_when_tighter_than_phase(clock_ns: dict[str, int]) -> None:
    budget = CascadeBudget(300.0, clock_ns=lambda: clock_ns["ns"])
    clock_ns["ns"] = 290_000_000_000
    assert budget.remaining_s() == 10.0
    assert budget.clamp(180.0) == 10.0


def test_zero_cap_is_immediately_exhausted(clock_ns: dict[str, int]) -> None:
    budget = CascadeBudget(0.0, clock_ns=lambda: clock_ns["ns"])
    assert budget.exhausted() is True
    assert budget.clamp(180.0) == 0.0


def test_legacy_closure_parity(clock_ns: dict[str, int]) -> None:
    cases = [
        (270.0, 0),
        (270.0, 90_000_000_000),
        (30.0, 45_000_000_000),
    ]
    for cap_s, advance_ns in cases:
        clock_ns["ns"] = 0
        budget = CascadeBudget(cap_s, clock_ns=lambda: clock_ns["ns"])
        clock_ns["ns"] = advance_ns
        elapsed = advance_ns / 1e9
        expected = max(0.0, cap_s - elapsed)
        assert budget.remaining_s() == expected
