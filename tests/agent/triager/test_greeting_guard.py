"""RED suite for greeting path scope guard (D14; green after W8)."""

from __future__ import annotations

import pytest

from sevn.agent.triager.routing_policy import is_strict_greeting_message, try_fast_greeting_triage
from sevn.agent.triager.run import _apply_tier_a_scope_guard


@pytest.mark.parametrize(
    "message",
    [
        "hello",
        "hi",
        "yoyoyyo",
        "helloo",
    ],
)
@pytest.mark.xfail(reason="green after W8: GREETING stays in strict-greeting scope", strict=False)
def test_greeting_intent_yields_strict_first_message(message: str) -> None:
    """D14: GREETING intents produce a strict-greeting-shaped ``first_message``."""
    result = try_fast_greeting_triage(current_message=message, turn_id="turn-greet")
    assert result is not None
    assert is_strict_greeting_message(result.first_message)


@pytest.mark.parametrize(
    "message",
    [
        "hello",
        "hi",
        "yoyoyyo",
        "helloo",
    ],
)
@pytest.mark.xfail(reason="green after W8: greeting guard no longer trips", strict=False)
def test_greeting_path_does_not_trip_triager_overstepped(message: str) -> None:
    """D14: strict greeting replies must not fire ``triager_overstepped``."""
    result = try_fast_greeting_triage(current_message=message, turn_id="turn-scope")
    assert result is not None
    adjusted, overstepped = _apply_tier_a_scope_guard(
        result,
        current_message=message,
        turn_id="turn-scope",
    )
    assert overstepped is False
    assert is_strict_greeting_message(adjusted.first_message)


def test_yoyoyyo_is_not_strict_greeting_today() -> None:
    """Baseline from session analysis: ``yoyoyyo`` is not yet a strict greeting token."""
    assert is_strict_greeting_message("yoyoyyo") is False
