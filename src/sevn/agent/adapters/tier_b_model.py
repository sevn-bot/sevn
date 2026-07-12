"""OpenAI Chat Completions bridge for tier-B ``FunctionModel`` (`specs/14-executor-tier-b.md` §2.3).

Maps pydantic-ai ``ModelMessage`` histories to proxy ``ChatCompletionsTransport.complete`` requests
and parses responses back into ``ModelResponse`` (text + tool calls).

Tier-B supports ``ChatCompletionsTransport``, ``AnthropicMessagesTransport``, and
``BedrockTransport``; ``ResponsesApiTransport`` remains unsupported until a serializer lands.

Module: sevn.agent.adapters.tier_b_model
Depends: pydantic_ai, sevn.agent.executors.b_types, sevn.agent.providers.transport,
    sevn.agent.tracing.sink, sevn.config.defaults

Exports:
    TriagerBoundToolChoiceContext - per-turn triager-bound ``tool_choice`` escalation state.
    build_tier_b_function_model - ``FunctionModel`` calling ``Transport.complete``.
    apply_minimax_anthropic_request_hygiene - MiniMax anthropic-wire param hygiene (D2).
    build_llm_request_metadata - redaction-safe provider ``metadata`` correlation fields.
    tier_b_system_prompt_text - merge persona ``SystemPromptPart`` + ``AgentInfo.instructions`` for the wire.
    pydantic_messages_to_openai_chat - pydantic-ai history to OpenAI chat messages.
    pydantic_messages_to_anthropic_messages - pydantic-ai history to Anthropic messages.
    merge_adjacent_anthropic_text_blocks - coalesce adjacent Anthropic text blocks (P7).
    coalesce_adjacent_anthropic_messages - merge consecutive same-role rows (2013 fix).
    coalesce_adjacent_openai_messages - merge consecutive same-role chat rows (2013 fix).
    finalize_openai_chat_messages - drop orphan tool results + trailing assistant echo (2013 fix).
    repair_anthropic_tool_pairing - align tool_use ids with tool_result rows (legacy).
    repair_openai_tool_pairing - repair orphan tool returns and dangling tool calls (2013).
    strip_orphan_tool_use_blocks - drop unfulfilled tool_use instead of replay stubs (W3).
    strip_orphan_tool_result_blocks - drop tool_result whose tool_use was stripped (2013 fix).
    rewrite_codemode_native_tool_calls - recover bare sandboxed-tool calls into run_code (§10.30).
    normalize_codemode_run_code_payloads - unwrap double-wrapped run_code {"code": ...} payloads.
    replay_stubs_are_same_turn_only - classify same-turn vs cross-turn replay stubs (W3).
    prepare_anthropic_messages_for_transport - coalesce + strip + sanitize pipeline.
    append_owner_steer_model_request - inject /steer without splitting user rows.
    sanitize_anthropic_messages - drop empty blocks before Anthropic POST (P7).
    pydantic_messages_to_bedrock_converse - pydantic-ai history to Bedrock Converse messages.
    openai_completion_to_model_response - OpenAI chat completion blob to ``ModelResponse``.
    anthropic_completion_to_model_response - Anthropic Messages blob to ``ModelResponse``.
    is_anthropic_empty_end_turn - detect empty MiniMax ``end_turn`` payloads for nudge.
    bedrock_converse_to_model_response - Bedrock Converse blob to ``ModelResponse``.

Examples:
    >>> from sevn.agent.providers.transport import ChatCompletionsTransport
    >>> isinstance(ChatCompletionsTransport().name, str)
    True
"""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from time import time_ns
from typing import TYPE_CHECKING, Any, Final, Literal

from loguru import logger
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    BaseToolReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)
from pydantic_ai.tools import ToolDefinition as PAToolDefinition
from pydantic_ai.usage import RequestUsage

from sevn.agent.adapters.tool_part_filter import MutableToolAllowlist, filter_tool_call_parts
from sevn.agent.executors.b_types import ResolvedTierBModel, SteerInject
from sevn.agent.grounding import (
    _bound_meta_tool_mandate_satisfied,
    steer_for_dropped_tool_call,
    triager_bound_tools_satisfied,
)
from sevn.agent.providers.transport import (
    AnthropicMessagesTransport,
    AnthropicTransport,
    BedrockTransport,
    ChatCompletionsTransport,
    StreamTextDelta,
    Transport,
)
from sevn.agent.providers.wire import adapt_request_for_transport
from sevn.agent.tracing.provider_call import emit_provider_call
from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.llm_params import (
    MINIMAX_THINKING_AGENTS,
    resolve_llm_request_params,
    resolve_minimax_thinking_request,
)
from sevn.config.model_resolution import is_minimax_catalog_model

# Meta loaders (load_tool / load_skill) do not consume tier-B counted-round budget.
_BUDGET_EXCLUDED_TOOL_NAMES: frozenset[str] = frozenset({"load_tool", "load_skill"})

# Whitelist of redaction-safe correlation keys for MiniMax ``metadata`` (D2).
_LLM_REQUEST_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "session_id",
        "turn_id",
        "user_id",
        "channel",
        "workspace_id",
        "agent",
        "executor_tier",
    }
)


def _has_budget_counted_tool_calls(
    parts: tuple[ModelResponsePart, ...] | list[ModelResponsePart],
) -> bool:
    """Return whether the response includes tool calls that count toward round budget.

    Args:
        parts (tuple[ModelResponsePart, ...] | list[ModelResponsePart]): Provider response parts.

    Returns:
        bool: ``True`` when at least one ``ToolCallPart`` is not a meta loader
        (``load_tool`` / ``load_skill``).

    Examples:
        >>> from pydantic_ai.messages import ToolCallPart
        >>> _has_budget_counted_tool_calls([ToolCallPart(tool_name="load_tool", args={}, tool_call_id="a")])
        False
        >>> _has_budget_counted_tool_calls([ToolCallPart(tool_name="load_skill", args={}, tool_call_id="s")])
        False
        >>> _has_budget_counted_tool_calls([ToolCallPart(tool_name="read", args={}, tool_call_id="b")])
        True
    """
    return any(
        isinstance(part, ToolCallPart) and part.tool_name not in _BUDGET_EXCLUDED_TOOL_NAMES
        for part in parts
    )


if TYPE_CHECKING:
    from sevn.agent.providers.budget import ModelBudget


def _user_prompt_to_text(content: str | Any) -> str:
    """Flatten a user-prompt payload (string or list) into a plain text body.

    Args:
        content (str | Any): Either a raw string or list of chunks.

    Returns:
        str: Newline-joined text body.

    Examples:
        >>> _user_prompt_to_text("hello")
        'hello'
        >>> _user_prompt_to_text(["a", "b"])
        'a\\nb'
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            else:
                chunks.append(str(item))
        return "\n".join(chunks)
    return str(content)


def tier_b_system_prompt_text(
    messages: list[ModelMessage],
    info: AgentInfo,
) -> str | None:
    """Collect persona ``system_prompt`` and static ``instructions`` for the wire.

    Pydantic AI stores ``Agent.system_prompt`` in ``SystemPromptPart`` on the first
    ``ModelRequest``; ``Agent.instructions`` (tool docs + BOOTSTRAP intro) is passed
    only on ``AgentInfo``, not in ``messages``. Tier-B serializers must merge both
    into Anthropic ``system`` or OpenAI ``role: system`` or the upstream sees
    ``system_chars: 0`` and the model leaks vendor identity.

    Args:
        messages (list[ModelMessage]): History passed to ``FunctionModel._llm``.
        info (AgentInfo): Per-round agent metadata from pydantic-ai.

    Returns:
        str | None: Combined system text, or ``None`` when empty.

    Examples:
        >>> from pydantic_ai.models import ModelRequestParameters
        >>> from pydantic_ai.models.function import AgentInfo
        >>> msgs = [
        ...     ModelRequest(parts=[SystemPromptPart(content="Name: Sevn")]),
        ... ]
        >>> info = AgentInfo(
        ...     function_tools=[],
        ...     allow_text_output=True,
        ...     output_tools=[],
        ...     model_settings=None,
        ...     model_request_parameters=ModelRequestParameters(),
        ...     instructions="BOOTSTRAP block",
        ... )
        >>> tier_b_system_prompt_text(msgs, info).startswith("Name: Sevn")
        True
    """
    parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, SystemPromptPart):
                text = _user_prompt_to_text(part.content)
                if text.strip():
                    parts.append(text.strip())
    if info.instructions and info.instructions.strip():
        parts.append(info.instructions.strip())
    if not parts:
        return None
    return "\n\n".join(parts)


def pydantic_messages_to_openai_chat(
    messages: list[ModelMessage],
) -> list[dict[str, Any]]:
    """Project pydantic-ai history to OpenAI ``messages`` JSON (`specs/05-llm-transports.md` chat shape).

    Args:
        messages (list[ModelMessage]): Pydantic AI message history (request + response parts).

    Returns:
        list[dict[str, Any]]: Chat-completions ``messages`` list with role / content / tool_calls.

    Examples:
        >>> pydantic_messages_to_openai_chat([])
        []
    """

    out: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    out.append({"role": "user", "content": _user_prompt_to_text(part.content)})
                elif isinstance(part, BaseToolReturnPart):
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": part.tool_call_id,
                            "content": part.model_response_str(),
                        },
                    )
        elif isinstance(msg, ModelResponse):
            text_chunks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for resp_part in msg.parts:
                if isinstance(resp_part, TextPart):
                    if resp_part.content:
                        text_chunks.append(resp_part.content)
                elif isinstance(resp_part, ToolCallPart):
                    args = resp_part.args
                    if isinstance(args, dict):
                        arg_str = json.dumps(args, separators=(",", ":"), ensure_ascii=False)
                    else:
                        arg_str = str(args) if args is not None else "{}"
                    tool_calls.append(
                        {
                            "id": resp_part.tool_call_id,
                            "type": "function",
                            "function": {"name": resp_part.tool_name, "arguments": arg_str},
                        },
                    )
            assistant: dict[str, Any] = {"role": "assistant"}
            if text_chunks:
                assistant["content"] = "\n".join(text_chunks)
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            if "content" not in assistant and "tool_calls" not in assistant:
                assistant["content"] = ""
            out.append(assistant)
    return out


def merge_adjacent_anthropic_text_blocks(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Coalesce consecutive Anthropic ``text`` blocks and drop empties (P7).

    MiniMax's Anthropic-compatible endpoint rejects fragmented assistant history
    (multiple adjacent ``text`` blocks from separate ``TextPart``s). Merging also
    prevents glued user-visible segments when history is replayed.

    Args:
        blocks (list[dict[str, Any]]): Anthropic ``content`` block list.

    Returns:
        list[dict[str, Any]]: Sanitized blocks with adjacent text merged.

    Examples:
        >>> merge_adjacent_anthropic_text_blocks([
        ...     {"type": "text", "text": "On it."},
        ...     {"type": "text", "text": "Saved."},
        ... ])
        [{'type': 'text', 'text': 'On it.\\n\\nSaved.'}]
        >>> merge_adjacent_anthropic_text_blocks([
        ...     {"type": "thinking", "thinking": "plan"},
        ...     {"type": "text", "text": "hi"},
        ...     {"type": "text", "text": "there"},
        ... ])
        [{'type': 'thinking', 'thinking': 'plan'}, {'type': 'text', 'text': 'hi\\n\\nthere'}]
    """
    merged: list[dict[str, Any]] = []
    text_run: list[str] = []

    def _flush_text() -> None:
        if not text_run:
            return
        combined = "\n\n".join(text_run)
        if combined.strip():
            merged.append({"type": "text", "text": combined})
        text_run.clear()

    for block in blocks:
        if block.get("type") == "text":
            text = str(block.get("text") or "")
            if text.strip():
                text_run.append(text)
            continue
        _flush_text()
        merged.append(block)
    _flush_text()
    return merged


