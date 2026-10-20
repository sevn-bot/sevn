"""Scripted Pydantic AI ``FunctionModel`` for runtime tests.

``function_model`` imports Pydantic AI when it is called. The package is added
in W3; collecting this module does not require it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from support.canary import note_model_request

type Step = Mapping[str, object]


class TurnGate:
    """Blocks inside a scripted model call so concurrency tests can observe it."""

    def __init__(self) -> None:
        self.release_all = asyncio.Event()
        self.active = 0
        self.max_active = 0
        self._condition = asyncio.Condition()

    async def enter(self) -> None:
        async with self._condition:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self._condition.notify_all()
        await self.release_all.wait()
        async with self._condition:
            self.active -= 1
            self._condition.notify_all()

    async def until(self, predicate: Any, *, timeout_s: float = 5) -> None:
        async with self._condition:

            def ready() -> bool:
                return bool(predicate())

            await asyncio.wait_for(self._condition.wait_for(ready), timeout_s)


def function_model(
    script: Sequence[Step] | Sequence[Sequence[Step]],
    *,
    model_name: str = "function",
    gate: TurnGate | None = None,
    pause: asyncio.Event | None = None,
    recorded: asyncio.Event | None = None,
) -> Any:
    """Return a FunctionModel that streams ``script`` and records each request.

    A flat list of steps is one model response. A list of lists is one response
    per request; further requests repeat the last response. A ``pause`` event
    is awaited after the response has been streamed, while the turn is still open.
    ``recorded`` is set as soon as the request has been recorded.
    """
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel

    responses = _responses(script)
    call_index = 0

    def _steps() -> list[Step]:
        nonlocal call_index
        chosen = responses[min(call_index, len(responses) - 1)]
        call_index += 1
        return chosen

    def _record(messages: list[Any], info: Any) -> None:
        note_model_request(
            {
                "model_name": model_name,
                "instructions": getattr(info, "instructions", None),
                "settings": _plain(getattr(info, "model_settings", None)),
                "messages": _plain(messages),
            }
        )

    async def respond(messages: list[Any], info: Any) -> ModelResponse:
        if gate is not None:
            await gate.enter()
        _record(messages, info)
        if recorded is not None:
            recorded.set()
        parts: list[Any] = []
        for index, step in enumerate(_steps()):
            kind = str(step.get("kind") or "text")
            if kind == "tool":
                parts.append(
                    ToolCallPart(
                        tool_name=str(step.get("name") or ""),
                        args=_args(step.get("args")),
                        tool_call_id=str(step.get("tool_call_id") or f"call_{index}"),
                    )
                )
            else:
                parts.append(TextPart(content=str(step.get("text") or "")))
        if pause is not None:
            await pause.wait()
        return ModelResponse(parts=parts)

    async def stream(messages: list[Any], info: Any) -> AsyncIterator[Any]:
        if gate is not None:
            await gate.enter()
        _record(messages, info)
        if recorded is not None:
            recorded.set()
        for index, step in enumerate(_steps()):
            kind = str(step.get("kind") or "text")
            if kind == "tool":
                yield {
                    index: DeltaToolCall(
                        name=str(step.get("name") or ""),
                        json_args=json.dumps(_args(step.get("args"))),
                        tool_call_id=str(step.get("tool_call_id") or f"call_{index}"),
                    )
                }
            else:
                yield str(step.get("text") or "")
        if pause is not None:
            await pause.wait()

    return FunctionModel(respond, stream_function=stream, model_name=model_name)


def _responses(script: Sequence[Step] | Sequence[Sequence[Step]]) -> list[list[Step]]:
    if len(script) == 0:
        return [[]]
    first = script[0]
    if isinstance(first, list):
        pages: list[list[Step]] = []
        for page in script:
            if not isinstance(page, list):
                raise TypeError("function_model script mixes lists and steps")
            pages.append(list(page))
        return pages
    flat: list[Step] = []
    for step in script:
        if isinstance(step, list):
            raise TypeError("function_model script mixes lists and steps")
        flat.append(step)
    return [flat]


def _args(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _plain(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _plain(dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return str(value)
