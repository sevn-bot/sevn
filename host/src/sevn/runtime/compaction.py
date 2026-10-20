"""before_model_request compaction for the pydantic_ai runtime (spec A.2.4, D16)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters

from sevn.log import logger
from sevn.runtime.errors import ModelError
from sevn.runtime.models import cheapest_configured_model, model_override_active, resolve_model

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext
    from pydantic_ai.tools import RunContext

_KEEP = 6


@dataclass
class Compaction(AbstractCapability[Any]):
    """Summarize older turns once the request exceeds 75% of the model window."""

    _: KW_ONLY

    id: str | None = "compaction"

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        _ = ctx
        window = request_context.model.context_window
        if window is None:
            return request_context
        messages = list(request_context.messages)
        try:
            compacted = await compact_messages(
                messages,
                model_window=window,
                estimated_tokens=_estimate_tokens(messages),
            )
        except ModelError:
            logger.warning("compaction skipped: no cheap model")
            return request_context
        request_context.messages = compacted
        return request_context


async def compact_messages(
    messages: Sequence[ModelMessage],
    *,
    model_window: int,
    estimated_tokens: int,
) -> list[ModelMessage]:
    """Keep the last six messages and capability pairs; summarize the rest."""
    if not _over_threshold(estimated_tokens, model_window) or len(messages) <= _KEEP:
        return list(messages)
    older = messages[:-_KEEP]
    recent = list(messages[-_KEEP:])
    dropped = [message for message in older if not _keeps_capability(message)]
    if len(dropped) == 0:
        return list(messages)
    summary = await _summarize(dropped)
    if summary == "":
        return list(messages)
    compacted: list[ModelMessage] = []
    inserted = False
    for message in older:
        if _keeps_capability(message):
            compacted.append(message)
            continue
        if not inserted:
            compacted.append(ModelResponse(parts=[TextPart(content=summary)]))
            inserted = True
    compacted.extend(recent)
    return compacted


def _over_threshold(estimated_tokens: int, model_window: int) -> bool:
    if model_window <= 0 or estimated_tokens <= 0:
        return False
    return estimated_tokens * 4 > model_window * 3


def _keeps_capability(message: ModelMessage) -> bool:
    for part in message.parts:
        if isinstance(part, LoadCapabilityCallPart | LoadCapabilityReturnPart):
            return True
        tool_name = getattr(part, "tool_name", None)
        if isinstance(tool_name, str) and tool_name == "load_capability":
            return True
    return False


def _estimate_tokens(messages: Sequence[ModelMessage]) -> int:
    return sum(len(_message_text(message)) for message in messages) // 4


async def _summarize(messages: Sequence[ModelMessage]) -> str:
    model = await _cheap_model()
    lines = ["Summarize the earlier conversation in one short message."]
    for message in messages:
        text = _message_text(message)
        if text != "":
            lines.append(text)
    response = await model.request(
        [ModelRequest(parts=[UserPromptPart(content="\n".join(lines))])],
        None,
        ModelRequestParameters(),
    )
    chunks: list[str] = []
    for part in response.parts:
        if isinstance(part, TextPart) and part.content != "":
            chunks.append(part.content)
    return "\n".join(chunks)


async def _cheap_model() -> Model:
    if model_override_active():
        return resolve_model("function:compaction")
    cheap = await asyncio.to_thread(cheapest_configured_model)
    if cheap is None:
        raise ModelError("no cheap model for compaction")
    return await asyncio.to_thread(resolve_model, cheap)


def _message_text(message: ModelMessage) -> str:
    chunks: list[str] = []
    for part in message.parts:
        content = getattr(part, "content", None)
        if isinstance(content, str) and content != "":
            chunks.append(content)
    return "\n".join(chunks)