def _anthropic_message_blocks(content: object) -> list[dict[str, Any]]:
    """Normalize one Anthropic message ``content`` field to a block list.

    Args:
        content (object): String body or block list from an Anthropic message row.

    Returns:
        list[dict[str, Any]]: Content blocks (may be empty).

    Examples:
        >>> _anthropic_message_blocks("hi")
        [{'type': 'text', 'text': 'hi'}]
    """
    if isinstance(content, str):
        text = content.strip()
        if text:
            return [{"type": "text", "text": content}]
        return []
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _anthropic_blocks_to_content(blocks: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    """Collapse a block list to Anthropic string or list form.

    Args:
        blocks (list[dict[str, Any]]): Non-empty sanitized blocks.

    Returns:
        str | list[dict[str, Any]]: Single text string or multi-block list.

    Examples:
        >>> _anthropic_blocks_to_content([{"type": "text", "text": "ok"}])
        'ok'
    """
    if len(blocks) == 1 and blocks[0].get("type") == "text":
        return str(blocks[0]["text"])
    return blocks


def _order_user_blocks_for_merge(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place ``tool_result`` blocks before text when merging consecutive user rows.

    Args:
        blocks (list[dict[str, Any]]): Merged user content blocks.

    Returns:
        list[dict[str, Any]]: Blocks ordered for MiniMax Anthropic pairing rules.

    Examples:
        >>> _order_user_blocks_for_merge([
        ...     {"type": "text", "text": "steer"},
        ...     {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ... ])[0]["type"]
        'tool_result'
    """
    tool_results = [b for b in blocks if b.get("type") == "tool_result"]
    other = [b for b in blocks if b.get("type") != "tool_result"]
    return [*tool_results, *other]


def coalesce_adjacent_anthropic_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge consecutive rows with the same ``role`` (steer / tool-return splits).

    Pydantic AI emits separate ``ModelRequest`` rows for tool returns and owner steer
    text; projecting each row to Anthropic produces consecutive ``user`` messages that
    MiniMax rejects with ``tool call and result not match (2013)``.

    Args:
        messages (list[dict[str, Any]]): Anthropic ``messages`` list.

    Returns:
        list[dict[str, Any]]: Messages with adjacent same-role rows merged.

    Examples:
        >>> coalesce_adjacent_anthropic_messages([
        ...     {"role": "assistant", "content": [
        ...         {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...     ]},
        ...     {"role": "user", "content": [
        ...         {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
        ...     ]},
        ...     {"role": "user", "content": "[Owner steer] retry"},
        ... ])
        [{'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 't1', 'name': 'read', 'input': {}}]}, {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'ok'}, {'type': 'text', 'text': '[Owner steer] retry'}]}]
    """
    merged: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        blocks = merge_adjacent_anthropic_text_blocks(_anthropic_message_blocks(msg.get("content")))
        if not blocks:
            continue
        if merged and merged[-1].get("role") == role:
            prev_blocks = _anthropic_message_blocks(merged[-1].get("content"))
            combined = merge_adjacent_anthropic_text_blocks(prev_blocks + blocks)
            if role == "user":
                combined = _order_user_blocks_for_merge(combined)
            merged[-1] = {"role": role, "content": _anthropic_blocks_to_content(combined)}
            continue
        merged.append({"role": role, "content": _anthropic_blocks_to_content(blocks)})
    return merged


def _merge_openai_same_role(prev: dict[str, Any], cur: dict[str, Any]) -> dict[str, Any]:
    """Merge two adjacent same-role OpenAI chat rows (text joined, tool_calls concatenated).

    Args:
        prev (dict[str, Any]): Earlier same-role message.
        cur (dict[str, Any]): Later same-role message.

    Returns:
        dict[str, Any]: Single merged ``{role, content?, tool_calls?}`` row.

    Examples:
        >>> _merge_openai_same_role(
        ...     {"role": "user", "content": "a"}, {"role": "user", "content": "b"})
        {'role': 'user', 'content': 'a\\nb'}
    """
    role = prev.get("role")
    texts = [
        str(m.get("content"))
        for m in (prev, cur)
        if isinstance(m.get("content"), str) and m.get("content")
    ]
    tool_calls: list[Any] = []
    for m in (prev, cur):
        calls = m.get("tool_calls")
        if isinstance(calls, list):
            tool_calls.extend(calls)
    out: dict[str, Any] = {"role": role}
    if texts:
        out["content"] = "\n".join(texts)
    if tool_calls:
        out["tool_calls"] = tool_calls
    if "content" not in out and "tool_calls" not in out:
        out["content"] = ""
    return out


def coalesce_adjacent_openai_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge consecutive same-role ``user``/``assistant`` rows on the chat_completions wire (2013).

    OpenAI-wire analog of :func:`coalesce_adjacent_anthropic_messages`. Pydantic AI emits separate
    rows for the user message, owner-steer text, and full-index retry instructions; projected to
    chat-completions these become **consecutive ``user`` (or ``assistant``) messages** that MiniMax
    rejects with ``invalid params … tool call and result not match (2013)`` — even when no tool
    blocks are present (transcript-review-2026-06-22). ``tool`` and ``system`` rows are left
    untouched: each ``tool`` row must keep its own ``tool_call_id``.

    Args:
        messages (list[dict[str, Any]]): Chat-completions ``messages`` list.

    Returns:
        list[dict[str, Any]]: Messages with adjacent same-role user/assistant rows merged.

    Examples:
        >>> coalesce_adjacent_openai_messages([
        ...     {"role": "user", "content": "what won yesterday?"},
        ...     {"role": "user", "content": "[Owner steer] search first"},
        ... ])
        [{'role': 'user', 'content': 'what won yesterday?\\n[Owner steer] search first'}]
        >>> coalesce_adjacent_openai_messages([
        ...     {"role": "tool", "tool_call_id": "a", "content": "1"},
        ...     {"role": "tool", "tool_call_id": "b", "content": "2"},
        ... ])
        [{'role': 'tool', 'tool_call_id': 'a', 'content': '1'}, {'role': 'tool', 'tool_call_id': 'b', 'content': '2'}]
    """
    merged: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role in ("user", "assistant") and merged and merged[-1].get("role") == role:
            merged[-1] = _merge_openai_same_role(merged[-1], msg)
            continue
        merged.append(dict(msg))
    return merged


def finalize_openai_chat_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip wire shapes MiniMax rejects with 2013 from a chat_completions message list.

    Two residual ``2013`` triggers seen after same-role coalescing (transcript-review-2026-06-22):

    - **orphan tool result** — a ``tool`` row whose ``tool_call_id`` matches no assistant
      ``tool_calls`` id anywhere in the request (``tool call result does not follow tool call``).
    - **trailing assistant echo** — the request ends with an ``assistant`` row that carries no
      ``tool_calls`` (a failed/echoed prior-pass output). A completion request must end with a
      ``user``/``tool`` row so the model generates the next turn (``tool call and result not
      match``). Assistant rows *with* tool_calls are left for :func:`repair_openai_tool_pairing`.

    Args:
        messages (list[dict[str, Any]]): Chat-completions ``messages`` list (post-coalesce).

    Returns:
        list[dict[str, Any]]: Messages with orphan tool results and trailing assistant echoes removed.

    Examples:
        >>> finalize_openai_chat_messages([
        ...     {"role": "user", "content": "hi"},
        ...     {"role": "assistant", "content": "done"},
        ... ])
        [{'role': 'user', 'content': 'hi'}]
        >>> finalize_openai_chat_messages([
        ...     {"role": "assistant", "tool_calls": [{"id": "a", "function": {"name": "x"}}]},
        ...     {"role": "tool", "tool_call_id": "a", "content": "1"},
        ...     {"role": "tool", "tool_call_id": "ghost", "content": "2"},
        ... ])
        [{'role': 'assistant', 'tool_calls': [{'id': 'a', 'function': {'name': 'x'}}]}, {'role': 'tool', 'tool_call_id': 'a', 'content': '1'}]
    """
    declared_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for call in msg.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id"):
                    declared_ids.add(str(call["id"]))
    pruned = [
        msg
        for msg in messages
        if not (msg.get("role") == "tool" and str(msg.get("tool_call_id")) not in declared_ids)
    ]
    while pruned and pruned[-1].get("role") == "assistant" and not pruned[-1].get("tool_calls"):
        pruned.pop()
    return pruned


SYNTHETIC_TOOL_RESULT_REPLAY_STUB: str = (
    '{"ok":true,"data":{"replay_stub":true,'
    '"note":"Transport replay stub — prior tool output omitted. '
    "Call the tool again in run_code if you need fresh data; "
    'do not report this stub as a tool failure."}}'
)
"""Neutral JSON placeholder for orphan ``tool_use`` rows at transport POST (2013 fix)."""


def _synthetic_tool_result_block(tool_id: str) -> dict[str, Any]:
    """Build one replay stub ``tool_result`` block for an unmatched ``tool_use`` id.

    Args:
        tool_id (str): Anthropic ``tool_use`` id needing a paired result.

    Returns:
        dict[str, Any]: Non-error stub so replay repair does not poison the model.

    Examples:
        >>> block = _synthetic_tool_result_block("t1")
        >>> block["is_error"]
        False
        >>> "replay_stub" in block["content"]
        True
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": SYNTHETIC_TOOL_RESULT_REPLAY_STUB,
        "is_error": False,
    }


def _synthetic_tool_result_messages(tool_ids: list[str]) -> list[dict[str, Any]]:
    """Build user rows with replay stubs for unmatched assistant tool_use ids.

    Args:
        tool_ids (list[str]): Pending Anthropic tool_use ids.

    Returns:
        list[dict[str, Any]]: One user message when ``tool_ids`` is non-empty.

    Examples:
        >>> _synthetic_tool_result_messages(["t1"])[0]["role"]
        'user'
    """
    if not tool_ids:
        return []
    blocks = [_synthetic_tool_result_block(tool_id) for tool_id in tool_ids]
    return [{"role": "user", "content": blocks}]


def strip_orphan_tool_use_blocks(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Remove unfulfilled assistant ``tool_use`` blocks instead of inserting replay stubs.

    Walks each assistant row and requires matching ``tool_result`` blocks in the
    immediately following user row. Unpaired ``tool_use`` blocks — including a
    trailing assistant row ending on in-flight tool calls — are removed so
    transport stays valid without poisoning the model with synthetic placeholders.

    Args:
        messages (list[dict[str, Any]]): Anthropic-shaped ``messages`` rows.

    Returns:
        tuple[list[dict[str, Any]], int]: Sanitized rows and count of stripped
            ``tool_use`` blocks.

    Examples:
        >>> stripped_rows, stripped = strip_orphan_tool_use_blocks([
        ...     {"role": "assistant", "content": [
        ...         {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...     ]},
        ... ])
        >>> stripped
        1
        >>> stripped_rows
        []
    """
    if not messages:
        return [], 0
    out: list[dict[str, Any]] = []
    stripped = 0
    index = 0
    while index < len(messages):
        row = messages[index]
        if not isinstance(row, dict):
            index += 1
            continue
        role = row.get("role")
        if role != "assistant":
            out.append(row)
            index += 1
            continue
        blocks = _anthropic_message_blocks(row.get("content"))
        tool_use_ids = [
            str(block.get("id"))
            for block in blocks
            if block.get("type") == "tool_use" and block.get("id")
        ]
        if not tool_use_ids:
            out.append(row)
            index += 1
            continue
        next_row = messages[index + 1] if index + 1 < len(messages) else None
        fulfilled: set[str] = set()
        if isinstance(next_row, dict) and next_row.get("role") == "user":
            next_blocks = _anthropic_message_blocks(next_row.get("content"))
            fulfilled = {
                str(block.get("tool_use_id"))
                for block in next_blocks
                if block.get("type") == "tool_result" and block.get("tool_use_id")
            }
        kept_blocks = [
            block
            for block in blocks
            if block.get("type") != "tool_use" or str(block.get("id", "")) in fulfilled
        ]
        stripped += sum(1 for tool_id in tool_use_ids if tool_id not in fulfilled)
        if kept_blocks:
            out.append({"role": "assistant", "content": _anthropic_blocks_to_content(kept_blocks)})
        index += 1
    return out, stripped


def strip_orphan_tool_result_blocks(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Remove user ``tool_result`` blocks whose ``tool_use`` was dropped (MiniMax 400 guard).

    Symmetric counterpart to :func:`strip_orphan_tool_use_blocks`. When a steer or text
    message separates an assistant ``tool_use`` from its ``tool_result`` (multi-turn
    replay via ``build_cross_turn_message_history``), the tool_use strip pass can remove
    the ``tool_use`` while the matching ``tool_result`` survives in a later user row.
    MiniMax's Anthropic-compatible endpoint then rejects the orphan with
    ``"tool result's tool id(minimax-xml-N) not found (2013)"``. This pass collects every
    surviving ``tool_use`` id across the whole list and drops any ``tool_result`` block
    whose ``tool_use_id`` is not among them, dropping the row entirely when it empties.

    Args:
        messages (list[dict[str, Any]]): Anthropic-shaped ``messages`` rows, already run
            through :func:`strip_orphan_tool_use_blocks`.

    Returns:
        tuple[list[dict[str, Any]], int]: Sanitized rows and count of stripped
            ``tool_result`` blocks.

    Examples:
        >>> rows, stripped = strip_orphan_tool_result_blocks([
        ...     {"role": "user", "content": [
        ...         {"type": "tool_result", "tool_use_id": "minimax-xml-1", "content": "ok"},
        ...     ]},
        ... ])
        >>> stripped
        1
        >>> rows
        []
    """
    if not messages:
        return [], 0
    live_tool_use_ids: set[str] = set()
    for row in messages:
        if not isinstance(row, dict) or row.get("role") != "assistant":
            continue
        for block in _anthropic_message_blocks(row.get("content")):
            if block.get("type") == "tool_use" and block.get("id"):
                live_tool_use_ids.add(str(block.get("id")))
    out: list[dict[str, Any]] = []
    stripped = 0
    for row in messages:
        if not isinstance(row, dict) or row.get("role") != "user":
            if isinstance(row, dict):
                out.append(row)
            continue
        blocks = _anthropic_message_blocks(row.get("content"))
        if not any(block.get("type") == "tool_result" for block in blocks):
            out.append(row)
            continue
        kept_blocks = [
            block
            for block in blocks
            if block.get("type") != "tool_result"
            or str(block.get("tool_use_id", "")) in live_tool_use_ids
        ]
        stripped += len(blocks) - len(kept_blocks)
        if kept_blocks:
            out.append({"role": "user", "content": _anthropic_blocks_to_content(kept_blocks)})
    return out, stripped


def repair_anthropic_tool_pairing(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Align assistant ``tool_use`` ids with the following user ``tool_result`` rows.

    Args:
        messages (list[dict[str, Any]]): Anthropic ``messages`` after coalescing.

    Returns:
        list[dict[str, Any]]: History safe for MiniMax Anthropic wire replay.

    Examples:
        >>> repaired = repair_anthropic_tool_pairing([
        ...     {"role": "assistant", "content": [
        ...         {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...     ]},
        ...     {"role": "assistant", "content": "continuing"},
        ... ])
        >>> repaired[1]["role"]
        'user'
    """
    repaired: list[dict[str, Any]] = []
    pending_tool_ids: list[str] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "assistant":
            if pending_tool_ids:
                repaired.extend(_synthetic_tool_result_messages(pending_tool_ids))
                pending_tool_ids = []
            blocks = _anthropic_message_blocks(msg.get("content"))
            for block in blocks:
                if block.get("type") == "tool_use":
                    tool_id = block.get("id")
                    if isinstance(tool_id, str) and tool_id:
                        pending_tool_ids.append(tool_id)
            repaired.append(msg)
            continue
        if role == "user":
            blocks = _anthropic_message_blocks(msg.get("content"))
            if pending_tool_ids:
                fulfilled = {
                    str(block.get("tool_use_id"))
                    for block in blocks
                    if block.get("type") == "tool_result" and block.get("tool_use_id")
                }
                missing = [tool_id for tool_id in pending_tool_ids if tool_id not in fulfilled]
                pending_tool_ids = []
                if missing:
                    extra = [_synthetic_tool_result_block(tool_id) for tool_id in missing]
                    blocks = _order_user_blocks_for_merge(extra + blocks)
                else:
                    blocks = _order_user_blocks_for_merge(blocks)
                if blocks:
                    repaired.append(
                        {"role": "user", "content": _anthropic_blocks_to_content(blocks)},
                    )
                continue
            blocks = [b for b in blocks if b.get("type") != "tool_result"]
            if blocks:
                repaired.append(
                    {"role": "user", "content": _anthropic_blocks_to_content(blocks)},
                )
            continue
        repaired.append(msg)

    # Stale replay rows may end on assistant ``tool_use`` (e.g. prior turn stored
    # ``run_code`` without a following ``tool_result``). Transport POST must not
    # leave orphan tool_use at the tail — MiniMax returns 2013.
    if pending_tool_ids:
        repaired.extend(_synthetic_tool_result_messages(pending_tool_ids))
    return repaired


def _count_replay_stub_tool_results(messages: list[dict[str, Any]]) -> int:
    """Count synthetic replay-stub ``tool_result`` blocks in Anthropic history.

    Args:
        messages (list[dict[str, Any]]): Anthropic-shaped message rows.

    Returns:
        int: Number of ``tool_result`` blocks tagged with ``replay_stub``.

    Examples:
        >>> _count_replay_stub_tool_results([
        ...     {"role": "user", "content": [
        ...         {"type": "tool_result", "tool_use_id": "t1", "content": '{"replay_stub":true}'},
        ...     ]},
        ... ])
        1
    """
    count = 0
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if "replay_stub" in str(block.get("content", "")):
                count += 1
    return count


def _replay_stub_tool_use_ids(messages: list[dict[str, Any]]) -> list[str]:
    """Collect ``tool_use_id`` values from synthetic replay-stub ``tool_result`` rows.

    Args:
        messages (list[dict[str, Any]]): Anthropic-shaped message rows after repair.

    Returns:
        list[str]: Stubbed tool-use ids in message order.

    Examples:
        >>> _replay_stub_tool_use_ids([
        ...     {"role": "user", "content": [
        ...         {"type": "tool_result", "tool_use_id": "t1", "content": '{"replay_stub":true}'},
        ...     ]},
        ... ])
        ['t1']
    """
    ids: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if "replay_stub" not in str(block.get("content", "")):
                continue
            tool_id = block.get("tool_use_id")
            if isinstance(tool_id, str) and tool_id:
                ids.append(tool_id)
    return ids


def _assistant_tool_use_row_indices(messages: list[dict[str, Any]]) -> dict[str, int]:
    """Map each assistant ``tool_use`` id to its Anthropic message row index.

    Args:
        messages (list[dict[str, Any]]): Anthropic-shaped message rows.

    Returns:
        dict[str, int]: ``tool_use`` id → zero-based row index.

    Examples:
        >>> _assistant_tool_use_row_indices([
        ...     {"role": "assistant", "content": [
        ...         {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...     ]},
        ... ])["t1"]
        0
    """
    indices: dict[str, int] = {}
    for idx, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        for block in _anthropic_message_blocks(msg.get("content")):
            if block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            if isinstance(tool_id, str) and tool_id:
                indices[tool_id] = idx
    return indices


def replay_stubs_are_same_turn_only(
    *,
    projected: list[dict[str, Any]],
    repaired: list[dict[str, Any]],
    turn_message_start_index: int,
) -> bool:
    """Return whether every transport replay stub targets the current turn only.

    Args:
        projected (list[dict[str, Any]]): Raw Anthropic rows before repair.
        repaired (list[dict[str, Any]]): Rows after ``repair_anthropic_tool_pairing``.
        turn_message_start_index (int): Anthropic row index where this turn begins.

    Returns:
        bool: ``True`` when all stubbed ids originate at or after the turn boundary.

    Examples:
        >>> replay_stubs_are_same_turn_only(
        ...     projected=[
        ...         {"role": "user", "content": "hi"},
        ...         {"role": "assistant", "content": [
        ...             {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...         ]},
        ...     ],
        ...     repaired=repair_anthropic_tool_pairing([
        ...         {"role": "user", "content": "hi"},
        ...         {"role": "assistant", "content": [
        ...             {"type": "tool_use", "id": "t1", "name": "read", "input": {}},
        ...         ]},
        ...     ]),
        ...     turn_message_start_index=1,
        ... )
        True
    """
    stub_ids = _replay_stub_tool_use_ids(repaired)
    if not stub_ids:
        return False
    coalesced = coalesce_adjacent_anthropic_messages(projected)
    indices = _assistant_tool_use_row_indices(coalesced)
    return all(
        tool_id in indices and indices[tool_id] >= turn_message_start_index for tool_id in stub_ids
    )


def prepare_anthropic_messages_for_transport(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Coalesce, strip orphan tool_use blocks, and sanitize Anthropic messages before POST.

    Args:
        messages (list[dict[str, Any]]): Raw projected Anthropic rows.

    Returns:
        list[dict[str, Any]]: Transport-safe ``messages`` list.

    Examples:
        >>> prepare_anthropic_messages_for_transport([])
        []
    """
    coalesced = coalesce_adjacent_anthropic_messages(messages)
    stripped_rows, _stripped_count = strip_orphan_tool_use_blocks(coalesced)
    # Symmetric pass: drop any ``tool_result`` whose ``tool_use`` was just stripped, so the
    # MiniMax Anthropic wire never sees an orphan result (error 2013). Must run AFTER the
    # tool_use strip so its removals are reflected in the live tool_use id set.
    deorphaned_rows, _orphan_results = strip_orphan_tool_result_blocks(stripped_rows)
    merged = coalesce_adjacent_anthropic_messages(deorphaned_rows)
    return sanitize_anthropic_messages(merged)


def append_owner_steer_model_request(
    messages: list[ModelMessage],
    steer_text: str,
) -> list[ModelMessage]:
    """Append buffered owner steer without creating consecutive user Anthropic rows.

    Args:
        messages (list[ModelMessage]): Pydantic AI history for the upcoming provider round.
        steer_text (str): Buffered ``/steer`` body (without the ``[Owner steer]`` prefix).

    Returns:
        list[ModelMessage]: History with steer merged into the trailing ``ModelRequest``
            when present.

    Examples:
        >>> out = append_owner_steer_model_request(
        ...     [ModelRequest(parts=[UserPromptPart(content="hi")])],
        ...     "retry",
        ... )
        >>> out[0].parts[1].content
        '[Owner steer] retry'
    """
    steer_part = UserPromptPart(content=f"[Owner steer] {steer_text}")
    if messages and isinstance(messages[-1], ModelRequest):
        last = messages[-1]
        merged_parts = [*last.parts, steer_part]
        return [*messages[:-1], ModelRequest(parts=merged_parts)]
    return [*messages, ModelRequest(parts=[steer_part])]


def sanitize_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop empty text blocks and ensure each message has ≥1 content block (P7).

    Args:
        messages (list[dict[str, Any]]): Anthropic ``messages`` list.

    Returns:
        list[dict[str, Any]]: Messages safe to POST (empty messages omitted).

    Examples:
        >>> sanitize_anthropic_messages([
        ...     {"role": "user", "content": [{"type": "text", "text": ""}]},
        ...     {"role": "assistant", "content": [
        ...         {"type": "text", "text": "a"},
        ...         {"type": "text", "text": "b"},
        ...     ]},
        ... ])
        [{'role': 'assistant', 'content': 'a\\n\\nb'}]
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            if content.strip():
                out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        blocks = merge_adjacent_anthropic_text_blocks(
            [b for b in content if isinstance(b, dict)],
        )
        if not blocks:
            continue
        if len(blocks) == 1 and blocks[0].get("type") == "text":
            out.append({"role": role, "content": blocks[0]["text"]})
        else:
            out.append({"role": role, "content": blocks})
    return out


def pydantic_messages_to_anthropic_messages(
    messages: list[ModelMessage],
) -> list[dict[str, Any]]:
    """Project pydantic-ai history to Anthropic ``messages`` JSON.

    Args:
        messages (list[ModelMessage]): Pydantic AI message history.

    Returns:
        list[dict[str, Any]]: Anthropic Messages API ``messages`` list.

    Examples:
        >>> pydantic_messages_to_anthropic_messages([])
        []
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            blocks: list[dict[str, Any]] = []
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    text = _user_prompt_to_text(part.content)
                    if text:
                        blocks.append({"type": "text", "text": text})
                elif isinstance(part, BaseToolReturnPart):
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": part.tool_call_id,
                            "content": part.model_response_str(),
                        },
                    )
            if blocks:
                if len(blocks) == 1 and blocks[0].get("type") == "text":
                    out.append({"role": "user", "content": blocks[0]["text"]})
                else:
                    out.append({"role": "user", "content": blocks})
        elif isinstance(msg, ModelResponse):
            metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
            raw_anthropic = metadata.get("anthropic_content")
            if isinstance(raw_anthropic, list) and raw_anthropic:
                blocks = merge_adjacent_anthropic_text_blocks(
                    [b for b in raw_anthropic if isinstance(b, dict)],
                )
                if blocks:
                    if len(blocks) == 1 and blocks[0].get("type") == "text":
                        out.append({"role": "assistant", "content": blocks[0]["text"]})
                    else:
                        out.append({"role": "assistant", "content": blocks})
                    continue
            blocks = []
            for resp_part in msg.parts:
                if isinstance(resp_part, ThinkingPart):
                    think_block: dict[str, Any] = {
                        "type": "thinking",
                        "thinking": resp_part.content,
                    }
                    if resp_part.signature:
                        think_block["signature"] = resp_part.signature
                    if resp_part.provider_details:
                        for key, value in resp_part.provider_details.items():
                            if key not in think_block:
                                think_block[key] = value
                    blocks.append(think_block)
                elif isinstance(resp_part, TextPart):
                    if resp_part.content:
                        blocks.append({"type": "text", "text": resp_part.content})
                elif isinstance(resp_part, ToolCallPart):
                    args = resp_part.args
                    if isinstance(args, dict):
                        tool_input = args
                    elif isinstance(args, str) and args.strip():
                        try:
                            tool_input = json.loads(args)
                        except json.JSONDecodeError:
                            tool_input = {"raw": args}
                    else:
                        tool_input = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": resp_part.tool_call_id,
                            "name": resp_part.tool_name,
                            "input": tool_input,
                        },
                    )
            if blocks:
                blocks = merge_adjacent_anthropic_text_blocks(blocks)
                if len(blocks) == 1 and blocks[0].get("type") == "text":
                    out.append({"role": "assistant", "content": blocks[0]["text"]})
                else:
                    out.append({"role": "assistant", "content": blocks})
    return sanitize_anthropic_messages(coalesce_adjacent_anthropic_messages(out))


def pydantic_messages_to_bedrock_converse(
    messages: list[ModelMessage],
) -> list[dict[str, Any]]:
    """Project pydantic-ai history to Bedrock Converse ``messages`` JSON.

    Args:
        messages (list[ModelMessage]): Pydantic AI message history.

    Returns:
        list[dict[str, Any]]: Bedrock Converse message list with text/tool blocks.

    Examples:
        >>> pydantic_messages_to_bedrock_converse([])
        []
    """
    anthropic_msgs = pydantic_messages_to_anthropic_messages(messages)
    out: list[dict[str, Any]] = []
    for row in anthropic_msgs:
        role = str(row.get("role", "user"))
        content = row.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": [{"text": content}]})
            continue
        if isinstance(content, list):
            blocks: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "text":
                    blocks.append({"text": str(block.get("text", ""))})
                elif kind == "tool_use":
                    blocks.append(
                        {
                            "toolUse": {
                                "toolUseId": str(block.get("id", uuid.uuid4().hex)),
                                "name": str(block.get("name", "")),
                                "input": block.get("input")
                                if isinstance(block.get("input"), dict)
                                else {},
                            },
                        },
                    )
                elif kind == "tool_result":
                    blocks.append(
                        {
                            "toolResult": {
                                "toolUseId": str(block.get("tool_use_id", "")),
                                "content": [{"text": str(block.get("content", ""))}],
                            },
                        },
                    )
            out.append({"role": role, "content": blocks})
    return out


def _anthropic_tools_payload(tool_defs: list[PAToolDefinition]) -> list[dict[str, Any]]:
    """Project pydantic-ai tool definitions into Anthropic ``tools`` JSON.

    Args:
        tool_defs (list[PAToolDefinition]): Tool definitions exposed for the round.

    Returns:
        list[dict[str, Any]]: Anthropic tool entries.

    Examples:
        >>> _anthropic_tools_payload([])
        []
    """
    tools: list[dict[str, Any]] = []
    for td in tool_defs:
        tools.append(
            {
                "name": td.name,
                "description": td.description or "",
                "input_schema": dict(td.parameters_json_schema),
            },
        )
    return tools


def _bedrock_tools_payload(tool_defs: list[PAToolDefinition]) -> list[dict[str, Any]]:
    """Project pydantic-ai tool definitions into Bedrock Converse ``toolConfig`` tools.

    Args:
        tool_defs (list[PAToolDefinition]): Tool definitions exposed for the round.

    Returns:
        list[dict[str, Any]]: Bedrock tool specification entries.

    Examples:
        >>> _bedrock_tools_payload([])
        []
    """
    tools: list[dict[str, Any]] = []
    for td in tool_defs:
        tools.append(
            {
                "toolSpec": {
                    "name": td.name,
                    "description": td.description or "",
                    "inputSchema": {"json": dict(td.parameters_json_schema)},
                },
            },
        )
    return tools


def openai_completion_to_model_response(data: dict[str, Any]) -> ModelResponse:
    """Translate a chat completion JSON blob into pydantic-ai ``ModelResponse``.

    Symmetric with :func:`anthropic_completion_to_model_response`: maps MiniMax
    ``reasoning_content`` to a ``ThinkingPart`` and recovers XML tool calls that
    leaked into ``content`` (``<invoke>`` / ``<minimax:tool_call>``) into structured
    ``ToolCallPart``s via :func:`_apply_xml_tool_recovery`. Without this the XML
    either leaks raw to the operator or is stripped by outbound hygiene, emptying an
    otherwise-valid turn (transcript-review-2026-06-22; `specs/14-executor-tier-b.md` §2.3).

    Args:
        data (dict[str, Any]): OpenAI chat completion response payload.

    Returns:
        ModelResponse: Pydantic AI response with thinking / text / tool call parts and usage.

    Examples:
        >>> resp = openai_completion_to_model_response({})
        >>> len(resp.parts)
        1
        >>> r = openai_completion_to_model_response(
        ...     {"choices": [{"message": {"content":
        ...      '<invoke name="read"><parameter name="file_path">a.py</parameter></invoke>'}}]})
        >>> [type(p).__name__ for p in r.parts]
        ['ToolCallPart']
        >>> t = openai_completion_to_model_response(
        ...     {"choices": [{"message": {"reasoning_content": "plan", "content": "hi"}}]})
        >>> [type(p).__name__ for p in t.parts]
        ['ThinkingPart', 'TextPart']
    """

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ModelResponse(parts=[TextPart(content="")], usage=RequestUsage())
    choice0 = choices[0]
    if not isinstance(choice0, dict):
        return ModelResponse(parts=[TextPart(content="")], usage=RequestUsage())
    msg = choice0.get("message")
    if not isinstance(msg, dict):
        return ModelResponse(parts=[TextPart(content="")], usage=RequestUsage())
    parts: list[ModelResponsePart] = []
    # MiniMax (OpenAI-wire, ``openai_thinking`` enabled) returns chain-of-thought in a
    # ``reasoning_content`` field parallel to ``content``. Emit it as a ThinkingPart first so
    # ordered history / display salvage match the Anthropic-wire path.
    reasoning = msg.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        parts.append(ThinkingPart(content=reasoning, provider_name="minimax"))
    raw_tools = msg.get("tool_calls")
    if isinstance(raw_tools, list):
        for tc in raw_tools:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function")
            fn_name = ""
            fn_args = "{}"
            if isinstance(fn, dict):
                fn_name = str(fn.get("name", ""))
                raw_arg = fn.get("arguments")
                if isinstance(raw_arg, str):
                    fn_args = raw_arg
                elif raw_arg is not None:
                    fn_args = json.dumps(raw_arg, separators=(",", ":"), ensure_ascii=False)
            parts.append(
                ToolCallPart(
                    tool_name=fn_name,
                    args=fn_args,
                    tool_call_id=str(tc.get("id", uuid.uuid4().hex)),
                ),
            )
    content = msg.get("content")
    if content is not None and str(content).strip() != "":
        parts.append(TextPart(content=str(content)))
    # MiniMax intermittently emits tool calls as XML inside ``content`` instead of structured
    # ``tool_calls`` on the chat_completions wire. Recover them into ToolCallParts so the agent
    # executes the tool, rather than leaking the raw XML or having outbound hygiene strip it to
    # an empty turn (transcript-review-2026-06-22). No-op when native ``tool_calls`` exist.
    parts = _apply_xml_tool_recovery(parts)
    if not parts:
        parts.append(TextPart(content=""))
    usage = RequestUsage()
    raw_usage = data.get("usage")
    if isinstance(raw_usage, dict):
        inp = raw_usage.get("prompt_tokens") or raw_usage.get("input_tokens")
        out_t = raw_usage.get("completion_tokens") or raw_usage.get("output_tokens")
        try:
            usage = RequestUsage(
                input_tokens=int(inp) if inp is not None else 0,
                output_tokens=int(out_t) if out_t is not None else 0,
            )
        except (TypeError, ValueError):
            usage = RequestUsage()
    return ModelResponse(parts=parts, usage=usage)


def _parse_minimax_xml_tool_calls(text: str) -> tuple[list[dict[str, str]], str]:
    """Recover MiniMax XML tool blocks embedded in text when native ``tool_use`` is omitted.

    MiniMax (Anthropic-compatible) intermittently returns tool calls as XML text
    inside a ``text`` block instead of structured ``tool_use`` blocks. Without
    recovery the agent loop sees only prose, executes nothing, and stalls. Ported
    from pyclaww ``MinimaxProvider``. Handles two shapes plus bare ``<invoke>``:

    Format A (invoke-style)::

        <minimax:tool_call><invoke name="read">
        <parameter name="file_path">skills/foo.py</parameter></invoke></minimax:tool_call>

    Format B (tag-per-tool)::

        <minimax:toolcall><read>path: skills/foo.py</read></minimax:toolcall>

    Args:
        text (str): Assistant text possibly containing XML tool markup.

    Returns:
        tuple[list[dict[str, str]], str]: ``(tool_calls, stripped_text)`` where each
        call has ``id`` / ``name`` / ``arguments`` (JSON string); ``stripped_text``
        has the consumed XML removed.

    Examples:
        >>> calls, rest = _parse_minimax_xml_tool_calls(
        ...     '<invoke name="read"><parameter name="file_path">a.py</parameter></invoke>')
        >>> calls[0]["name"], json.loads(calls[0]["arguments"])  # doctest: +ELLIPSIS
        ('read', {'file_path': 'a.py'})
        >>> _parse_minimax_xml_tool_calls("no tools here")
        ([], 'no tools here')
    """
    if not text:
        return [], text
    low = text.lower()
    if "<invoke" not in low and "minimax:tool_call" not in low and "minimax:toolcall" not in low:
        return [], text

    parsed: list[dict[str, str]] = []
    to_remove: list[str] = []
    nid = 0

    def extract_invokes(fragment: str, record_spans: bool) -> None:
        nonlocal nid
        for inv in re.finditer(
            r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</invoke>",
            fragment,
            re.DOTALL | re.IGNORECASE,
        ):
            if record_spans:
                to_remove.append(inv.group(0))
            nid += 1
            args: dict[str, str] = {}
            for pm in re.finditer(
                r"<parameter\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</parameter>",
                inv.group(2),
                re.DOTALL | re.IGNORECASE,
            ):
                args[pm.group(1).strip()] = pm.group(2).strip()
            parsed.append(
                {
                    "id": f"minimax-xml-{nid}",
                    "name": inv.group(1).strip().lower(),
                    "arguments": json.dumps(args),
                },
            )

    def extract_tag_per_tool(fragment: str) -> None:
        nonlocal nid
        skip_tags = frozenset(
            {
                "minimax",
                "br",
                "p",
                "div",
                "span",
                "random",
                "parameter",
                "invoke",
                "tool_call",
                "toolcall",
            },
        )
        positions: list[tuple[int, str]] = []
        for bm in re.finditer(r"<(\w+)[^>]*>", fragment, re.IGNORECASE):
            tag = bm.group(1).strip().lower()
            if tag not in skip_tags:
                positions.append((bm.start(), tag))
        primary_args = {
            "read": "file_path",
            "glob": "pattern",
            "grep": "pattern",
            "write": "file_path",
        }
        for idx, (start, tag_name) in enumerate(positions):
            end = positions[idx + 1][0] if idx + 1 < len(positions) else len(fragment)
            block = fragment[start:end]
            args: dict[str, str] = {}
            for pm in re.finditer(
                r"<parameter\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</parameter>",
                block,
                re.DOTALL | re.IGNORECASE,
            ):
                args[pm.group(1).strip()] = pm.group(2).strip()
            if not args:
                for raw_line in block.splitlines():
                    line = raw_line.strip()
                    if line.startswith("<") and ":" not in line:
                        continue
                    line = re.sub(r"</\w+>\s*$", "", line).strip()
                    if not line:
                        continue
                    line = re.sub(r"^<\w+[^>]*>\s*", "", line).strip()
                    if ":" in line:
                        key, _, val = line.partition(":")
                        if key.strip():
                            args[key.strip()] = val.strip()
                    elif line:
                        args[primary_args.get(tag_name, "input")] = line
            if args:
                nid += 1
                parsed.append(
                    {
                        "id": f"minimax-xml-{nid}",
                        "name": tag_name,
                        "arguments": json.dumps(args),
                    },
                )

    for m in re.finditer(
        r"<minimax:tool_call>\s*(.*?)\s*</minimax:tool_call>",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        to_remove.append(m.group(0))
        extract_invokes(m.group(1), record_spans=False)
    for m in re.finditer(
        r"<minimax:toolcall>\s*(.*?)\s*</minimax:toolcall>",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        to_remove.append(m.group(0))
        extract_tag_per_tool(m.group(1))
    if not parsed:
        extract_invokes(text, record_spans=True)
    if not parsed:
        return [], text

    stripped = text
    for seg in sorted(to_remove, key=len, reverse=True):
        stripped = stripped.replace(seg, "")
    return parsed, stripped.strip()


def _thinking_block_to_part(block: dict[str, Any]) -> ThinkingPart:
    """Map one Anthropic ``thinking`` content block to a pydantic-ai ``ThinkingPart``.

    Args:
        block (dict[str, Any]): Anthropic content block with ``type: thinking``.

    Returns:
        ThinkingPart: Ordered history part preserving signature and extra keys.

    Examples:
        >>> p = _thinking_block_to_part({"type": "thinking", "thinking": "plan", "signature": "s"})
        >>> p.content, p.signature, p.provider_name
        ('plan', 's', 'anthropic')
    """
    think = block.get("thinking", block.get("text", ""))
    signature = block.get("signature")
    extra = {
        key: value
        for key, value in block.items()
        if key not in ("type", "thinking", "text", "signature")
    }
    return ThinkingPart(
        content=str(think) if think else "",
        signature=str(signature) if signature is not None else None,
        provider_name="anthropic",
        provider_details=extra or None,
    )


def _tool_use_block_to_part(block: dict[str, Any]) -> ToolCallPart:
    """Map one Anthropic ``tool_use`` content block to a ``ToolCallPart``.

    Args:
        block (dict[str, Any]): Anthropic content block with ``type: tool_use``.

    Returns:
        ToolCallPart: Tool call part for pydantic-ai history.

    Examples:
        >>> p = _tool_use_block_to_part(
        ...     {"type": "tool_use", "id": "t1", "name": "read", "input": {"file_path": "a.py"}})
        >>> p.tool_name, p.tool_call_id
        ('read', 't1')
    """
    tool_input = block.get("input")
    if isinstance(tool_input, dict):
        arg_str = json.dumps(tool_input, separators=(",", ":"), ensure_ascii=False)
    else:
        arg_str = "{}"
    return ToolCallPart(
        tool_name=str(block.get("name", "")),
        args=arg_str,
        tool_call_id=str(block.get("id", uuid.uuid4().hex)),
    )


def _apply_xml_tool_recovery(parts: list[ModelResponsePart]) -> list[ModelResponsePart]:
    """Recover MiniMax XML tool calls from text parts when no native ``tool_use`` exists.

    Preserves non-text parts (e.g. ``ThinkingPart``) in their original order; replaces
    text blocks with stripped text (if any) followed by recovered ``ToolCallPart``s.

    Args:
        parts (list[ModelResponsePart]): Parts built from ordered Anthropic blocks.

    Returns:
        list[ModelResponsePart]: Parts unchanged, or with XML tool calls recovered.

    Examples:
        >>> _apply_xml_tool_recovery([])
        []
    """
    if any(isinstance(p, ToolCallPart) for p in parts):
        return parts
    combined = "\n".join(p.content for p in parts if isinstance(p, TextPart) and p.content).strip()
    if not combined:
        return parts
    xml_tool_calls, stripped = _parse_minimax_xml_tool_calls(combined)
    if not xml_tool_calls:
        return parts
    logger.debug(
        "minimax_xml_tool_calls_recovered count={} (native tool_use absent)",
        len(xml_tool_calls),
    )
    kept: list[ModelResponsePart] = [p for p in parts if not isinstance(p, TextPart)]
    if stripped.strip():
        kept.append(TextPart(content=stripped))
    for xtc in xml_tool_calls:
        kept.append(
            ToolCallPart(
                tool_name=xtc["name"],
                args=xtc["arguments"],
                tool_call_id=xtc["id"],
            ),
        )
    return kept


def _display_text_from_model_response(response: ModelResponse) -> str:
    """User-visible text from a resolved response (UI/streaming only).

    Joins ``TextPart`` content. When there is no text and no ``ToolCallPart``, salvages
    an answer from ``ThinkingPart`` via :func:`_recover_answer_from_thinking` — never
    substitutes thinking for history; never salvages when tool calls are present.

    Args:
        response (ModelResponse): Resolved assistant response.

    Returns:
        str: Text to show the operator, or ``""``.

    Examples:
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> _display_text_from_model_response(ModelResponse(parts=[TextPart(content="hi")]))
        'hi'
        >>> _display_text_from_model_response(ModelResponse(parts=[
        ...     ThinkingPart(content='{"intent": "GREETING"}', provider_name="anthropic")]))
        '{"intent": "GREETING"}'
    """
    text = "\n\n".join(p.content for p in response.parts if isinstance(p, TextPart) and p.content)
    if text.strip():
        return text
    if any(isinstance(p, ToolCallPart) for p in response.parts):
        return ""
    thinking_chunks = [
        p.content for p in response.parts if isinstance(p, ThinkingPart) and p.content
    ]
    if thinking_chunks:
        return _recover_answer_from_thinking("\n".join(thinking_chunks))
    return ""


def _recover_answer_from_thinking(thinking_text: str) -> str:
    """Recover a final answer from MiniMax ``thinking`` blocks when text is empty.

    MiniMax M2 reasoning sometimes leaves ``content`` text empty while emitting the
    real answer inside ``thinking``. For classification prompts the JSON object is
    embedded; for short answers (e.g. a tier letter) the last line carries it.
    Ported from pyclaww ``MinimaxProvider``.

    Args:
        thinking_text (str): Concatenated thinking-block text.

    Returns:
        str: Recovered answer, or ``""`` when nothing usable is found.

    Examples:
        >>> _recover_answer_from_thinking('reasoning... {"intent": "GREETING"} done')
        '{"intent": "GREETING"}'
        >>> _recover_answer_from_thinking("weighing options\\nB")
        'B'
        >>> _recover_answer_from_thinking("just rambling at length here")
        ''
    """
    match = re.search(r'\{[^{}]*"intent"[^{}]*\}', thinking_text)
    if match:
        return match.group(0)
    stripped = thinking_text.strip()
    if stripped:
        last_line = stripped.splitlines()[-1].strip()
        if 0 < len(last_line) <= 10:
            return last_line
    return ""


def anthropic_completion_to_model_response(data: dict[str, Any]) -> ModelResponse:
    """Translate an Anthropic Messages JSON blob into pydantic-ai ``ModelResponse``.

    Walks ``content`` **in provider order**, emitting ``ThinkingPart``, ``TextPart``, and
    ``ToolCallPart`` so multi-turn MiniMax tool/reasoning history round-trips faithfully.
    Display salvage from ``thinking`` is **not** folded into history — use
    :func:`_display_text_from_model_response` for UI/streaming. When no native
    ``tool_use`` is present, parses XML tool calls embedded in text blocks.

    Args:
        data (dict[str, Any]): Anthropic Messages API response payload.

    Returns:
        ModelResponse: Pydantic AI response with ordered parts, usage, and optional
            ``metadata["anthropic_content"]`` for exact replay.

    Examples:
        >>> resp = anthropic_completion_to_model_response({"content": []})
        >>> len(resp.parts)
        1
        >>> r = anthropic_completion_to_model_response(
        ...     {"content": [{"type": "text",
        ...      "text": '<invoke name="read"><parameter name="file_path">a.py'
        ...              '</parameter></invoke>'}]})
        >>> [type(p).__name__ for p in r.parts]
        ['ToolCallPart']
        >>> ordered = anthropic_completion_to_model_response({
        ...     "content": [
        ...         {"type": "thinking", "thinking": "plan", "signature": "sig"},
        ...         {"type": "tool_use", "id": "t1", "name": "read",
        ...          "input": {"file_path": "a.py"}},
        ...     ]})
        >>> [type(p).__name__ for p in ordered.parts]
        ['ThinkingPart', 'ToolCallPart']
    """
    parts: list[ModelResponsePart] = []
    raw_content = data.get("content")
    if isinstance(raw_content, list):
        for block in raw_content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "thinking":
                think = block.get("thinking", block.get("text", ""))
                if think:
                    parts.append(_thinking_block_to_part(block))
            elif kind == "text":
                text = block.get("text")
                if text is not None and str(text).strip() != "":
                    parts.append(TextPart(content=str(text)))
            elif kind == "tool_use":
                parts.append(_tool_use_block_to_part(block))
    elif isinstance(raw_content, str) and raw_content.strip():
        parts.append(TextPart(content=raw_content))

    parts = _apply_xml_tool_recovery(parts)

    if not raw_content:
        stop = data.get("stop_reason") or data.get("stop_sequence")
        logger.warning(
            "anthropic_empty_content model={} stop={} keys={}",
            data.get("model", "?"),
            stop,
            list(data.keys()),
        )

    if not parts:
        parts.append(TextPart(content=""))

    usage = RequestUsage()
    raw_usage = data.get("usage")
    if isinstance(raw_usage, dict):
        inp = raw_usage.get("input_tokens")
        out_t = raw_usage.get("output_tokens")
        try:
            usage = RequestUsage(
                input_tokens=int(inp) if inp is not None else 0,
                output_tokens=int(out_t) if out_t is not None else 0,
            )
        except (TypeError, ValueError):
            usage = RequestUsage()
    metadata: dict[str, Any] | None = None
    if isinstance(raw_content, list) and raw_content:
        metadata = {"anthropic_content": list(raw_content)}
    stop_reason = data.get("stop_reason") or data.get("stop_sequence")
    if stop_reason is not None:
        metadata = dict(metadata or {})
        metadata["stop_reason"] = str(stop_reason)
    return ModelResponse(parts=parts, usage=usage, metadata=metadata)


_EMPTY_CONTENT_NUDGE_USER_TEXT: Final[str] = (
    "You returned no assistant content. Reply now with the required answer or valid JSON."
)
_EMPTY_CONTENT_NUDGE_TEMPERATURE: Final[float] = 0.4


def _anthropic_payload_has_usable_content(payload: dict[str, Any]) -> bool:
    """Return True when an Anthropic payload carries text, thinking, or tool_use blocks.

    Args:
        payload (dict[str, Any]): Anthropic Messages API response body.

    Returns:
        bool: True when at least one content block has usable body text or a tool call.

    Examples:
        >>> _anthropic_payload_has_usable_content({"content": []})
        False
        >>> _anthropic_payload_has_usable_content(
        ...     {"content": [{"type": "text", "text": "hi"}]})
        True
    """
    raw = payload.get("content")
    if not isinstance(raw, list) or not raw:
        return False
    for block in raw:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and str(block.get("text", "")).strip():
            return True
        if kind == "thinking":
            think = block.get("thinking", block.get("text", ""))
            if str(think).strip():
                return True
        if kind == "tool_use":
            return True
    return False


def is_anthropic_empty_end_turn(payload: dict[str, Any]) -> bool:
    """Detect MiniMax-style empty ``content`` with ``stop_reason=end_turn``.

    Args:
        payload (dict[str, Any]): Anthropic Messages API response body.

    Returns:
        bool: True when the assistant ended the turn without usable content blocks.

    Examples:
        >>> is_anthropic_empty_end_turn({"content": [], "stop_reason": "end_turn"})
        True
        >>> is_anthropic_empty_end_turn(
        ...     {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})
        False
    """
    stop = payload.get("stop_reason")
    if stop not in (None, "end_turn"):
        return False
    return not _anthropic_payload_has_usable_content(payload)


def bedrock_converse_to_model_response(data: dict[str, Any]) -> ModelResponse:
    """Translate a Bedrock Converse JSON blob into pydantic-ai ``ModelResponse``.

    Args:
        data (dict[str, Any]): Bedrock Converse API response payload.

    Returns:
        ModelResponse: Pydantic AI response with text / tool call parts and usage.

    Examples:
        >>> resp = bedrock_converse_to_model_response({})
        >>> len(resp.parts)
        1
    """
    parts: list[ModelResponsePart] = []
    output = data.get("output")
    if isinstance(output, dict):
        message = output.get("message")
        if isinstance(message, dict):
            raw_content = message.get("content")
            if isinstance(raw_content, list):
                for block in raw_content:
                    if not isinstance(block, dict):
                        continue
                    if "text" in block:
                        text = block.get("text")
                        if text is not None and str(text).strip() != "":
                            parts.append(TextPart(content=str(text)))
                    tool_use = block.get("toolUse")
                    if isinstance(tool_use, dict):
                        tool_input = tool_use.get("input")
                        if isinstance(tool_input, dict):
                            arg_str = json.dumps(
                                tool_input, separators=(",", ":"), ensure_ascii=False
                            )
                        else:
                            arg_str = "{}"
                        parts.append(
                            ToolCallPart(
                                tool_name=str(tool_use.get("name", "")),
                                args=arg_str,
                                tool_call_id=str(tool_use.get("toolUseId", uuid.uuid4().hex)),
                            ),
                        )
    if not parts:
        parts.append(TextPart(content=""))
    usage = RequestUsage()
    raw_usage = data.get("usage")
    if isinstance(raw_usage, dict):
        inp = raw_usage.get("inputTokens") or raw_usage.get("input_tokens")
        out_t = raw_usage.get("outputTokens") or raw_usage.get("output_tokens")
        try:
            usage = RequestUsage(
                input_tokens=int(inp) if inp is not None else 0,
                output_tokens=int(out_t) if out_t is not None else 0,
            )
        except (TypeError, ValueError):
            usage = RequestUsage()
    return ModelResponse(parts=parts, usage=usage)


def _wire_tool_defs(
    tool_defs: list[PAToolDefinition],
    allowed_tool_names: frozenset[str] | MutableToolAllowlist | None,
) -> list[PAToolDefinition]:
    """Filter tool definitions sent to the provider by the per-turn allowlist (P3).

    The pydantic-ai agent may register the full registry for auto-grant dispatch, but
    only triager-bound (plus auto-granted) tools are exposed on the wire each round.

    Args:
        tool_defs (list[PAToolDefinition]): Candidate tool definitions for the round.
        allowed_tool_names (frozenset[str] | MutableToolAllowlist | None): Effective
            allowlist. ``None`` disables filtering.

    Returns:
        list[PAToolDefinition]: Subset of ``tool_defs`` permitted on the wire.

    Examples:
        >>> from pydantic_ai.tools import ToolDefinition as PAToolDefinition
        >>> defs = [
        ...     PAToolDefinition(name="read", description="", parameters_json_schema={}),
        ...     PAToolDefinition(name="glob", description="", parameters_json_schema={}),
        ... ]
        >>> out = _wire_tool_defs(defs, frozenset({"read"}))
        >>> [d.name for d in out]
        ['read']
    """
    if allowed_tool_names is None:
        return tool_defs
    if isinstance(allowed_tool_names, MutableToolAllowlist):
        allowed = allowed_tool_names.effective
    else:
        allowed = allowed_tool_names
    return [td for td in tool_defs if td.name in allowed]


def _openai_tools_payload(tool_defs: list[PAToolDefinition]) -> list[dict[str, Any]]:
    """Project pydantic-ai tool definitions into OpenAI ``tools`` JSON payload.

    Args:
        tool_defs (list[PAToolDefinition]): Tool definitions exposed for the round.

    Returns:
        list[dict[str, Any]]: Function-call tool entries ready for the provider request.

    Examples:
        >>> _openai_tools_payload([])
        []
    """
    tools: list[dict[str, Any]] = []
    for td in tool_defs:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description or "",
                    "parameters": dict(td.parameters_json_schema),
                },
            },
        )
    return tools


