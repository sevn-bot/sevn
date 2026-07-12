"""Structured agent-context snapshots for trace export (`specs/04-tracing.md`).

Module: sevn.agent.tracing.agent_context
Depends: pydantic_ai.messages, sevn.agent.tracing.attrs

Exports:
    trace_text_field — one prompt/history field with truncation metadata.
    serialize_message_history_for_trace — pydantic-ai history → JSON-safe rows.
    serialize_user_prompt_for_trace — tier-B user prompt → JSON-safe value.
    build_triager_context_attrs — triager prompt segments for one turn.
    build_tier_b_context_attrs — tier-B instructions + history for one turn.
    emit_context_span — emit one context snapshot span when a sink is wired.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from time import time_ns

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from sevn.agent.tracing.attrs import json_safe_trace_attrs
from sevn.agent.tracing.sink import TraceEvent, TraceSink

TRACE_TEXT_MAX_CHARS = 12_000


def trace_text_field(
    text: str | None,
    *,
    field: str,
    max_chars: int = TRACE_TEXT_MAX_CHARS,
) -> dict[str, object]:
    """Return one text blob plus ``_chars`` / ``_truncated`` metadata for traces.

    Args:
        text (str | None): Source text (whitespace-normalized).
        field (str): Attr key for the text body.
        max_chars (int): Max characters to retain in ``field``.

    Returns:
        dict[str, object]: ``{field, field_chars, field_truncated}``.

    Examples:
        >>> out = trace_text_field("hello", field="body")
        >>> out["body"]
        'hello'
        >>> out["body_truncated"]
        False
    """
    flat = " ".join((text or "").split())
    truncated = len(flat) > max_chars
    body = flat[:max_chars] + ("…" if truncated else "")
    return {
        field: body,
        f"{field}_chars": len(flat),
        f"{field}_truncated": truncated,
    }


def _part_content(part: object) -> str:
    """Return string content from one pydantic-ai message part when present.

    Args:
        part (object): A ``ModelRequest`` or ``ModelResponse`` part instance.

    Returns:
        str: Part content as text, or empty when absent.

    Examples:
        >>> _part_content(UserPromptPart(content="hi"))
        'hi'
    """
    content = getattr(part, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def serialize_message_history_for_trace(
    messages: Sequence[ModelMessage],
) -> list[dict[str, object]]:
    """Serialize pydantic-ai ``message_history`` for trace persistence.

    Args:
        messages (Sequence[ModelMessage]): History passed to ``agent.iter``.

    Returns:
        list[dict[str, object]]: JSON-safe rows with ``kind`` and ``parts``.

    Examples:
        >>> serialize_message_history_for_trace([])
        []
    """
    rows: list[dict[str, object]] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            parts: list[dict[str, object]] = []
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    parts.append({"type": "user", "content": _part_content(part)})
                elif isinstance(part, SystemPromptPart):
                    parts.append({"type": "system", "content": _part_content(part)})
                elif isinstance(part, ToolReturnPart):
                    parts.append(
                        {
                            "type": "tool_return",
                            "tool_name": part.tool_name,
                            "content": _part_content(part),
                        },
                    )
                else:
                    parts.append({"type": type(part).__name__, "content": _part_content(part)})
            rows.append({"kind": "request", "parts": parts})
        elif isinstance(msg, ModelResponse):
            response_parts: list[dict[str, object]] = []
            for response_part in msg.parts:
                if isinstance(response_part, TextPart):
                    response_parts.append({"type": "text", "content": response_part.content})
                elif isinstance(response_part, ToolCallPart):
                    response_parts.append(
                        {
                            "type": "tool_call",
                            "tool_name": response_part.tool_name,
                            "args": json_safe_trace_attrs(
                                dict(response_part.args)
                                if isinstance(response_part.args, dict)
                                else {"raw": response_part.args},
                            ),
                        },
                    )
                else:
                    response_parts.append(
                        {
                            "type": type(response_part).__name__,
                            "content": _part_content(response_part),
                        },
                    )
            rows.append({"kind": "response", "parts": response_parts})
    return rows


def serialize_user_prompt_for_trace(prompt: str | Sequence[object]) -> object:
    """Serialize tier-B ``user_prompt`` for trace attrs.

    Args:
        prompt (str | Sequence[object]): Plain string or multimodal content list.

    Returns:
        object: String or list of JSON-safe multimodal part descriptors.

    Examples:
        >>> serialize_user_prompt_for_trace("hi")
        'hi'
    """
    if isinstance(prompt, str):
        return prompt
    parts: list[dict[str, object]] = []
    for item in prompt:
        if isinstance(item, str):
            parts.append({"type": "text", "content": item})
        else:
            parts.append(
                {
                    "type": type(item).__name__,
                    "content": str(item),
                },
            )
    return parts


def build_triager_context_attrs(
    *,
    segments: tuple[str, str, str, str],
    current_message: str,
    transcript_turns: Sequence[str],
    registry_version: int,
    personality_version: int,
    user_language: str,
    attachment_hints: Sequence[dict[str, str]],
    user_blob: str,
) -> dict[str, object]:
    """Build attrs for a ``triager.context`` span.

    Args:
        segments (tuple[str, str, str, str]): ``(static, registry, personality, suffix)``.
        current_message (str): Operator line for this turn.
        transcript_turns (Sequence[str]): Preformatted transcript lines.
        registry_version (int): Registry snapshot version.
        personality_version (int): Personality bundle version.
        user_language (str): BCP-47-ish language label.
        attachment_hints (Sequence[dict[str, str]]): Inbound attachment metadata.
        user_blob (str): Concatenated prompt sent to the triager model.

    Returns:
        dict[str, object]: JSON-safe attrs for trace sinks.

    Examples:
        >>> attrs = build_triager_context_attrs(
        ...     segments=("s", "r", "p", "x"),
        ...     current_message="hi",
        ...     transcript_turns=[],
        ...     registry_version=1,
        ...     personality_version=0,
        ...     user_language="en",
        ...     attachment_hints=[],
        ...     user_blob="blob",
        ... )
        >>> attrs["agent"]
        'triager'
    """
    static, registry, personality, suffix = segments
    attrs: dict[str, object] = {
        "agent": "triager",
        "current_message": current_message,
        "transcript_turns": list(transcript_turns),
        "transcript_turn_count": len(transcript_turns),
        "registry_version": registry_version,
        "personality_version": personality_version,
        "user_language": user_language,
        "attachment_hints": list(attachment_hints),
        "prompt_segments": {
            **trace_text_field(static, field="static_prefix"),
            **trace_text_field(registry, field="registry_block"),
            **trace_text_field(personality, field="personality_block"),
            **trace_text_field(suffix, field="suffix"),
        },
        **trace_text_field(user_blob, field="user_blob"),
    }
    return json_safe_trace_attrs(attrs)


def build_tier_b_context_attrs(
    *,
    incoming_text: str,
    triager_first_reply: str,
    system_prompt: str,
    instructions: str,
    message_history: Sequence[ModelMessage],
    user_prompt: str | Sequence[object],
    tools: Sequence[str],
    skills: Sequence[str],
) -> dict[str, object]:
    """Build attrs for a ``tier_b.context`` span.

    Args:
        incoming_text (str): Operator message for this turn.
        triager_first_reply (str): Triager ``first_message`` when present.
        system_prompt (str): Static system prompt passed to ``Agent``.
        instructions (str): Dynamic instructions string.
        message_history (Sequence[ModelMessage]): Cross-turn replay history.
        user_prompt (str | Sequence[object]): Current-turn user prompt.
        tools (Sequence[str]): Triager-bound tool names.
        skills (Sequence[str]): Triager-bound skill names.

    Returns:
        dict[str, object]: JSON-safe attrs for trace sinks.

    Examples:
        >>> attrs = build_tier_b_context_attrs(
        ...     incoming_text="hi",
        ...     triager_first_reply="",
        ...     system_prompt="sys",
        ...     instructions="inst",
        ...     message_history=[],
        ...     user_prompt="hi",
        ...     tools=[],
        ...     skills=[],
        ... )
        >>> attrs["agent"]
        'tier_b'
    """
    attrs: dict[str, object] = {
        "agent": "tier_b",
        "operator_message": incoming_text,
        "triager_first_reply": triager_first_reply,
        "tools": list(tools),
        "skills": list(skills),
        "message_history": serialize_message_history_for_trace(message_history),
        "message_history_count": len(message_history),
        "user_prompt": serialize_user_prompt_for_trace(user_prompt),
        **trace_text_field(system_prompt, field="system_prompt"),
        **trace_text_field(instructions, field="instructions"),
    }
    return json_safe_trace_attrs(attrs)


async def emit_context_span(
    trace: TraceSink | None,
    *,
    kind: str,
    session_id: str,
    turn_id: str,
    parent_span_id: str | None,
    tier: str | None,
    attrs: dict[str, object],
) -> None:
    """Emit one agent-context snapshot span when ``trace`` is configured.

    Args:
        trace (TraceSink | None): Gateway trace sink.
        kind (str): Span kind (e.g. ``triager.context``, ``tier_b.context``).
        session_id (str): Owning session id.
        turn_id (str): Turn correlation id.
        parent_span_id (str | None): Parent span (usually turn root).
        tier (str | None): Executor tier label when applicable.
        attrs (dict[str, object]): JSON-safe attribute payload.

    Examples:
        >>> import asyncio
        >>> asyncio.run(
        ...     emit_context_span(
        ...         None,
        ...         kind="triager.context",
        ...         session_id="s",
        ...         turn_id="t",
        ...         parent_span_id=None,
        ...         tier=None,
        ...         attrs={},
        ...     ),
        ... ) is None
        True
    """
    if trace is None:
        return
    now = time_ns()
    await trace.emit(
        TraceEvent(
            kind=kind,
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            session_id=session_id,
            turn_id=turn_id,
            tier=tier,
            ts_start_ns=now,
            ts_end_ns=now,
            status="ok",
            attrs=dict(attrs),
        ),
    )


__all__ = [
    "build_tier_b_context_attrs",
    "build_triager_context_attrs",
    "emit_context_span",
    "serialize_message_history_for_trace",
    "serialize_user_prompt_for_trace",
    "trace_text_field",
]
