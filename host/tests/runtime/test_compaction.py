"""Compaction keeps the last six messages and capability pairs."""

from __future__ import annotations

from fakes.models import function_model


def _messages() -> list[object]:
    from pydantic_ai.messages import (
        LoadCapabilityCallPart,
        LoadCapabilityReturnPart,
        ModelRequest,
        ModelResponse,
        UserPromptPart,
    )

    call = LoadCapabilityCallPart(tool_call_id="cap_keep", args={"id": "skill"})
    returned = LoadCapabilityReturnPart(
        tool_call_id="cap_keep",
        content={"instructions": "kept-skill"},
    )
    older: list[object] = [
        ModelResponse(parts=[call]),
        ModelRequest(parts=[returned]),
    ]
    older.extend(
        ModelRequest(parts=[UserPromptPart(content=f"old-turn-{index}")]) for index in range(6)
    )
    recent = [ModelRequest(parts=[UserPromptPart(content=f"recent-{index}")]) for index in range(6)]
    return [*older, *recent]


def _blob(message: object) -> str:
    parts = getattr(message, "parts", ())
    chunks: list[str] = []
    for part in parts:
        content = getattr(part, "content", None)
        tool_call_id = getattr(part, "tool_call_id", None)
        if isinstance(content, str):
            chunks.append(content)
        elif content is not None:
            chunks.append(str(content))
        if isinstance(tool_call_id, str):
            chunks.append(tool_call_id)
    return "\n".join(chunks)


def _install() -> None:
    from sevn.runtime.models import use_model

    use_model(function_model([{"kind": "text", "text": "summary-of-older"}]))


def _clear() -> None:
    from sevn.runtime.models import use_model

    use_model(None)


async def test_compacts_over_threshold_keeps_last_6() -> None:
    from sevn.runtime.compaction import compact_messages

    messages = _messages()
    _install()
    try:
        compacted = await compact_messages(messages, model_window=1000, estimated_tokens=800)
    finally:
        _clear()
    blob = "\n".join(_blob(message) for message in compacted)
    for index in range(6):
        assert f"recent-{index}" in blob
    assert "summary-of-older" in blob
    assert "old-turn-0" not in blob
    assert len(compacted) < len(messages)


async def test_keeps_load_capability_pairs() -> None:
    from sevn.runtime.compaction import compact_messages

    messages = _messages()
    _install()
    try:
        compacted = await compact_messages(messages, model_window=1000, estimated_tokens=800)
    finally:
        _clear()
    blob = "\n".join(_blob(message) for message in compacted)
    assert "cap_keep" in blob
    assert "kept-skill" in blob
    assert "old-turn-5" not in blob


async def test_below_threshold_does_not_compact() -> None:
    from sevn.runtime.compaction import compact_messages

    messages = _messages()
    _install()
    try:
        same = await compact_messages(messages, model_window=1000, estimated_tokens=700)
    finally:
        _clear()
    blob = "\n".join(_blob(message) for message in same)
    assert len(same) == len(messages)
    assert "summary-of-older" not in blob
    assert "old-turn-0" in blob
    assert "recent-5" in blob