_TOOL_MARKUP_MARKERS: tuple[str, ...] = ("<invoke", "<minimax:tool_call", "<minimax:toolcall")
"""Sentinels that mark MiniMax XML tool-call markup leaking into a text block."""


def _extract_upstream_error_body(exc: BaseException, *, limit: int = 2000) -> str:
    """Best-effort extract of an upstream HTTP error body for diagnostics.

    Streaming LLM rounds that fail with an HTTP 4xx/5xx (e.g. MiniMax's
    Anthropic-compatible endpoint returning ``400 Bad Request``) only surface the
    status line in ``str(exc)``. The actual rejection reason lives in the response
    body, so we pull it (truncated) when the exception carries an httpx-style
    ``response``. Returns ``""`` when no body is recoverable.

    Args:
        exc (BaseException): The exception raised by the transport.
        limit (int): Max characters of body to return.

    Returns:
        str: Truncated response body, or ``""`` when unavailable.

    Examples:
        >>> _extract_upstream_error_body(ValueError("boom"))
        ''
    """
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    body = ""
    try:
        body = response.text
    except Exception:  # pragma: no cover - defensive: streamed/closed body
        try:
            body = bytes(getattr(response, "content", b"")).decode("utf-8", "replace")
        except Exception:  # pragma: no cover - last resort
            return ""
    if not isinstance(body, str):
        return ""
    body = body.strip()
    return body[:limit]


