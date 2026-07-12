"""Cross-turn provider-native transcript replay for tier B (`specs/14-executor-tier-b.md`).

Module: sevn.agent.transcript_replay
Depends: pydantic_ai.messages, sevn.agent.adapters.tier_b_model

Exports:
    TranscriptRow — one gateway transcript row with optional structured payload.
    serialize_provider_turn_messages — pydantic-ai history → Anthropic JSON rows.
    sanitize_provider_turn_messages_for_storage — strip orphan ``tool_use`` before persist.
    anthropic_messages_to_pydantic_history — Anthropic JSON rows → message history.
    build_cross_turn_message_history — replay prior turns for ``agent.iter``.
    slim_transcript_for_log_provenance — one prior user line for log audit turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)

from sevn.agent.adapters.tier_b_model import (
    anthropic_completion_to_model_response,
    pydantic_messages_to_anthropic_messages,
    strip_orphan_tool_use_blocks,
)
from sevn.agent.provider_history_keys import PROVIDER_TURN_MESSAGES_KEY
from sevn.logging.structured import debug_event


@dataclass(frozen=True)
class TranscriptRow:
    """One visible gateway message row for cross-turn replay.

    Attributes:
        role (str): ``user`` or ``assistant``.
        text (str): Stored ``gateway_messages.content`` body.
        provider_turn_messages (list[dict[str, Any]] | None): Full tier-B provider
            history for one user turn when persisted on the assistant row.
    """

    role: Literal["user", "assistant"]
    text: str
    provider_turn_messages: list[dict[str, Any]] | None = None


def serialize_provider_turn_messages(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Serialize pydantic-ai messages added during one tier-B turn.

    Args:
        messages (list[ModelMessage]): ``AgentRunResult.new_messages()`` payload.

    Returns:
        list[dict[str, Any]]: Anthropic-shaped ``messages`` rows safe for JSON storage.

    Examples:
        >>> from pydantic_ai.messages import ModelRequest, UserPromptPart
        >>> rows = serialize_provider_turn_messages(
        ...     [ModelRequest(parts=[UserPromptPart(content="hi")])],
        ... )
        >>> rows[0]["role"]
        'user'
    """
    return pydantic_messages_to_anthropic_messages(list(messages))


def sanitize_provider_turn_messages_for_storage(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Strip orphan assistant ``tool_use`` blocks before JSON persistence.

    Args:
        rows (list[dict[str, Any]]): Anthropic-shaped ``messages`` for one turn.

    Returns:
        tuple[list[dict[str, Any]], int]: Sanitized rows and count of stripped
            ``tool_use`` blocks.

    Examples:
        >>> sanitized, stripped = sanitize_provider_turn_messages_for_storage([
        ...     {"role": "assistant", "content": [
        ...         {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...     ]},
        ... ])
        >>> stripped
        1
        >>> sanitized
        []
    """
    return strip_orphan_tool_use_blocks(rows)


def anthropic_messages_to_pydantic_history(
    rows: list[dict[str, Any]],
) -> list[ModelRequest | ModelResponse]:
    """Rebuild pydantic-ai history from stored Anthropic-shaped rows.

    Args:
        rows (list[dict[str, Any]]): Serialized provider turn messages.

    Returns:
        list[ModelRequest | ModelResponse]: History suitable for ``message_history=``.

    Examples:
        >>> hist = anthropic_messages_to_pydantic_history(
        ...     [{"role": "user", "content": "read a.py"}],
        ... )
        >>> hist[0].parts[0].content
        'read a.py'
    """
    history: list[ModelRequest | ModelResponse] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role", ""))
        content = row.get("content")
        if role == "user":
            if isinstance(content, str):
                history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
                continue
            if isinstance(content, list):
                parts: list[UserPromptPart | ToolReturnPart] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    kind = block.get("type")
                    if kind == "text":
                        text = str(block.get("text", ""))
                        if text:
                            parts.append(UserPromptPart(content=text))
                    elif kind == "tool_result":
                        parts.append(
                            ToolReturnPart(
                                tool_name=str(block.get("name", "")),
                                content=block.get("content", ""),
                                tool_call_id=str(block.get("tool_use_id", "")),
                            ),
                        )
                if parts:
                    history.append(ModelRequest(parts=parts))
        elif role == "assistant":
            if isinstance(content, str):
                history.append(ModelResponse(parts=[TextPart(content=content)]))
            elif isinstance(content, list):
                history.append(
                    anthropic_completion_to_model_response({"content": content}),
                )
    return history


def slim_transcript_for_log_provenance(rows: list[TranscriptRow]) -> list[TranscriptRow]:
    """Keep only the last prior user line for log-provenance audit turns.

    Args:
        rows (list[TranscriptRow]): Prior visible rows excluding the current user line.

    Returns:
        list[TranscriptRow]: Zero or one user row — the question being audited.

    Examples:
        >>> slim = slim_transcript_for_log_provenance([
        ...     TranscriptRow(role="user", text="Wemby stats?"),
        ...     TranscriptRow(role="assistant", text="Game 4: 107-106"),
        ... ])
        >>> len(slim) == 1 and slim[0].text == "Wemby stats?"
        True
    """
    for row in reversed(rows):
        if row.role == "user" and row.text.strip():
            return [row]
    return []


def build_cross_turn_message_history(
    rows: list[TranscriptRow],
    *,
    replay_provider_history: bool,
) -> list[ModelRequest | ModelResponse]:
    """Build ``message_history`` for ``agent.iter`` from prior gateway rows.

    When ``replay_provider_history`` is true and an assistant row carries
    ``provider_turn_messages``, that structured payload replaces the text-only
    ``user:`` / ``assistant:`` fallback for the whole user turn (including tool
    rounds). Otherwise prior turns replay as ``TextPart``-only assistant lines.

    Args:
        rows (list[TranscriptRow]): Prior visible rows excluding the current user line.
        replay_provider_history (bool): Triager gate (D8).

    Returns:
        list[ModelRequest | ModelResponse]: Cross-turn history ending on the last
            assistant reply.

    Examples:
        >>> rows = [
        ...     TranscriptRow(role="user", text="hi"),
        ...     TranscriptRow(role="assistant", text="hello"),
        ... ]
        >>> hist = build_cross_turn_message_history(rows, replay_provider_history=False)
        >>> len(hist)
        2
    """
    history: list[ModelRequest | ModelResponse] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.role == "user":
            next_row = rows[index + 1] if index + 1 < len(rows) else None
            structured = (
                next_row.provider_turn_messages
                if next_row is not None and next_row.role == "assistant"
                else None
            )
            if replay_provider_history and structured:
                sanitized, stripped = sanitize_provider_turn_messages_for_storage(structured)
                if stripped:
                    debug_event(
                        "transcript_replay.sanitized_orphans",
                        stripped_tool_use_count=stripped,
                        message_count=len(sanitized),
                    )
                history.extend(anthropic_messages_to_pydantic_history(sanitized))
                index += 2
                continue
            if row.text:
                history.append(ModelRequest(parts=[UserPromptPart(content=row.text)]))
            index += 1
            continue
        if row.text:
            history.append(ModelResponse(parts=[TextPart(content=row.text)]))
        index += 1
    return history


__all__ = [
    "PROVIDER_TURN_MESSAGES_KEY",
    "TranscriptRow",
    "anthropic_messages_to_pydantic_history",
    "build_cross_turn_message_history",
    "sanitize_provider_turn_messages_for_storage",
    "serialize_provider_turn_messages",
    "slim_transcript_for_log_provenance",
]
