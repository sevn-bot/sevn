"""Append-only decision log. The stored state is redacted and truncated (D6)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from sevn.decisions.base import Attempt, stored_state
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.store.db import utcnow
from sevn.store.models import DecisionLog

_POINT = "route"
_tick = 0


def _created_at() -> datetime:
    """Monotonic timestamps so rows from one chain stay in step order."""
    global _tick
    _tick += 1
    return utcnow() + timedelta(microseconds=_tick)


async def record_attempt(state: str, attempt: Attempt) -> None:
    """Insert one row for a step that actually ran."""
    decision = attempt.decision
    outcome = "ask_user" if decision.ask_user else decision.intent
    row = DecisionLog(
        id=new_id("dec_"),
        point=_POINT,
        input_hash=hashlib.sha256(state.encode("utf-8")).hexdigest(),
        state_redacted=stored_state(state),
        answers=attempt.answers,
        confidences=attempt.confidences,
        path=decision.path,
        outcome=outcome,
        corrected_to=None,
        created_at=_created_at(),
    )
    async with open_session() as session:
        session.add(row)
        await session.commit()
