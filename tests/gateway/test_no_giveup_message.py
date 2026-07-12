"""Wave W3: cascade budget messages must not blame or abandon (D7)."""

from __future__ import annotations

import pytest

from sevn.gateway.agent_turn import (
    _collect_partial_progress,
    _render_no_answer_message,
)
from sevn.gateway.turn_finalizer import TierBAnswerFinalizer
from sevn.prompts.fallbacks import format_cascade_budget_exhausted_message


@pytest.mark.parametrize(
    "partial",
    [None, "Found 3 session files under sessions/"],
)
def test_cascade_budget_message_no_giveup_framing(partial: str | None) -> None:
    """Budget-exhausted copy invites retry and never uses Abandoned/blame wording."""
    msg = format_cascade_budget_exhausted_message(partial)
    lowered = msg.lower()
    assert "abandoned" not in lowered
    assert "taking too long" not in lowered
    assert "didn't finish" not in lowered
    assert "keep going" in lowered or "narrow" in lowered
    if partial:
        assert partial in msg


def test_render_cascade_budget_exhausted_includes_partial() -> None:
    """``_render_no_answer_message`` threads partial progress for cascade exhaustion."""
    partial = "Listed sessions/2026-05-29.jsonl"
    out = _render_no_answer_message("cascade_budget_exhausted", partial_progress=partial)
    assert partial in out
    assert "abandoned" not in out.lower()


def test_collect_partial_progress_from_finalizer() -> None:
    """Streaming placeholder text is recovered for budget-exhausted finalization."""
    from unittest.mock import MagicMock

    adapter = MagicMock()
    router = MagicMock()
    fin = TierBAnswerFinalizer(
        router=router,
        adapter=adapter,
        channel="telegram",
        user_id="1",
        session_id="s1",
        turn_id="t1",
    )
    fin._last_streamed_text = "Partial answer so far."
    assert _collect_partial_progress(finalizer=fin, outcome=None) == "Partial answer so far."