def _has_tool_markup(text: str) -> bool:
    """Whether accumulated text contains MiniMax XML tool-call markup.

    Used by the streaming path to stop forwarding live text deltas once the model
    starts emitting an XML tool call in a ``text`` block (the converter recovers
    the call post-hoc; the raw markup must not flash in the Telegram placeholder).

    Args:
        text (str): Accumulated streamed text so far.

    Returns:
        bool: ``True`` when a tool-markup sentinel is present.

    Examples:
        >>> _has_tool_markup('hello <invoke name="read">')
        True
        >>> _has_tool_markup("plain answer with no markup")
        False
    """
    low = text.lower()
    return any(marker in low for marker in _TOOL_MARKUP_MARKERS)


def _tool_call_deltas(tool_parts: list[ToolCallPart]) -> DeltaToolCalls:
    """Project resolved ``ToolCallPart``s into pydantic-ai streaming ``DeltaToolCalls``.

    Args:
        tool_parts (list[ToolCallPart]): Tool calls from a resolved response.

    Returns:
        DeltaToolCalls: Index-keyed deltas the FunctionModel stream can yield.

    Examples:
        >>> from pydantic_ai.messages import ToolCallPart
        >>> d = _tool_call_deltas([ToolCallPart(tool_name="read", args="{}", tool_call_id="a")])
        >>> d[0].name
        'read'
    """
    return {
        index: DeltaToolCall(
            name=part.tool_name,
            json_args=part.args_as_json_str(),
            tool_call_id=part.tool_call_id,
        )
        for index, part in enumerate(tool_parts)
    }


