"""Within-turn outbound ``message`` dedupe (`specs/11-tools-registry.md` §10.13).

A looping tier-B model re-sent the same outbound line every round until the
executor timeout, spamming the user (`gateway.log` 2026-06-22: identical 849-char
``message`` re-delivered across rounds). Identical ``message`` sends within one
turn must deliver once, then short-circuit to a notice without re-delivering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import (
    FunctionTool,
    ToolCall,
    ToolDefinition,
    enveloped_success,
)
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import TracingToolExecutor, _message_dedup_key


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="msg-dedupe",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
        executor_tier="B",
    )


def _message_executor() -> tuple[TracingToolExecutor, list[str]]:
    """A ``message`` tool that records each *actual* delivery body."""
    delivered: list[str] = []

    async def _send(ctx: ToolContext, **kwargs: object) -> str:
        _ = ctx
        text = str(kwargs.get("text", "")).strip()
        delivered.append(text)
        return enveloped_success({"channel": "telegram", "text_length": len(text)})

    definition = ToolDefinition(
        name="message",
        category="outbound",
        description="send a proactive text message",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "channel": {"type": "string"},
                "user_id": {"type": "string"},
            },
            "required": ["text"],
        },
    )
    exe = TracingToolExecutor(default_timeout_seconds=None)
    exe.register(FunctionTool(definition, _send))
    return exe, delivered


def test_message_dedup_key_normalizes_text_and_destination() -> None:
    assert _message_dedup_key({"text": "  hi  "}) == ("", "", "hi")
    assert _message_dedup_key({"text": "hi", "channel": "telegram", "user_id": "u1"}) == (
        "telegram",
        "u1",
        "hi",
    )
    assert _message_dedup_key({"text": "   "}) is None
    assert _message_dedup_key({}) is None


@pytest.mark.asyncio
async def test_identical_message_delivered_once_then_short_circuits(ctx: ToolContext) -> None:
    """Two identical sends in one turn: delivered once, second is a no-deliver notice."""
    exe, delivered = _message_executor()
    call = ToolCall(name="message", arguments={"text": "skills recap"})

    first = json.loads(await exe.dispatch(ctx, call))
    second = json.loads(await exe.dispatch(ctx, call))

    # First send actually delivers and is not flagged as deduped.
    assert first["ok"] is True
    assert first["data"].get("deduped") is not True

    # Second identical send short-circuits without re-delivering.
    assert second["ok"] is True
    assert second["data"]["deduped"] is True
    assert second["data"]["delivered"] is False
    assert "already delivered" in second["data"]["content"]

    # The channel only saw the body once.
    assert delivered == ["skills recap"]


@pytest.mark.asyncio
async def test_distinct_message_bodies_both_deliver(ctx: ToolContext) -> None:
    """Different text is new content — not deduped."""
    exe, delivered = _message_executor()

    await exe.dispatch(ctx, ToolCall(name="message", arguments={"text": "first line"}))
    second = json.loads(
        await exe.dispatch(ctx, ToolCall(name="message", arguments={"text": "second line"})),
    )

    assert second["data"].get("deduped") is not True
    assert delivered == ["first line", "second line"]
