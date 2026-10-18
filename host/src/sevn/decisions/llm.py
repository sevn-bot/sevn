"""Pydantic AI structured fallback. A confidence under 0.6 continues the chain."""

from __future__ import annotations

import asyncio

from sevn.config import Settings
from sevn.decisions.base import Attempt, ModelRoute, attempt_from_model, model_prompt
from sevn.decisions.thresholds import step_accepts
from sevn.log import logger
from sevn.runtime.models import (
    cheapest_configured_model,
    model_override_active,
    resolve_model,
)

_INSTRUCTIONS = "Choose a route. Reply with the structured route and a confidence from 0 to 1."


class LLMDecider:
    """One structured call on the cheapest configured provider model."""

    async def attempt(self, state: str) -> Attempt | None:
        if not await _ready():
            return None
        try:
            from pydantic_ai import Agent

            model = await asyncio.to_thread(resolve_model, _model_name())
            agent: Agent[None, ModelRoute] = Agent(
                model,
                output_type=ModelRoute,
                instructions=_INSTRUCTIONS,
            )
            result = await agent.run(model_prompt(state))
        except Exception:  # noqa: BLE001 — a failed model falls through
            logger.warning("llm decider failed")
            return None
        parsed = result.output
        return attempt_from_model(parsed, "llm", accepted=step_accepts(parsed.confidence))


def _model_name() -> str:
    chosen = Settings.load().decisions.llm_model
    if chosen != "":
        return chosen
    cheap = cheapest_configured_model()
    if cheap is not None:
        return cheap
    return "anthropic:claude-haiku-4-5"


async def _ready() -> bool:
    if model_override_active():
        return True
    found = await asyncio.to_thread(cheapest_configured_model)
    return found is not None