def _model_response_for_wire(wire: str, payload: dict[str, Any]) -> ModelResponse:
    """Run the wire-appropriate ``*_to_model_response`` converter on a payload.

    Both the non-streaming ``complete`` path and the streaming ``complete_stream``
    final payload go through the same converter so MiniMax XML / thinking recovery
    is identical for both (`specs/14-executor-tier-b.md` §2.3).

    Args:
        wire (str): ``chat_completions`` | ``anthropic`` | ``bedrock``.
        payload (dict[str, Any]): Provider-shaped completion payload.

    Returns:
        ModelResponse: Parsed pydantic-ai response.

    Examples:
        >>> len(_model_response_for_wire("anthropic", {"content": []}).parts)
        1
    """
    if wire == "chat_completions":
        return openai_completion_to_model_response(payload)
    if wire == "anthropic":
        return anthropic_completion_to_model_response(payload)
    return bedrock_converse_to_model_response(payload)


async def _response_to_stream_deltas(
    response: ModelResponse,
) -> AsyncIterator[str | DeltaToolCalls]:
    """Yield streaming deltas from a fully-resolved response (fallback path).

    When real SSE streaming could not start, the FunctionModel falls back to a
    single ``complete`` round-trip and replays its parts as one batch of deltas so
    pydantic-ai still assembles the right response.

    Args:
        response (ModelResponse): Resolved non-streaming response.

    Yields:
        str | DeltaToolCalls: Tool-call deltas when present, else the answer text.

    Returns:
        collections.abc.AsyncIterator[str | DeltaToolCalls]: Async generator of deltas.

    Examples:
        >>> import asyncio
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> async def _run():
        ...     return [d async for d in _response_to_stream_deltas(
        ...         ModelResponse(parts=[TextPart(content="hi")]))]
        >>> asyncio.run(_run())
        ['hi']
    """
    tool_parts = [p for p in response.parts if isinstance(p, ToolCallPart)]
    if tool_parts:
        yield _tool_call_deltas(tool_parts)
        return
    display = _display_text_from_model_response(response)
    if display:
        yield display


def build_llm_request_metadata(
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    workspace_id: str | None = None,
    agent: str | None = None,
    executor_tier: str | None = None,
) -> dict[str, str]:
    """Build redaction-safe MiniMax ``metadata`` correlation fields (D2).

    Only whitelisted scalar keys are included; values pass through the default
    trace redaction policy so secrets and high-entropy literals are stripped.

    Args:
        session_id (str | None): Gateway session id.
        turn_id (str | None): Turn / correlation id.
        user_id (str | None): Channel user id.
        channel (str | None): Active channel key (``telegram``, ``webchat``, …).
        workspace_id (str | None): Workspace identifier.
        agent (str | None): ``LLM_params_config.json`` agent key (``tier_b``, …).
        executor_tier (str | None): Executor tier label (``B``, ``C``, …).

    Returns:
        dict[str, str]: Non-empty string fields safe to attach to provider requests.

    Examples:
        >>> meta = build_llm_request_metadata(session_id="s1", turn_id="t1", channel="telegram")
        >>> meta["session_id"], meta["channel"]
        ('s1', 'telegram')
    """
    raw: dict[str, object] = {}
    for key in _LLM_REQUEST_METADATA_KEYS:
        value = locals()[key]
        if value is None:
            continue
        text = str(value).strip()
        if text:
            raw[key] = text
    if not raw:
        return {}
    policy = TraceRedactionPolicy.from_defaults()
    redacted = redact_attrs(raw, policy)
    return {str(k): str(v) for k, v in redacted.items() if v not in (None, "", "<redacted>")}


@dataclasses.dataclass
class TriagerBoundToolChoiceContext:
    """Mutable per-turn state for triager-bound ``tool_choice`` escalation (tier B).

    When the triager binds tools/skills, tier B starts with Anthropic ``{"type": "any"}``
    (OpenAI ``"required"``) until :func:`triager_bound_tools_satisfied` is true, then
    relaxes to ``auto`` for synthesis rounds.
    """

    bound_tools: frozenset[str] = dataclasses.field(default_factory=frozenset)
    bound_skills: frozenset[str] = dataclasses.field(default_factory=frozenset)
    must_satisfy_tools: frozenset[str] = dataclasses.field(default_factory=frozenset)
    successful_tools_called: set[str] = dataclasses.field(default_factory=set)
    successful_skills_called: set[str] = dataclasses.field(default_factory=set)
    codemode_bound_tools_called: set[str] = dataclasses.field(default_factory=set)

    def has_bindings(self) -> bool:
        """Return whether the triager bound any tools or skills this turn.

        Returns:
            bool: ``True`` when ``bound_tools`` or ``bound_skills`` is non-empty.

        Examples:
            >>> TriagerBoundToolChoiceContext(bound_tools=frozenset({"log_query"})).has_bindings()
            True
            >>> TriagerBoundToolChoiceContext().has_bindings()
            False
        """
        return bool(self.bound_tools or self.bound_skills)

    def satisfied(self) -> bool:
        """Return whether at least one bound tool or skill succeeded (G0 / D0b).

        Returns:
            bool: ``True`` when a bound registry tool, skill, or CodeMode trace hit succeeded.

        Examples:
            >>> ctx = TriagerBoundToolChoiceContext(bound_tools=frozenset({"log_query"}))
            >>> ctx.satisfied()
            False
            >>> ctx.successful_tools_called.add("log_query")
            >>> ctx.satisfied()
            True
        """
        successful = frozenset(self.successful_tools_called)
        if _bound_meta_tool_mandate_satisfied(tuple(self.bound_tools), successful):
            return True
        if self.must_satisfy_tools and not (self.must_satisfy_tools & successful):
            return False
        return triager_bound_tools_satisfied(
            bound_tools=tuple(self.bound_tools),
            bound_skills=tuple(self.bound_skills),
            successful_tools_called=successful,
            successful_skills_called=frozenset(self.successful_skills_called),
            codemode_bound_tools_called=frozenset(self.codemode_bound_tools_called),
        )

    def anthropic_tool_choice_type(self) -> Literal["auto", "any"]:
        """Resolve Anthropic-shaped ``tool_choice.type`` for the next LLM round.

        Returns:
            Literal["auto", "any"]: ``any`` until a bound tool/skill succeeds, then ``auto``.

        Examples:
            >>> TriagerBoundToolChoiceContext(
            ...     bound_tools=frozenset({"log_query"}),
            ... ).anthropic_tool_choice_type()
            'any'
        """
        if not self.has_bindings() or self.satisfied():
            return "auto"
        return "any"

    def openai_tool_choice(self) -> Literal["auto", "required"]:
        """Resolve OpenAI chat-completions ``tool_choice`` for the next LLM round.

        Returns:
            Literal["auto", "required"]: ``required`` until a bound tool/skill succeeds.

        Examples:
            >>> TriagerBoundToolChoiceContext(
            ...     bound_tools=frozenset({"log_query"}),
            ... ).openai_tool_choice()
            'required'
        """
        if not self.has_bindings() or self.satisfied():
            return "auto"
        return "required"


