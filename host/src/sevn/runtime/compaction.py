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
from sevn.memory.context import carries_memories
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
    split = _split_point(messages, len(messages) - _KEEP)
    older = messages[:split]
    recent = list(messages[split:])
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


def _split_point(messages: Sequence[ModelMessage], start: int) -> int:
    """Move ``start`` back until every tool return kept verbatim has its call.

    A return whose call was summarized away is an unknown ``tool_call_id`` to
    the provider, and the next request fails. Capability pairs in the older
    span are kept, so their calls count as present.
    """
    split = start
    while split > 0:
        kept = list(messages[split:])
        kept.extend(message for message in messages[:split] if _keeps_capability(message))
        called = {
            call_id
            for message in kept
            if isinstance(message, ModelResponse)
            for call_id in _call_ids(message)
        }
        returned = {
            call_id
            for message in messages[split:]
            if isinstance(message, ModelRequest)
            for call_id in _call_ids(message)
        }
        if returned <= called:
            return split
        split -= 1
    return split


def _call_ids(message: ModelMessage) -> list[str]:
    found: list[str] = []
    for part in message.parts:
        call_id = getattr(part, "tool_call_id", None)
        if isinstance(call_id, str) and call_id != "":
            found.append(call_id)
    return found


def _over_threshold(estimated_tokens: int, model_window: int) -> bool:
    if model_window <= 0 or estimated_tokens <= 0:
        return False
    return estimated_tokens * 4 > model_window * 3


def _keeps_capability(message: ModelMessage) -> bool:
    """Kept verbatim: capability pairs, and the user prompt carrying memories.

    Later turns send only a memory diff, so the full block must stay in the
    window or the model loses the memories the diff builds on.
    """
    for part in message.parts:
        if isinstance(part, UserPromptPart) and isinstance(part.content, str):
            if carries_memories(part.content):
                return True
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
