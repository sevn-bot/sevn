"""Pydantic AI structured fallback. A confidence under 0.6 continues the chain."""

from __future__ import annotations

import asyncio

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.usage import RunUsage

from sevn.config import Settings
from sevn.decisions.base import Attempt, ModelRoute, attempt_from_model, model_prompt
from sevn.decisions.thresholds import step_accepts
from sevn.log import logger
from sevn.runtime.models import cheapest_configured_model, resolve_model
from sevn.runtime.usage import price_responses, usage_record

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
        return attempt_from_model(
            parsed,
            "llm",
            accepted=step_accepts(parsed.confidence),
            usage=_usage(result.usage, result.new_messages()),
        )


def _usage(usage: RunUsage, messages: list[ModelMessage]) -> dict[str, object]:
    """The call's counts, priced per response like a turn."""
    cost, source = price_responses(
        message for message in messages if isinstance(message, ModelResponse)
    )
    return usage_record(
        {
            "requests": usage.requests,
            "tool_calls": usage.tool_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
        },
        cost_usd=cost,
        cost_source=source,
    )


def _model_name() -> str:
    chosen = Settings.load().decisions.llm_model
    if chosen != "":
        return chosen
    cheap = cheapest_configured_model()
    if cheap is not None:
        return cheap
    return "anthropic:claude-haiku-4-5"


async def _ready() -> bool:
    """A provider key is required. The turn's test model is not a router model."""
    found = await asyncio.to_thread(cheapest_configured_model)
    return found is not None