def apply_minimax_anthropic_request_hygiene(
    req: dict[str, Any],
    *,
    model_id: str,
    agent: str,
    content_root: Path | None,
    has_tools: bool,
    session_id: str | None = None,
    turn_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    workspace_id: str | None = None,
    executor_tier: str | None = None,
    thinking_via_capability: bool = False,
    tool_choice_type: Literal["auto", "any"] | None = None,
) -> None:
    """Apply MiniMax anthropic-wire request param hygiene in place (D2).

    Drops ignored ``top_k``, sets ``tool_choice`` when tools are present (default
    ``{"type": "auto"}``; callers may pass ``tool_choice_type="any"`` for triager-bound
    enforcement rounds),
    optionally attaches config-gated ``thinking``, and adds redaction-safe
    ``metadata`` for tracing and billing attribution.

    When ``thinking_via_capability`` is True (W7 ``Thinking`` capability on the agent),
    manual ``thinking`` body injection is skipped to avoid double-enabling.

    Args:
        req (dict[str, Any]): Anthropic-shaped request body (mutated in place).
        model_id (str): Resolved catalog model id.
        agent (str): Agent key for thinking lookup (``tier_b`` / ``tier_cd`` only).
        content_root (Path | None): Workspace root for ``LLM_params_config.json``.
        has_tools (bool): Whether ``tools`` is non-empty on the request.
        session_id (str | None): Gateway session id for ``metadata``.
        turn_id (str | None): Turn id for ``metadata``.
        user_id (str | None): Channel user id for ``metadata``.
        channel (str | None): Active channel for ``metadata``.
        workspace_id (str | None): Workspace id for ``metadata``.
        executor_tier (str | None): Executor tier label for ``metadata``.
        thinking_via_capability (bool): When ``True``, skip manual ``thinking`` body injection (W7).
        tool_choice_type (Literal["auto", "any"] | None): Anthropic ``tool_choice.type``
            when ``has_tools``; defaults to ``"auto"``.

    Returns:
        None: Mutates ``req`` in place.

    Examples:
        >>> body: dict[str, Any] = {"top_k": 40, "temperature": 1.0}
        >>> apply_minimax_anthropic_request_hygiene(
        ...     body,
        ...     model_id="minimax/MiniMax-M2",
        ...     agent="tier_b",
        ...     content_root=None,
        ...     has_tools=True,
        ...     session_id="s",
        ...     turn_id="t",
        ... )
        >>> "top_k" not in body and body.get("tool_choice") == {"type": "auto"}
        True
        >>> apply_minimax_anthropic_request_hygiene(
        ...     body,
        ...     model_id="minimax/MiniMax-M2",
        ...     agent="tier_b",
        ...     content_root=None,
        ...     has_tools=True,
        ...     tool_choice_type="any",
        ... )
        >>> body.get("tool_choice") == {"type": "any"}
        True
    """
    if not is_minimax_catalog_model(model_id):
        return
    req.pop("top_k", None)
    if has_tools:
        # Anthropic Messages wire requires the OBJECT form ``{"type": "auto"}``;
        # MiniMax's Anthropic-compatible endpoint rejects the bare OpenAI string
        # ``"auto"`` with HTTP 400 ``invalid params`` (verified against
        # api.minimax.io/anthropic — string 400s, object 200s, regardless of
        # system size, tool schema, or metadata keys).
        choice = tool_choice_type or "auto"
        req["tool_choice"] = {"type": choice}
    if not thinking_via_capability:
        thinking = resolve_minimax_thinking_request(agent, model_id, content_root=content_root)
        if thinking is not None:
            req["thinking"] = thinking
    if agent in MINIMAX_THINKING_AGENTS:
        metadata = build_llm_request_metadata(
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            channel=channel,
            workspace_id=workspace_id,
            agent=agent,
            executor_tier=executor_tier,
        )
        if metadata:
            req["metadata"] = metadata


RUN_CODE_TOOL_NAME: Final[str] = "run_code"


def _python_kwargs_repr(args: dict[str, Any]) -> str:
    """Render tool-call args as a Python keyword-argument string for ``run_code``.

    Args:
        args (dict[str, Any]): JSON-decoded tool-call arguments.

    Returns:
        str: ``k=<repr>, ...`` in the call's argument order; empty for no args.

    Examples:
        >>> _python_kwargs_repr({"url": "https://x", "count": 5})
        "url='https://x', count=5"
        >>> _python_kwargs_repr({})
        ''
    """
    return ", ".join(f"{key}={value!r}" for key, value in args.items())


def rewrite_codemode_native_tool_calls(
    parts: list[ModelResponsePart],
    *,
    sandboxed_tool_names: frozenset[str],
) -> tuple[list[ModelResponsePart], list[str]]:
    """Rewrite bare native calls to CodeMode-sandboxed tools into ``run_code`` (Layer 1).

    Under CodeMode only ``run_code`` plus a few meta tools have native handlers; the
    triager-bound retrieval/skill tools live **only** inside the ``run_code`` sandbox.
    MiniMax-class models intermittently emit a top-level ``ToolCallPart`` for such a tool,
    which has no native handler, returns no ``tool_result``, and is later removed as an
    orphan by :func:`strip_orphan_tool_use_blocks` — leaving the model to fabricate an
    answer or loop to ``max_retries`` (`specs/14-executor-tier-b.md` §5.1). This rewrites
    each such call into an equivalent single-statement ``run_code`` invocation, preserving
    the original ``tool_call_id`` so the dispatched result maps back. Because the rewritten
    part is a valid tool call, the turn can no longer finalize on co-emitted text — the
    harness must dispatch it and feed the result back (Layer 2, realized for free).

    Args:
        parts (list[ModelResponsePart]): Post-conversion assistant parts.
        sandboxed_tool_names (frozenset[str]): Names callable only inside ``run_code`` this
            turn (``compute_codemode_eligible_names`` minus the native meta set). Empty when
            CodeMode is off, so the rewrite is a no-op.

    Returns:
        tuple[list[ModelResponsePart], list[str]]: Parts with sandboxed native calls
            rewritten, and the list of rewritten tool names (for telemetry).

    Examples:
        >>> from pydantic_ai.messages import ToolCallPart
        >>> parts, names = rewrite_codemode_native_tool_calls(
        ...     [ToolCallPart(tool_name="get_page_content", args={"url": "https://x"}, tool_call_id="c1")],
        ...     sandboxed_tool_names=frozenset({"get_page_content"}),
        ... )
        >>> names
        ['get_page_content']
        >>> parts[0].tool_name, parts[0].tool_call_id
        ('run_code', 'c1')
        >>> parts[0].args["code"]
        "result = await get_page_content(url='https://x')\\nresult"
    """
    if not sandboxed_tool_names:
        return parts, []
    out: list[ModelResponsePart] = []
    rewritten: list[str] = []
    for part in parts:
        if isinstance(part, ToolCallPart) and part.tool_name in sandboxed_tool_names:
            try:
                args = part.args_as_dict()
            except (ValueError, TypeError):
                args = {}
            code = f"result = await {part.tool_name}({_python_kwargs_repr(args)})\nresult"
            out.append(
                ToolCallPart(
                    tool_name=RUN_CODE_TOOL_NAME,
                    args={"code": code},
                    tool_call_id=part.tool_call_id,
                ),
            )
            rewritten.append(part.tool_name)
            continue
        out.append(part)
    return out, rewritten


_MAX_RUN_CODE_UNWRAP_DEPTH = 3


def _unwrap_nested_run_code_arg(code: str) -> str:
    """Unwrap a ``run_code`` ``code`` argument the model double-wrapped as JSON.

    MiniMax-class models intermittently pass the whole call back as the ``code`` value — e.g.
    ``code='{"code": "result = await log_query(lines=80)"}'`` — so Monty executes a bare dict
    literal, the intended tool never runs, and CodeMode burns its retry budget to
    ``Tool 'run_code' exceeded max retries``. Peel a ``{"code": "..."}`` JSON wrapper (bounded
    depth) back to the inner source so the real code executes.

    Args:
        code (str): Raw ``code`` argument value from a ``run_code`` tool call.

    Returns:
        str: The inner Python source when a JSON ``{"code": ...}`` wrapper was found, else
            ``code`` unchanged.

    Examples:
        >>> _unwrap_nested_run_code_arg('{"code": "await log_query(lines=80)"}')
        'await log_query(lines=80)'
        >>> _unwrap_nested_run_code_arg("result = await serp(query='x')")
        "result = await serp(query='x')"
    """
    for _ in range(_MAX_RUN_CODE_UNWRAP_DEPTH):
        stripped = code.strip()
        if not (stripped.startswith("{") and '"code"' in stripped):
            break
        try:
            obj = json.loads(stripped)
        except (ValueError, TypeError):
            break
        inner = obj.get("code") if isinstance(obj, dict) else None
        if not isinstance(inner, str):
            break
        code = inner
    return code


def normalize_codemode_run_code_payloads(
    parts: list[ModelResponsePart],
) -> tuple[list[ModelResponsePart], int]:
    """Repair ``run_code`` calls whose ``code`` arg is a JSON-wrapped ``{"code": ...}`` string.

    Runs after :func:`rewrite_codemode_native_tool_calls` so both rewritten and model-emitted
    ``run_code`` parts are normalized before dispatch into the Monty sandbox — stops the
    ``Tool 'run_code' exceeded max retries`` failure from a double-wrapped payload.

    Args:
        parts (list[ModelResponsePart]): Post-rewrite assistant parts.

    Returns:
        tuple[list[ModelResponsePart], int]: Parts with unwrapped ``run_code`` code, and the
            count of repaired parts (for telemetry).

    Examples:
        >>> from pydantic_ai.messages import ToolCallPart
        >>> parts, n = normalize_codemode_run_code_payloads(
        ...     [ToolCallPart(tool_name="run_code", args={"code": '{"code": "x=1"}'}, tool_call_id="c1")],
        ... )
        >>> n, parts[0].args["code"]
        (1, 'x=1')
    """
    out: list[ModelResponsePart] = []
    repaired = 0
    for part in parts:
        if isinstance(part, ToolCallPart) and part.tool_name == RUN_CODE_TOOL_NAME:
            try:
                args = part.args_as_dict()
            except (ValueError, TypeError):
                args = {}
            code = args.get("code")
            if isinstance(code, str):
                unwrapped = _unwrap_nested_run_code_arg(code)
                if unwrapped != code:
                    new_args = dict(args)
                    new_args["code"] = unwrapped
                    out.append(
                        ToolCallPart(
                            tool_name=RUN_CODE_TOOL_NAME,
                            args=new_args,
                            tool_call_id=part.tool_call_id,
                        ),
                    )
                    repaired += 1
                    continue
        out.append(part)
    return out, repaired


