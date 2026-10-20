"""Decider results and redaction of state before it leaves the host."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from sevn.log import redact

if TYPE_CHECKING:
    from loguru import Record

_STATE_LIMIT = 4000


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """One routing answer. ``path`` names the step that produced it."""

    intent: str
    target_agent_id: str | None
    confidence: float
    path: str
    ask_user: bool = False
    choices: tuple[str, ...] = ()
    busy_policy: str | None = None


@dataclass(frozen=True, slots=True)
class Attempt:
    """A step that ran. ``accepted`` is false when the chain should continue."""

    decision: RouteDecision
    accepted: bool
    answers: dict[str, object]
    confidences: dict[str, object]


class ModelRoute(BaseModel):
    """Structured route returned by the LLM, Ollama, and CLI deciders."""

    model_config = ConfigDict(extra="ignore")

    intent: str
    target_agent_id: str | None = None
    busy_policy: str | None = None
    confidence: float


def redact_text(text: str) -> str:
    """Replace registered secrets in ``text`` using the log redaction patcher."""
    record: dict[str, object] = {"message": text, "extra": {}}
    redact(cast("Record", record))
    message = record["message"]
    if isinstance(message, str):
        return message
    return text


def object_dict(value: object) -> dict[str, object] | None:
    """Copy a JSON object into ``dict[str, object]``. Other values are none."""
    if not isinstance(value, dict):
        return None
    body: dict[str, object] = {}
    for key, item in cast("dict[object, object]", value).items():
        if isinstance(key, str):
            body[key] = item
    return body


def stored_state(state: str) -> str:
    """The decision log keeps at most 4 000 characters of redacted state."""
    return state[:_STATE_LIMIT]


def parse_model_route(text: str) -> ModelRoute | None:
    """Parse one JSON object. A non-object reply is not a decision."""
    try:
        return ModelRoute.model_validate_json(text)
    except ValidationError:
        return None


def model_prompt(state: str) -> str:
    """Ask a fallback model for the route JSON. ``state`` is already redacted."""
    return (
        "Reply with one JSON object with keys intent, target_agent_id, "
        "busy_policy, and confidence.\n" + state
    )


def attempt_for(decision: RouteDecision, *, accepted: bool = True) -> Attempt:
    """Wrap a decision that did not come from a model JSON object."""
    return Attempt(
        decision=decision,
        accepted=accepted,
        answers={
            "intent": decision.intent,
            "target_agent_id": decision.target_agent_id,
            "busy_policy": decision.busy_policy,
        },
        confidences={"confidence": decision.confidence},
    )


def attempt_from_model(parsed: ModelRoute, path: str, *, accepted: bool) -> Attempt:
    """Build an attempt from a parsed fallback reply."""
    target = parsed.target_agent_id
    if target == "" or target == "none":
        target = None
    decision = RouteDecision(
        intent=parsed.intent,
        target_agent_id=target,
        confidence=parsed.confidence,
        path=path,
        busy_policy=parsed.busy_policy,
    )
    return Attempt(
        decision=decision,
        accepted=accepted,
        answers={
            "intent": parsed.intent,
            "target_agent_id": target,
            "busy_policy": parsed.busy_policy,
        },
        confidences={"confidence": parsed.confidence},
    )
