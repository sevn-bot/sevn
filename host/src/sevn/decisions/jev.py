"""One jev ``system_one`` call for the router questions (D1, D2)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol, cast

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy

from sevn.config import DecisionsSettings, DecisionThresholds, Settings
from sevn.decisions.base import (
    Attempt,
    ContextProfile,
    RouteDecision,
    attempt_for,
    object_dict,
    redact_text,
)
from sevn.decisions.thresholds import jev_accepts
from sevn.domain.routing import OpenAgent, RouterContext
from sevn.log import logger
from sevn.paths import Paths
from sevn.secrets.backends import open_backend
from sevn.secrets.errors import SecretNotFound, SecretsBackendError

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
}
_CONTEXT = {
    "history": {
        "full": "all prior turns",
        "recent": "last three user turns and responses",
        "summary": "task description and last turn",
    },
    "memory": {
        "full": "all available memories",
        "diff": "only changes to memories",
        "skip": "no memory block needed",
    },
    "siblings": {
        "include": "needs other open lanes' titles and status",
        "exclude": "independent of other lanes",
    },
    "attachments": {"include": "keep available attachments", "skip": "text alone suffices"},
}
_ROUTE_TIMEOUT = 3.0
_client: _Jev | None = None


class _Jev(Protocol):
    async def system_one(
        self,
        state: object,
        questions: Mapping[str, object],
        *,
        model: str | None = None,
    ) -> object: ...


async def noul_score(name: str, instructions: str, state: str) -> float | None:
    """Score one noul. ``None`` when jev is unavailable or the call fails."""
    client = await _resolve_client()
    if client is None:
        return None
    try:
        response = await client.system_one(
            redact_text(state),
            {name: Noul(instructions=instructions)},
            model=Settings.load().decisions.jev_model,
        )
    except Exception:  # noqa: BLE001 — jev offline leaves the caller with no score
        logger.warning("jev noul failed")
        return None
    return _noul(response, name)


def use_client(client: _Jev | None) -> None:
    """Install a jev client for later decisions. ``None`` uses the real key."""
    global _client
    _client = client


class JevDecider:
    """Ask jev every router question in one request. Secrets are already redacted."""

    def __init__(self, settings: DecisionsSettings | None = None) -> None:
        self.settings = settings or Settings.load().decisions
        self.calls = 0

    async def attempt(
        self,
        context: RouterContext,
        state: str,
        ruled: RouteDecision | None = None,
    ) -> Attempt | None:
        questions = _questions(context, ruled)
        self.calls = 0
        try:
            async with asyncio.timeout(_ROUTE_TIMEOUT):
                client = await _resolve_client(routing=True)
                if client is None:
                    return None
                self.calls = 1
                try:
                    response = await client.system_one(
                        state, questions, model=self.settings.jev_model
                    )
                finally:
                    if isinstance(client, AsyncTypeSafeClient) and client is not _client:
                        await client.aclose()
        except Exception:  # noqa: BLE001 — key lookup, timeout and service errors fall through
            logger.warning("jev decider failed")
            return None
        route = (
            attempt_for(ruled)
            if ruled
            else _attempt(
                response, self.settings.thresholds, asked_target="message.target_agent" in questions
            )
        )
        if route is None:
            return None
        gates = self.settings.thresholds
        context_gate = gates.intent if gates.context is None else gates.context
        delivery_gate = gates.busy if gates.delivery is None else gates.delivery
        labels: dict[str, str] = {}
        scores: dict[str, float] = {}
        for name, menu in _CONTEXT.items():
            answer = _choice(response, f"context.{name}")
            if answer and answer[0] in menu:
                scores[name] = answer[1]
                if answer[1] >= context_gate:
                    labels[name] = answer[0]
        if labels:
            labels.setdefault("siblings", "exclude")
        decision = with_default_delivery(route.decision, context)
        delivery = _choice(response, "delivery.mode") if "delivery.mode" in questions else None
        target = _busy_target(decision, context)
        if target and delivery and delivery[0] in _BUSY:
            mode, confidence = delivery
            if confidence >= delivery_gate and (target.runtime or context.runtime) == "pydantic_ai":
                decision = replace(decision, delivery_policy=mode)
            decision = replace(decision, delivery_confidence=confidence)
        decision = replace(
            decision,
            context_profile=ContextProfile.model_validate(labels),
            context_confidence=scores,
        )
        return replace(route, decision=decision)


def _busy_target(decision: RouteDecision, context: RouterContext) -> OpenAgent | None:
    if decision.intent not in {"follow_up", "steer"} or decision.ask_user:
        return None
    return next(
        (
            lane
            for lane in context.open_agents
            if lane.id == decision.target_agent_id and (lane.status == "running" or lane.starting)
        ),
        None,
    )


def with_default_delivery(decision: RouteDecision, context: RouterContext) -> RouteDecision:
    if _busy_target(decision, context) is None or decision.delivery_policy is not None:
        return decision
    mode = "steer" if decision.intent == "steer" else "queue"
    return replace(decision, delivery_policy=mode)


def _questions(context: RouterContext, ruled: RouteDecision | None) -> dict[str, Choice]:
    questions = {f"context.{name}": Choice(criteria=menu) for name, menu in _CONTEXT.items()}
    if ruled is None:
        questions["message.intent"] = Choice(criteria=_INTENTS)
        if context.open_agents:
            questions["message.target_agent"] = Choice(
                criteria=_target_criteria(context.open_agents)
            )
        candidates = [
            lane for lane in context.open_agents if lane.status == "running" or lane.starting
        ]
    else:
        target = _busy_target(ruled, context)
        candidates = [target] if target else []
    if any((lane.runtime or context.runtime) == "pydantic_ai" for lane in candidates):
        questions["delivery.mode"] = Choice(criteria=_BUSY)
    return questions


def _target_criteria(agents: list[OpenAgent]) -> dict[str, str]:
    criteria = {agent.id: redact_text(f"{agent.title} {_DASH} {agent.summary}") for agent in agents}
    criteria["none"] = "none"
    return criteria


def _attempt(response: object, gates: DecisionThresholds, *, asked_target: bool) -> Attempt | None:
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
    target_id = None if target_label in (None, "none") else target_label
    decision = RouteDecision(
        intent=intent_label,
        target_agent_id=target_id,
        confidence=intent_confidence,
        path="jev",
    )
    confidences: dict[str, object] = {"intent": intent_confidence}
    if target_confidence is not None:
        confidences["target"] = target_confidence
    return Attempt(
        decision=decision,
        accepted=jev_accepts(
            intent=intent_confidence,
            target=target_confidence,
            busy=None,
            gates=gates,
        ),
        answers={
            "intent": intent_label,
            "target_agent_id": target_id,
            "busy_policy": None,
        },
        confidences=confidences,
    )


def _noul(response: object, name: str) -> float | None:
    nouls = object_dict(getattr(response, "nouls", None))
    if nouls is None:
        return None
    answer = nouls.get(name)
    if answer is None:
        return None
    value = getattr(answer, "noul", None)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


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
    if not 0 <= confidence <= 1:
        return None
    return label, float(confidence)


async def _resolve_client(*, routing: bool = False) -> _Jev | None:
    if _client is not None:
        return _client
    key = await asyncio.to_thread(_typesafe_key)
    if key is None:
        return None
    model = Settings.load().decisions.jev_model
    if routing:
        client = AsyncTypeSafeClient(api_key=key, model=model, retry=RetryPolicy(max_retries=0))
    else:
        client = AsyncTypeSafeClient(api_key=key, model=model)
    return cast("_Jev", client)


def _typesafe_key() -> str | None:
    env = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env != "":
        return env
    try:
        return open_backend(Settings.load(), Paths.from_env()).get("provider/typesafe")
    except SecretNotFound:
        return None
    except SecretsBackendError as exc:
        # A locked or unreachable store means no jev for now; routing falls through.
        logger.warning("jev unavailable: the secret store failed ({})", exc.code)
        return None
