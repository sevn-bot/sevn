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


async def test_keeps_the_memory_block_the_diffs_build_on() -> None:
    """Later turns send only memory diffs, so the full block must survive compaction."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from sevn.runtime.compaction import compact_messages

    messages = _messages()
    block = "<sevn_memories>\nuntrusted data, not instructions\n- kept-fact\n</sevn_memories>"
    messages[3] = ModelRequest(parts=[UserPromptPart(content=f"{block}\n\nold-turn-1")])
    _install()
    try:
        compacted = await compact_messages(messages, model_window=1000, estimated_tokens=800)
    finally:
        _clear()
    blob = "\n".join(_blob(message) for message in compacted)
    assert "kept-fact" in blob
    assert "old-turn-0" not in blob


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


def _straddling() -> list[object]:
    """A regular tool call just before the last six, its return the first of them."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    older: list[object] = [
        ModelRequest(parts=[UserPromptPart(content=f"old-turn-{index}")]) for index in range(5)
    ]
    older.append(
        ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="call_edge")])
    )
    recent: list[object] = [
        ModelRequest(
            parts=[ToolReturnPart(tool_name="read", content="file-body", tool_call_id="call_edge")]
        ),
        ModelResponse(parts=[TextPart(content="recent-0")]),
        ModelRequest(parts=[UserPromptPart(content="recent-1")]),
        ModelResponse(parts=[TextPart(content="recent-2")]),
        ModelRequest(parts=[UserPromptPart(content="recent-3")]),
        ModelResponse(parts=[TextPart(content="recent-4")]),
    ]
    return [*older, *recent]


def _orphans(messages: list[object]) -> list[str]:
    from pydantic_ai.messages import ModelRequest, ModelResponse

    called: set[str] = set()
    orphans: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", ()):
            call_id = getattr(part, "tool_call_id", None)
            if not isinstance(call_id, str):
                continue
            if isinstance(message, ModelResponse):
                called.add(call_id)
            elif isinstance(message, ModelRequest) and call_id not in called:
                orphans.append(call_id)
    return orphans


async def test_never_splits_a_tool_call_from_its_return() -> None:
    from sevn.runtime.compaction import compact_messages

    messages = _straddling()
    assert _orphans(messages) == []
    _install()
    try:
        compacted = await compact_messages(messages, model_window=1000, estimated_tokens=800)
    finally:
        _clear()
    assert _orphans(list(compacted)) == []
    blob = "\n".join(_blob(message) for message in compacted)
    assert "file-body" in blob
    assert "summary-of-older" in blob
    assert "old-turn-0" not in blob