def build_tier_b_function_model(
    *,
    bundle: ResolvedTierBModel,
    steer_buffer: SteerInject | None,
    trace: TraceSink | None,
    session_id: str,
    turn_id: str,
    provider_round_counter: list[int],
    parent_span_id: str | None = None,
    count_planning: bool = False,
    max_rounds: int | None = None,
    max_output_tokens: int = 4096,
    agent: str = "tier_b",
    content_root: Path | None = None,
    seed: int | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    workspace_id: str | None = None,
    executor_tier: str | None = None,
    allowed_tool_names: frozenset[str] | MutableToolAllowlist | None = None,
    on_granted_tool: Callable[[str], None] | None = None,
    lifecycle_via_hooks: bool = False,
    thinking_via_capability: bool = False,
    turn_message_start_index: int = 0,
    codemode_sandboxed_tool_names: frozenset[str] = frozenset(),
    triager_bound_tool_choice: TriagerBoundToolChoiceContext | None = None,
) -> FunctionModel:
    """Create a ``FunctionModel`` that delegates to ``bundle.transport``.

    Args:
        bundle (ResolvedTierBModel): Resolved model id + transport + budget bundle.
        steer_buffer (SteerInject | None): Optional owner ``/steer`` queue read between rounds.
        trace (TraceSink | None): Optional structured trace sink for provider checkpoints.
        session_id (str): Session id used for tracing.
        turn_id (str): Turn id used for tracing.
        provider_round_counter (list[int]): Mutable one-element counter. Incremented per
            response that contains at least one budget-counted ``ToolCallPart`` (all tools
            except ``load_tool`` / ``load_skill``); when ``count_planning`` is ``True``, every
            response is counted (`specs/14-executor-tier-b.md` §5).
        parent_span_id (str | None): Turn root span id for ``parent_span_id`` linkage.
        count_planning (bool): When ``True``, planning-only LLM rounds (responses without any
            tool call) also increment ``provider_round_counter``; default ``False`` matches
            ``gateway.budget.count_planning`` (`specs/14-executor-tier-b.md` §5).
        max_rounds (int | None): Hard cap on counted rounds. When ``provider_round_counter``
            reaches this value before the next LLM call, ``_llm`` raises
            ``UsageLimitExceeded`` so the gateway can route to escalation. ``None`` disables
            the manual check (pydantic-ai's ``request_limit`` is still in effect).
        max_output_tokens (int): Provider-side ``max_tokens`` cap for the Anthropic
            messages path; ignored by other transports. Defaults to ``4096`` to match
            the prior hardcoded value.
        agent (str): Agent key for ``LLM_params_config.json`` sampling lookup (e.g.
            ``"tier_b"`` or ``"triager"``); see :mod:`sevn.config.llm_params`.
        content_root (Path | None): Workspace content root holding
            ``LLM_params_config.json``. ``None`` falls back to built-in defaults
            (MiniMax ⇒ 1.0/0.95/40, others deterministic).
        seed (int | None): Deterministic seed fallback applied only when the
            resolved config sets none and the wire accepts ``seed`` (e.g. the
            triager's ``cfg.deterministic_seed`` on the chat_completions wire).
        user_id (str | None): Channel user id for MiniMax ``metadata`` (D2).
        channel (str | None): Active channel key for MiniMax ``metadata`` (D2).
        workspace_id (str | None): Workspace id for MiniMax ``metadata`` (D2).
        executor_tier (str | None): Executor tier label for MiniMax ``metadata`` (D2).
        allowed_tool_names (frozenset[str] | MutableToolAllowlist | None): Per-turn
            allowlist for wire exposure and XML-recovered call filtering (P3). Registry-valid
            tools are auto-granted on first recovered call; non-registry tools are dropped
            with ``TOOL_NOT_PROVISIONED`` steer. When ``None``, no filtering is applied.
        on_granted_tool (Callable[[str], None] | None): Optional callback when a
            registry-valid tool is auto-granted (e.g. add to ``BTierDeps.loaded_tools``).
        lifecycle_via_hooks (bool): When ``True``, steer injection and the manual round-budget
            guard in ``_preamble`` are skipped because tier-B ``Hooks`` own those concerns (W5).
        thinking_via_capability (bool): When ``True``, skip manual MiniMax ``thinking`` body injection (W7).
        turn_message_start_index (int): Anthropic row index where this turn's
            ``new_messages()`` begin; used to classify same-turn replay stubs (W3).
        codemode_sandboxed_tool_names (frozenset[str]): Tool names callable only inside
            ``run_code`` this turn; a bare native call to one is rewritten into ``run_code``
            before the allowlist filter (§10.30). Empty disables the rewrite.
        triager_bound_tool_choice (TriagerBoundToolChoiceContext | None): When set and the
            triager bound tools/skills, sends ``{"type": "any"}`` (OpenAI ``"required"``)
            until a bound tool/skill succeeds, then ``auto``.

    Returns:
        FunctionModel: Pydantic AI model whose ``_llm`` delegates to ``transport.complete``.

    Raises:
        NotImplementedError: If ``bundle.transport`` is not a supported serializer family.

    Examples:
        >>> import inspect
        >>> "bundle" in inspect.signature(build_tier_b_function_model).parameters
        True
    """

    transport: Transport = bundle.transport
    model_id: str = bundle.model_id
    budget: ModelBudget = bundle.budget

    if isinstance(transport, ChatCompletionsTransport):
        wire = "chat_completions"
    elif isinstance(transport, (AnthropicMessagesTransport, AnthropicTransport)):
        wire = "anthropic"
    elif isinstance(transport, BedrockTransport):
        wire = "bedrock"
    else:
        msg = (
            "tier B transport must be ChatCompletionsTransport, AnthropicMessagesTransport, "
            f"or BedrockTransport; got {type(transport).__name__}. "
            "Add a serializer in src/sevn/agent/adapters/tier_b_model.py for new shapes."
        )
        raise NotImplementedError(msg)

    # Resolved, transport-filtered sampling params (W7.4). MiniMax catalog ids ride
    # the anthropic wire and pick up top_k/top_p; seed is dropped for that wire.
    sampling_kwargs = resolve_llm_request_params(
        agent, model_id, wire, content_root=content_root, seed=seed
    )

    provider_kind = f"provider.{wire}.{model_id}"

    def _effective_allowed() -> frozenset[str]:
        if allowed_tool_names is None:
            return frozenset()
        if isinstance(allowed_tool_names, MutableToolAllowlist):
            return allowed_tool_names.effective
        return allowed_tool_names

    def _on_dropped_tool(tool_name: str) -> None:
        if steer_buffer is None:
            return
        steer_buffer.inject_pending(
            steer_for_dropped_tool_call(tool_name, available_tools=_effective_allowed()),
        )

    def _filter_response_parts(parts: list[ModelResponsePart]) -> list[ModelResponsePart]:
        # Layer 1: rewrite bare native calls to CodeMode-sandboxed tools into ``run_code``
        # before the allowlist filter, so a contract-violating MiniMax call dispatches
        # through the sandbox instead of vanishing as an orphan (`specs/14` §5.1, §10.20).
        parts, rewritten = rewrite_codemode_native_tool_calls(
            parts,
            sandboxed_tool_names=codemode_sandboxed_tool_names,
        )
        for tool_name in rewritten:
            from sevn.logging.structured import debug_event

            logger.info(
                "tier_b.codemode_native_call_rewritten session_id={} turn_id={} "
                "tool_name={} model_id={}",
                session_id,
                turn_id,
                tool_name,
                model_id,
            )
            debug_event(
                "tier_b.codemode_native_call_rewritten",
                session_id=session_id,
                turn_id=turn_id,
                tool_name=tool_name,
                model_id=model_id,
            )
        # Layer 1b: unwrap a double-wrapped ``run_code`` payload (``code='{"code": ...}'``)
        # so the inner source executes instead of a bare dict literal that burns CodeMode's
        # retry budget to ``Tool 'run_code' exceeded max retries`` (`specs/14` §10.20).
        parts, unwrapped = normalize_codemode_run_code_payloads(parts)
        if unwrapped:
            from sevn.logging.structured import debug_event

            logger.info(
                "tier_b.run_code_payload_unwrapped session_id={} turn_id={} count={} model_id={}",
                session_id,
                turn_id,
                unwrapped,
                model_id,
            )
            debug_event(
                "tier_b.run_code_payload_unwrapped",
                session_id=session_id,
                turn_id=turn_id,
                count=unwrapped,
                model_id=model_id,
            )
        if allowed_tool_names is None:
            return parts
        return filter_tool_call_parts(
            parts,
            allowed_tool_names=allowed_tool_names,
            log_prefix="tier_b",
            on_dropped=_on_dropped_tool,
            on_granted=on_granted_tool,
        )

    async def _preamble(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> tuple[list[ModelMessage], str | None, str, int, int]:
        """Apply the round budget guard + owner steer, emit the ``started`` trace.

        Shared by both the non-streaming ``_llm`` and the streaming ``_stream_llm``
        so each LLM round runs the guard / steer pop / ``started`` emission exactly
        once (no double steer drain when streaming falls back to ``complete``).
        """
        if max_rounds is not None and provider_round_counter[0] >= max_rounds:
            msg = (
                f"tier-B counted-round budget exhausted (rounds={provider_round_counter[0]}, "
                f"max={max_rounds}, count_planning={count_planning})"
            )
            raise UsageLimitExceeded(msg)
        if lifecycle_via_hooks:
            prepared = list(messages)
        else:
            prepared = list(messages)
            if steer_buffer is not None:
                pending = steer_buffer.pop_pending()
                if pending:
                    prepared = append_owner_steer_model_request(prepared, pending)
        span_id = str(uuid.uuid4())
        start_ns = time_ns()
        projected_round = provider_round_counter[0] + 1
        if trace is not None:
            await trace.emit(
                TraceEvent(
                    kind=provider_kind,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier="B",
                    ts_start_ns=start_ns,
                    ts_end_ns=None,
                    status="started",
                    attrs={
                        "round": projected_round,
                        "model_id": model_id,
                        "budget_regime": budget.regime.value,
                    },
                ),
            )
        system_text = tier_b_system_prompt_text(prepared, info)
        return prepared, system_text, span_id, start_ns, projected_round

    def _build_req(
        prepared: list[ModelMessage],
        info: AgentInfo,
        system_text: str | None,
        *,
        sampling_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the wire-shaped request body for ``complete`` / ``complete_stream``."""
        effective_sampling = {**sampling_kwargs, **(sampling_override or {})}
        if wire == "chat_completions":
            # Coalesce consecutive same-role rows (steer / retry splits) before POST — MiniMax
            # rejects adjacent user/assistant messages with 2013 even without tool blocks
            # (transcript-review-2026-06-22). Mirrors the anthropic-wire coalesce below.
            pre_repair = prepared
            prepared = repair_openai_tool_pairing(prepared)
            if prepared != pre_repair:
                pre_synthetic = sum(
                    1
                    for msg in pre_repair
                    if isinstance(msg, ModelRequest)
                    for part in msg.parts
                    if isinstance(part, ToolReturnPart)
                    and part.content == _SYNTHETIC_OPENAI_TOOL_RETURN_CONTENT
                )
                post_synthetic = sum(
                    1
                    for msg in prepared
                    if isinstance(msg, ModelRequest)
                    for part in msg.parts
                    if isinstance(part, ToolReturnPart)
                    and part.content == _SYNTHETIC_OPENAI_TOOL_RETURN_CONTENT
                )
                synthesized = post_synthetic - pre_synthetic
                pre_returns = sum(
                    1
                    for msg in pre_repair
                    if isinstance(msg, ModelRequest)
                    for part in msg.parts
                    if isinstance(part, BaseToolReturnPart)
                )
                post_returns = sum(
                    1
                    for msg in prepared
                    if isinstance(msg, ModelRequest)
                    for part in msg.parts
                    if isinstance(part, BaseToolReturnPart)
                )
                dropped = max(0, pre_returns - post_returns + synthesized)
                from sevn.logging.structured import debug_event

                logger.info(
                    "tier_b.openai_tool_pairing_repaired session_id={} turn_id={} "
                    "synthesized={} dropped={}",
                    session_id,
                    turn_id,
                    synthesized,
                    dropped,
                )
                debug_event(
                    "tier_b.openai_tool_pairing_repaired",
                    session_id=session_id,
                    turn_id=turn_id,
                    synthesized=synthesized,
                    dropped=dropped,
                )
            chat_messages = finalize_openai_chat_messages(
                coalesce_adjacent_openai_messages(
                    pydantic_messages_to_openai_chat(prepared),
                ),
            )
            if system_text:
                chat_messages = [{"role": "system", "content": system_text}, *chat_messages]
            req: dict[str, Any] = {
                "model": model_id,
                "messages": chat_messages,
                **effective_sampling,
            }
            wire_tools = _wire_tool_defs(info.function_tools, allowed_tool_names)
            otools = _openai_tools_payload(wire_tools)
            if otools:
                req["tools"] = otools
                if triager_bound_tool_choice is not None:
                    req["tool_choice"] = triager_bound_tool_choice.openai_tool_choice()
                else:
                    req["tool_choice"] = "auto"
            return req
        if wire == "anthropic":
            projected = pydantic_messages_to_anthropic_messages(prepared)
            coalesced = coalesce_adjacent_anthropic_messages(projected)
            stripped_rows, stripped_count = strip_orphan_tool_use_blocks(coalesced)
            anthropic_messages = sanitize_anthropic_messages(
                coalesce_adjacent_anthropic_messages(stripped_rows),
            )
            if stripped_count:
                from sevn.logging.structured import debug_event

                logger.info(
                    "tier_b.strip_orphan_tool_use session_id={} turn_id={} "
                    "stripped_count={} message_count={} turn_message_start_index={}",
                    session_id,
                    turn_id,
                    stripped_count,
                    len(anthropic_messages),
                    turn_message_start_index,
                )
                debug_event(
                    "tier_b.strip_orphan_tool_use",
                    session_id=session_id,
                    turn_id=turn_id,
                    stripped_count=stripped_count,
                    message_count=len(anthropic_messages),
                    turn_message_start_index=turn_message_start_index,
                )
            req = {
                "model": model_id,
                "max_tokens": max_output_tokens,
                "messages": anthropic_messages,
                **effective_sampling,
            }
            if system_text:
                req["system"] = system_text
            wire_tools = _wire_tool_defs(info.function_tools, allowed_tool_names)
            atools = _anthropic_tools_payload(wire_tools)
            if atools:
                req["tools"] = atools
            tool_choice_type: Literal["auto", "any"] | None = None
            if triager_bound_tool_choice is not None and atools:
                tool_choice_type = triager_bound_tool_choice.anthropic_tool_choice_type()
            if is_minimax_catalog_model(model_id):
                apply_minimax_anthropic_request_hygiene(
                    req,
                    model_id=model_id,
                    agent=agent,
                    content_root=content_root,
                    has_tools=bool(atools),
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    channel=channel,
                    workspace_id=workspace_id,
                    executor_tier=executor_tier,
                    thinking_via_capability=thinking_via_capability,
                    tool_choice_type=tool_choice_type,
                )
            elif tool_choice_type is not None:
                req["tool_choice"] = {"type": tool_choice_type}
            return adapt_request_for_transport(transport, req)
        bedrock_messages = pydantic_messages_to_bedrock_converse(prepared)
        # Bedrock nests sampling under inferenceConfig (temperature/topP/topK).
        inference_config: dict[str, float | int] = {}
        if "temperature" in effective_sampling:
            inference_config["temperature"] = effective_sampling["temperature"]
        if "top_p" in effective_sampling:
            inference_config["topP"] = effective_sampling["top_p"]
        if "top_k" in effective_sampling:
            inference_config["topK"] = effective_sampling["top_k"]
        req = {
            "modelId": model_id,
            "messages": bedrock_messages,
            "inferenceConfig": inference_config,
        }
        wire_tools = _wire_tool_defs(info.function_tools, allowed_tool_names)
        btools = _bedrock_tools_payload(wire_tools)
        if btools:
            req["toolConfig"] = {"tools": btools}
        return req

    async def _emit_error(
        span_id: str, start_ns: int, projected_round: int, exc: BaseException
    ) -> None:
        """Emit the ``error`` provider trace for a failed round."""
        end_ns = time_ns()
        if trace is not None:
            await trace.emit(
                TraceEvent(
                    kind=provider_kind,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier="B",
                    ts_start_ns=start_ns,
                    ts_end_ns=end_ns,
                    status="error",
                    attrs={
                        "error": type(exc).__name__,
                        "round": projected_round,
                        "model_id": model_id,
                        "budget_regime": budget.regime.value,
                    },
                ),
            )
        await emit_provider_call(
            trace,
            span_id=span_id,
            parent_span_id=parent_span_id,
            session_id=session_id,
            turn_id=turn_id,
            model_id=model_id,
            regime=budget.regime.value,
            tokens_in=0,
            tokens_out=0,
            transport=wire,
            tier="B",
            status="error",
            ts_start_ns=start_ns,
            ts_end_ns=end_ns,
            extra_attrs={"error": type(exc).__name__, "round": projected_round},
        )

    async def _account(
        model_response: ModelResponse,
        in_tok: int,
        out_tok: int,
        span_id: str,
        start_ns: int,
        projected_round: int,
        *,
        empty_content_rate: float = 0.0,
    ) -> None:
        """Increment the round budget, log, and emit the ``ok`` provider trace."""
        _ = projected_round
        end_ns = time_ns()
        has_tool_calls = any(isinstance(p, ToolCallPart) for p in model_response.parts)
        has_budget_tool_calls = _has_budget_counted_tool_calls(list(model_response.parts))
        counted = count_planning or has_budget_tool_calls
        if counted:
            provider_round_counter[0] += 1
            tool_calls = [part for part in model_response.parts if isinstance(part, ToolCallPart)]
            tools_used = len(tool_calls)
            tool_names = [part.tool_name for part in tool_calls]
            elapsed_ms = (end_ns - start_ns) // 1_000_000
            logger.info(
                "agent_turn round={} tier=B tools_used={} tool_names={} elapsed_ms={}",
                provider_round_counter[0],
                tools_used,
                tool_names,
                elapsed_ms,
            )
            from sevn.logging.structured import debug_event

            debug_event(
                "tier_b.round_tools",
                session_id=session_id,
                turn_id=turn_id,
                round=provider_round_counter[0],
                tool_names=tool_names,
                elapsed_ms=elapsed_ms,
            )
        if trace is not None:
            await trace.emit(
                TraceEvent(
                    kind=provider_kind,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier="B",
                    ts_start_ns=start_ns,
                    ts_end_ns=end_ns,
                    status="ok",
                    attrs={
                        "round": provider_round_counter[0],
                        "counted": counted,
                        "has_tool_calls": has_tool_calls,
                        "has_budget_tool_calls": has_budget_tool_calls,
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "model_id": model_id,
                        "budget_regime": budget.regime.value,
                        "empty_content_rate": empty_content_rate,
                    },
                ),
            )
        await emit_provider_call(
            trace,
            span_id=span_id,
            parent_span_id=parent_span_id,
            session_id=session_id,
            turn_id=turn_id,
            model_id=model_id,
            regime=budget.regime.value,
            tokens_in=in_tok,
            tokens_out=out_tok,
            transport=wire,
            tier="B",
            status="ok",
            ts_start_ns=start_ns,
            ts_end_ns=end_ns,
            extra_attrs={
                "round": provider_round_counter[0],
                "empty_content_rate": empty_content_rate,
            },
        )

    async def _complete_payload(
        prepared: list[ModelMessage],
        info: AgentInfo,
        system_text: str | None,
    ) -> tuple[dict[str, Any], float]:
        """Run ``transport.complete`` once, nudging once on empty Anthropic ``end_turn``.

        Args:
            prepared (list[ModelMessage]): History for this LLM round.
            info (AgentInfo): Pydantic-ai agent tool/output metadata.
            system_text (str | None): Merged system prompt for the wire.

        Returns:
            tuple[dict[str, Any], float]: Raw provider payload and ``empty_content_rate``
                (``1.0`` when an empty ``end_turn`` was observed before the nudge).
        """
        req = _build_req(prepared, info, system_text)
        resp = await transport.complete(req)
        empty_content_rate = (
            1.0 if wire == "anthropic" and is_anthropic_empty_end_turn(resp) else 0.0
        )
        if empty_content_rate == 1.0:
            logger.warning(
                "anthropic_empty_content_nudge model={} stop={}",
                resp.get("model", model_id),
                resp.get("stop_reason"),
            )
            nudge_prepared = [
                *prepared,
                ModelRequest(
                    parts=[UserPromptPart(content=_EMPTY_CONTENT_NUDGE_USER_TEXT)],
                ),
            ]
            nudge_req = _build_req(
                nudge_prepared,
                info,
                system_text,
                sampling_override={"temperature": _EMPTY_CONTENT_NUDGE_TEMPERATURE},
            )
            resp = await transport.complete(nudge_req)
        return resp, empty_content_rate

    async def _complete_round(
        prepared: list[ModelMessage],
        info: AgentInfo,
        system_text: str | None,
        span_id: str,
        start_ns: int,
        projected_round: int,
    ) -> ModelResponse:
        """Run one non-streaming ``complete`` round (no preamble; account on success)."""
        try:
            resp, empty_content_rate = await _complete_payload(prepared, info, system_text)
            model_response = _model_response_for_wire(wire, resp)
            if allowed_tool_names is not None:
                model_response = dataclasses.replace(
                    model_response,
                    parts=_filter_response_parts(list(model_response.parts)),
                )
            in_tok, out_tok = transport.tokens_used(resp)
        except BaseException as exc:
            await _emit_error(span_id, start_ns, projected_round, exc)
            raise
        await _account(
            model_response,
            in_tok,
            out_tok,
            span_id,
            start_ns,
            projected_round,
            empty_content_rate=empty_content_rate,
        )
        return model_response

    async def _llm(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prepared, system_text, span_id, start_ns, projected_round = await _preamble(messages, info)
        return await _complete_round(
            prepared, info, system_text, span_id, start_ns, projected_round
        )

    async def _stream_llm(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | DeltaToolCalls]:
        """Stream genuine token deltas from ``transport.complete_stream``.

        Real SSE: ``complete_stream`` sends ``stream: true`` and reconstructs the
        upstream event stream into incremental text + a final ``complete``-shaped
        payload. Live ``text_delta`` fragments are yielded so the harness'
        ``stream_text(delta=False)`` tap edits the Telegram placeholder
        progressively; the same final payload is then run through the wire
        converter so MiniMax XML / thinking recovery and native tool calls are
        preserved exactly as on the batch path (`specs/14-executor-tier-b.md` §2.3).

        Robustness:
        - Tool calls are surfaced as ``DeltaToolCalls`` (yielding text alone drops
          ``ToolCallPart``s, stalling the loop). Mixed yields are fine — pydantic-ai
          keys text vs tool parts by ``vendor_part_id``.
        - When a ``text`` block starts emitting MiniMax XML tool markup, live text
          forwarding stops so the raw markup never flashes in the placeholder; the
          converter recovers the call post-hoc.
        - If the stream cannot start (or fails before any text is shown), it falls
          back to one non-streaming ``complete`` round (same preamble / span — no
          double steer drain, no double round-trip).
        """
        prepared, system_text, span_id, start_ns, projected_round = await _preamble(messages, info)
        text_shown = False
        try:
            req = _build_req(prepared, info, system_text)
            text_acc = ""
            suppress = False
            final_resp: dict[str, object] | None = None
            async for chunk in transport.complete_stream(req):
                if isinstance(chunk, StreamTextDelta):
                    text_acc += chunk.text
                    if not suppress and _has_tool_markup(text_acc):
                        suppress = True
                    if not suppress and chunk.text:
                        text_shown = True
                        yield chunk.text
                else:
                    final_resp = chunk.response
            if final_resp is None:
                msg = "complete_stream produced no final payload"
                raise RuntimeError(msg)
            empty_content_rate = 0.0
            if wire == "anthropic" and is_anthropic_empty_end_turn(final_resp):
                empty_content_rate = 1.0
                logger.warning(
                    "anthropic_empty_content_nudge model={} stop={} path=stream",
                    final_resp.get("model", model_id),
                    final_resp.get("stop_reason"),
                )
                nudge_prepared = [
                    *prepared,
                    ModelRequest(
                        parts=[UserPromptPart(content=_EMPTY_CONTENT_NUDGE_USER_TEXT)],
                    ),
                ]
                nudge_req = _build_req(
                    nudge_prepared,
                    info,
                    system_text,
                    sampling_override={"temperature": _EMPTY_CONTENT_NUDGE_TEMPERATURE},
                )
                final_resp = await transport.complete(nudge_req)
            model_response = _model_response_for_wire(wire, final_resp)
            if allowed_tool_names is not None:
                model_response = dataclasses.replace(
                    model_response,
                    parts=_filter_response_parts(list(model_response.parts)),
                )
            in_tok, out_tok = transport.tokens_used(final_resp)
        except Exception as exc:
            if text_shown:
                # Tokens already rendered; cannot cleanly restart this node. Surface
                # the error so the harness logs ``streaming_unavailable`` and the node
                # loop re-runs via the non-streaming ``_llm`` path.
                await _emit_error(span_id, start_ns, projected_round, exc)
                raise
            logger.info(
                "tier_b.stream_fallback_to_complete reason={} upstream_body={!r} session_id={} "
                "turn_id={} model_id={} transport={}",
                exc,
                _extract_upstream_error_body(exc),
                session_id,
                turn_id,
                model_id,
                transport.name,
            )
            model_response = await _complete_round(
                prepared, info, system_text, span_id, start_ns, projected_round
            )
            async for delta in _response_to_stream_deltas(model_response):
                yield delta
            return
        await _account(
            model_response,
            in_tok,
            out_tok,
            span_id,
            start_ns,
            projected_round,
            empty_content_rate=empty_content_rate,
        )
        tool_parts = [p for p in model_response.parts if isinstance(p, ToolCallPart)]
        if tool_parts:
            yield _tool_call_deltas(tool_parts)
            return
        if not text_shown:
            # Pure-text round where nothing streamed live (empty text deltas, or
            # markup-suppressed with no recovered tool): emit display text (salvages
            # from ``ThinkingPart`` only when there is no text and no tool call).
            recovered = _display_text_from_model_response(model_response)
            if recovered:
                yield recovered

    return FunctionModel(
        _llm,
        stream_function=_stream_llm,
        model_name=f"sevn-tier-b:{model_id}",
        settings=None,
    )


_SYNTHETIC_OPENAI_TOOL_RETURN_CONTENT = "[no result recorded]"
"""Placeholder for assistant ``ToolCallPart`` rows left without a matching return (2013 fix)."""


def _synthetic_openai_tool_return_request(
    pending_calls: list[tuple[str, str]],
) -> ModelRequest:
    """Build one ``ModelRequest`` with stub returns for dangling assistant tool calls.

    Args:
        pending_calls (list[tuple[str, str]]): ``(tool_call_id, tool_name)`` pairs still
            awaiting a ``ToolReturnPart`` after the assistant row that emitted them.

    Returns:
        ModelRequest: Stub tool returns keyed to each pending id.

    Examples:
        >>> req = _synthetic_openai_tool_return_request([("t1", "read")])
        >>> req.parts[0].tool_call_id
        't1'
        >>> req.parts[0].content
        '[no result recorded]'
    """
    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name=tool_name,
                content=_SYNTHETIC_OPENAI_TOOL_RETURN_CONTENT,
                tool_call_id=tool_call_id,
            )
            for tool_call_id, tool_name in pending_calls
        ],
    )


def _openai_tool_return_ids(parts: list[Any]) -> set[str]:
    """Collect ``tool_call_id`` values from parts that fulfill assistant tool calls.

    Args:
        parts (list[Any]): ``ModelRequest`` parts after orphan-return filtering.

    Returns:
        set[str]: Ids present on ``ToolReturnPart`` rows.

    Examples:
        >>> _openai_tool_return_ids([
        ...     ToolReturnPart(tool_name="read", content="ok", tool_call_id="t1"),
        ... ])
        {'t1'}
    """
    return {
        str(part.tool_call_id)
        for part in parts
        if isinstance(part, BaseToolReturnPart) and part.tool_call_id
    }


def repair_openai_tool_pairing(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Repair orphan tool returns and dangling tool calls on the chat_completions wire (2013).

    The OpenAI/chat_completions transport maps each ``ToolReturnPart`` / tool-scoped
    ``RetryPromptPart`` to an OpenAI ``tool`` message keyed by ``tool_call_id``. Two failure
    modes make MiniMax reject the request with ``invalid params … (2013)``:

    * **Orphan return** — a tool return whose id was never produced by a preceding
      ``ToolCallPart`` (e.g. left behind by a cancelled pass). These are dropped.
    * **Dangling call** — an assistant ``ToolCallPart`` with no matching following
      ``ToolReturnPart`` (e.g. a prior turn that failed mid-``run_code``). A stub return is
      synthesized immediately after the assistant row that emitted the call.

    Non-tool parts (user prompts, retries without a tool id) are always preserved.

    Args:
        messages (list[ModelMessage]): pydantic-ai conversation history.

    Returns:
        list[ModelMessage]: History safe for MiniMax chat_completions replay.

    Examples:
        >>> hist = [
        ...     ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="t1")]),
        ...     ModelRequest(parts=[ToolReturnPart(tool_name="read", content="ok", tool_call_id="t1")]),
        ...     ModelRequest(parts=[ToolReturnPart(tool_name="x", content="zz", tool_call_id="ghost")]),
        ... ]
        >>> repaired = repair_openai_tool_pairing(hist)
        >>> len(repaired)  # the orphan 'ghost' request is dropped
        2
        >>> dangling = [ModelResponse(parts=[ToolCallPart(tool_name="read", args={}, tool_call_id="t1")])]
        >>> len(repair_openai_tool_pairing(dangling))
        2
    """
    seen_call_ids: set[str] = set()
    pending_calls: list[tuple[str, str]] = []
    repaired: list[ModelMessage] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            if pending_calls:
                repaired.append(_synthetic_openai_tool_return_request(pending_calls))
                pending_calls = []
            for resp_part in msg.parts:
                if isinstance(resp_part, ToolCallPart) and resp_part.tool_call_id:
                    seen_call_ids.add(resp_part.tool_call_id)
                    pending_calls.append((resp_part.tool_call_id, resp_part.tool_name))
            repaired.append(msg)
            continue
        if isinstance(msg, ModelRequest):
            kept: list[Any] = []
            dropped = False
            for part in msg.parts:
                tool_id = getattr(part, "tool_call_id", None)
                # Only parts that map to an OpenAI ``tool`` message can trigger 2013: a
                # ``ToolReturnPart`` always does, a ``RetryPromptPart`` only when it is
                # tool-scoped (``tool_name`` set). A plain output-validation retry carries an
                # auto-generated ``tool_call_id`` but maps to a user message, so keep it.
                is_tool_scoped = isinstance(part, BaseToolReturnPart) or (
                    isinstance(part, RetryPromptPart) and part.tool_name is not None
                )
                if is_tool_scoped and tool_id and tool_id not in seen_call_ids:
                    dropped = True
                    continue
                kept.append(part)
            if kept:
                repaired.append(dataclasses.replace(msg, parts=kept) if dropped else msg)
                fulfilled = _openai_tool_return_ids(kept)
                if fulfilled and pending_calls:
                    pending_calls = [
                        (tool_call_id, tool_name)
                        for tool_call_id, tool_name in pending_calls
                        if tool_call_id not in fulfilled
                    ]
            continue
        if pending_calls:
            repaired.append(_synthetic_openai_tool_return_request(pending_calls))
            pending_calls = []
        repaired.append(msg)
    if pending_calls:
        repaired.append(_synthetic_openai_tool_return_request(pending_calls))
    return repaired


__all__ = [
    "TriagerBoundToolChoiceContext",
    "anthropic_completion_to_model_response",
    "append_owner_steer_model_request",
    "apply_minimax_anthropic_request_hygiene",
    "bedrock_converse_to_model_response",
    "build_tier_b_function_model",
    "coalesce_adjacent_anthropic_messages",
    "coalesce_adjacent_openai_messages",
    "finalize_openai_chat_messages",
    "is_anthropic_empty_end_turn",
    "merge_adjacent_anthropic_text_blocks",
    "openai_completion_to_model_response",
    "prepare_anthropic_messages_for_transport",
    "pydantic_messages_to_anthropic_messages",
    "pydantic_messages_to_bedrock_converse",
    "pydantic_messages_to_openai_chat",
    "repair_anthropic_tool_pairing",
    "repair_openai_tool_pairing",
    "replay_stubs_are_same_turn_only",
    "sanitize_anthropic_messages",
    "strip_orphan_tool_result_blocks",
    "strip_orphan_tool_use_blocks",
    "tier_b_system_prompt_text",
]
