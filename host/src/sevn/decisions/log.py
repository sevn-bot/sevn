"""Append-only decision log. The stored state is redacted and truncated (D6)."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from datetime import datetime, timedelta

from sevn.decisions.base import Attempt, stored_state
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.observability.spans import route_span
from sevn.store.db import utcnow
from sevn.store.models import DecisionLog

_POINT = "route"
_tick = 0
_last_id: ContextVar[str | None] = ContextVar("sevn_decision_id", default=None)


def _created_at() -> datetime:
    """Monotonic timestamps so rows from one chain stay in step order."""
    global _tick
    _tick += 1
    return utcnow() + timedelta(microseconds=_tick)


def last_decision_id() -> str | None:
    """The decision row recorded in this task, if a step has run."""
    return _last_id.get()


async def mark_corrected(decision_id: str | None, agent_id: str) -> None:
    """Record where the user moved a routed message (D7)."""
    if decision_id is None:
        return
    async with open_session() as session:
        row = await session.get(DecisionLog, decision_id)
        if row is None:
            return
        row.corrected_to = agent_id
        await session.commit()


async def record_attempt(
    state: str, attempt: Attempt, *, calls: int = 0, elapsed: float = 0.0, p95: float = 0.0
) -> None:
    """Insert one row for a step that actually ran."""
    decision = attempt.decision
    outcome = "ask_user" if decision.ask_user else decision.intent
    row_id = new_id("dec_")
    _last_id.set(row_id)
    row = DecisionLog(
        id=row_id,
        point=_POINT,
        input_hash=hashlib.sha256(state.encode("utf-8")).hexdigest(),
        state_redacted=stored_state(state),
        answers={
            **attempt.answers,
            "context_profile": decision.context_profile.model_dump(),
            "delivery_policy": decision.delivery_policy,
            "steer_injected": False,
        },
        confidences={
            **attempt.confidences,
            "delivery_confidence": decision.delivery_confidence,
            "context_confidence": decision.context_confidence,
        },
        path=decision.path,
        outcome=outcome,
        corrected_to=None,
        created_at=_created_at(),
    )
    with route_span(
        point=_POINT,
        path=decision.path,
        confidence=decision.confidence,
        accepted=attempt.accepted,
        decision_id=row_id,
    ) as span:
        if attempt.accepted:
            span.set_attribute("sevn.routing.jev_calls", calls)
            span.set_attribute("sevn.routing.latency_ms", elapsed)
            span.set_attribute("sevn.routing.latency_p95_ms", p95)
        async with open_session() as session:
            session.add(row)
            await session.commit()
