"""One jev ``system_one`` call for the router questions (D1, D2)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Protocol, cast

from typesafe_sdk import AsyncTypeSafeClient, Choice

from sevn.config import Settings
from sevn.decisions.base import Attempt, RouteDecision, object_dict, redact_text
from sevn.decisions.thresholds import jev_accepts
from sevn.domain.routing import OpenAgent, RouterContext
from sevn.log import logger
from sevn.paths import Paths
from sevn.secrets.backends import open_backend
from sevn.secrets.errors import SecretNotFound

_DASH = "\u2014"
_INTENTS: dict[str, str] = {
    "new_request": "start a new task",
    "follow_up": "continue an open agent",
    "steer": "change what a running agent is doing",
    "answer": "answer a pending question",
    "cancel": "stop an agent",
    "chit_chat": "a short reply with no task",
}
_BUSY: dict[str, str] = {
    "queue": "wait until the running turn finishes",
    "steer": "inject this message into the running turn",
    "interrupt": "stop the running turn and handle this message",
}
_client: _Jev | None = None


class _Jev(Protocol):
    async def system_one(
        self,
        state: object,
        questions: Mapping[str, object],
        *,
        model: str | None = None,
    ) -> object: ...


def use_client(client: _Jev | None) -> None:
    """Install a jev client for later decisions. ``None`` uses the real key."""
    global _client
    _client = client


class JevDecider:
    """Ask jev every router question in one request. Secrets are already redacted."""

    async def attempt(self, context: RouterContext, state: str) -> Attempt | None:
        client = await _resolve_client()
        if client is None:
            return None
        questions = _questions(context)
        model = Settings.load().decisions.jev_model
        try:
            response = await client.system_one(state, questions, model=model)
        except Exception:  # noqa: BLE001 — jev offline falls through
            logger.warning("jev decider failed")
            return None
        return _attempt(
            response,
            asked_target="message.target_agent" in questions,
            asked_busy="busy.policy" in questions,
        )


def _questions(context: RouterContext) -> dict[str, Choice]:
    questions: dict[str, Choice] = {"message.intent": Choice(criteria=_INTENTS)}
    if context.open_agents:
        questions["message.target_agent"] = Choice(criteria=_target_criteria(context.open_agents))
    if any(agent.status == "running" for agent in context.open_agents):
        questions["busy.policy"] = Choice(criteria=_BUSY)
    return questions


def _target_criteria(agents: list[OpenAgent]) -> dict[str, str]:
    criteria = {agent.id: redact_text(f"{agent.title} {_DASH} {agent.summary}") for agent in agents}
    criteria["none"] = "none"
    return criteria


def _attempt(response: object, *, asked_target: bool, asked_busy: bool) -> Attempt | None:
    intent = _choice(response, "message.intent")
    if intent is None:
        return None
    intent_label, intent_confidence = intent
    target_label: str | None = None
    target_confidence: float | None = None
    if asked_target:
        target = _choice(response, "message.target_agent")
        if target is None:
            target_label, target_confidence = "none", 0.0
        else:
            target_label, target_confidence = target
    busy_label: str | None = None
    busy_confidence: float | None = None
    if asked_busy:
        busy = _choice(response, "busy.policy")
        # An unscripted question comes back at 0. It must not veto a confident intent.
        if busy is None or busy[1] == 0.0:
            busy_label, busy_confidence = None, None
        else:
            busy_label, busy_confidence = busy
    target_id = None if target_label in (None, "none") else target_label
    decision = RouteDecision(
        intent=intent_label,
        target_agent_id=target_id,
        confidence=intent_confidence,
        path="jev",
        busy_policy=busy_label,
    )
    confidences: dict[str, object] = {"intent": intent_confidence}
    if target_confidence is not None:
        confidences["target"] = target_confidence
    if busy_confidence is not None:
        confidences["busy"] = busy_confidence
    return Attempt(
        decision=decision,
        accepted=jev_accepts(
            intent=intent_confidence,
            target=target_confidence,
            busy=busy_confidence,
        ),
        answers={
            "intent": intent_label,
            "target_agent_id": target_id,
            "busy_policy": busy_label,
        },
        confidences=confidences,
    )


def _choice(response: object, name: str) -> tuple[str, float] | None:
    choices = object_dict(getattr(response, "choices", None))
    if choices is None:
        return None
    answer = choices.get(name)
    if answer is None:
        return None
    label = getattr(answer, "choice", None)
    confidence = getattr(answer, "confidence", None)
    if not isinstance(label, str) or isinstance(confidence, bool):
        return None
    if not isinstance(confidence, int | float):
        return None
    return label, float(confidence)


async def _resolve_client() -> _Jev | None:
    if _client is not None:
        return _client
    key = await asyncio.to_thread(_typesafe_key)
    if key is None:
        return None
    client = AsyncTypeSafeClient(api_key=key, model=Settings.load().decisions.jev_model)
    return cast("_Jev", client)


def _typesafe_key() -> str | None:
    env = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env != "":
        return env
    try:
        return open_backend(Settings.load(), Paths.from_env()).get("provider/typesafe")
    except SecretNotFound:
        return None
