"""Draft ``RuntimeEvent`` mapping for subscription CLI transcripts (D4)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_INTERRUPTED = frozenset({"aborted_streaming", "aborted_tools"})
_ACP_STOP_ERRORS = frozenset({"refusal", "max_tokens", "max_turn_requests"})
_CODEX_APPROVALS = frozenset(
    {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "mcpServer/elicitation/request",
    }
)
_CODEX_TOOL_TYPES = frozenset({"mcpToolCall", "commandExecution", "dynamicToolCall", "fileChange"})
_ACP_IGNORED = frozenset(
    {
        "agent_message_chunk",
        "agent_thought_chunk",
        "available_commands_update",
        "config_option_update",
        "current_mode_update",
        "plan",
        "plan_removed",
        "plan_update",
        "session",
        "session_info_update",
        "session_update",
        "tool_call",
        "tool_call_update",
        "unknown",
        "usage_update",
        "user_message_chunk",
    }
)

IGNORED_NATIVE: dict[str, frozenset[str]] = {
    "claude": frozenset(
        {
            "assistant",
            "conversation_reset",
            "permission_request",
            "rate_limit_event",
            "stream_event",
            "system",
            "unknown",
            "user",
        }
    ),
    "codex": frozenset(
        {
            "item/commandExecution/outputDelta",
            "item/completed",
            "item/fileChange/outputDelta",
            "item/fileChange/patchUpdated",
            "item/mcpToolCall/progress",
            "item/plan/delta",
            "item/reasoning/summaryPartAdded",
            "item/started",
            "mcpServer/startupStatus/updated",
            "model/rerouted",
            "serverRequest/resolved",
            "thread/status/changed",
            "thread/tokenUsage/updated",
            "turn/diff/updated",
            "turn/started",
            "unknown",
        }
    ),
    "opencode": _ACP_IGNORED,
    "cursor": _ACP_IGNORED,
}


@dataclass(frozen=True)
class RuntimeEvent:
    """One mapped runtime event. Only the fields for ``kind`` are meaningful."""

    kind: str
    text: str | None = None
    name: str | None = None
    args: dict[str, object] | None = None
    ok: bool | None = None
    tool: str | None = None
    request_id: str | None = None
    usage: dict[str, object] | None = None
    code: str | None = None
    message: str | None = None
    session_ref: str | None = None
    native_type: str | None = None


def map_native_event(runtime: str, native: object) -> RuntimeEvent:
    """Map one native object to a D4 event, or to a documented ``ignored`` event.

    Never raises ``KeyError``. Unknown shapes become ``ignored`` / ``unknown``.
    """

    if not isinstance(native, Mapping):
        return _ignored("unknown")
    if runtime == "claude":
        return _map_claude(native)
    if runtime == "codex":
        return _map_codex(native)
    if runtime in {"opencode", "cursor"}:
        return _map_acp(runtime, native)
    return _ignored("unknown")


def _map_claude(native: Mapping[str, object]) -> RuntimeEvent:
    native_type = native.get("type")
    if native_type == "system":
        return _map_system(native)
    if native_type == "stream_event":
        return _map_stream(native.get("event"))
    if native_type == "assistant":
        return _map_block(native.get("block"))
    if native_type == "user":
        block = native.get("block")
        if isinstance(block, Mapping) and block.get("type") == "tool_result":
            return _map_block(block)
        return _ignored("user")
    if native_type == "result":
        return _map_result(native)
    if native_type == "permission_request":
        return _map_permission(native)
    if native_type == "error":
        return _map_error(native)
    if isinstance(native_type, str) and native_type in IGNORED_NATIVE["claude"]:
        return _ignored(native_type)
    return _ignored("unknown")


def _map_system(native: Mapping[str, object]) -> RuntimeEvent:
    session_id = native.get("session_id")
    if native.get("subtype") == "init" and isinstance(session_id, str) and session_id:
        return RuntimeEvent(kind="session_bound", session_ref=session_id)
    return _ignored("system")


def _map_stream(event: object) -> RuntimeEvent:
    if not isinstance(event, Mapping) or event.get("type") != "content_block_delta":
        return _ignored("stream_event")
    delta = event.get("delta")
    if not isinstance(delta, Mapping):
        return _ignored("stream_event")
    if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
        return RuntimeEvent(kind="text_delta", text=delta["text"])
    if delta.get("type") == "thinking_delta" and isinstance(delta.get("thinking"), str):
        return RuntimeEvent(kind="thinking_delta", text=delta["thinking"])
    return _ignored("stream_event")


def _map_block(block: object) -> RuntimeEvent:
    if not isinstance(block, Mapping):
        return _ignored("assistant")
    block_type = block.get("type")
    if block_type == "text" and isinstance(block.get("text"), str):
        # include_partial_messages already streamed this reply as text_delta.
        return _ignored("assistant")
    if block_type == "thinking" and isinstance(block.get("thinking"), str):
        return RuntimeEvent(kind="thinking_delta", text=block["thinking"])
    if block_type == "tool_use":
        name = block.get("name")
        if isinstance(name, str) and name:
            raw_args = block.get("input")
            args = dict(raw_args) if isinstance(raw_args, Mapping) else {}
            return RuntimeEvent(kind="tool_call_started", name=name, args=args)
    if block_type == "tool_result":
        name = block.get("name")
        if isinstance(name, str) and name:
            return RuntimeEvent(
                kind="tool_call_finished",
                name=name,
                ok=block.get("is_error") is not True,
            )
    return _ignored("assistant")


def _map_permission(native: Mapping[str, object]) -> RuntimeEvent:
    tool = native.get("tool")
    args = native.get("args")
    request_id = native.get("request_id")
    if (
        isinstance(tool, str)
        and tool
        and isinstance(args, Mapping)
        and isinstance(request_id, str)
        and request_id
    ):
        return RuntimeEvent(
            kind="permission_request",
            tool=tool,
            args=dict(args),
            request_id=request_id,
        )
    return _ignored("permission_request")


def _map_result(native: Mapping[str, object]) -> RuntimeEvent:
    terminal = native.get("terminal_reason")
    if terminal in _INTERRUPTED:
        return RuntimeEvent(kind="error", code="interrupted", message=_message_text(native))
    if native.get("is_error") is True:
        code = native.get("subtype")
        return RuntimeEvent(
            kind="error",
            code=code if isinstance(code, str) and code else "error",
            message=_message_text(native),
        )
    usage = native.get("usage")
    return RuntimeEvent(
        kind="turn_finished",
        usage=dict(usage) if isinstance(usage, Mapping) else None,
    )


def _map_error(native: Mapping[str, object]) -> RuntimeEvent:
    code = native.get("code")
    message = native.get("message")
    if isinstance(code, str) and code and isinstance(message, str):
        return RuntimeEvent(kind="error", code=code, message=message)
    return _ignored("unknown")


def _message_text(native: Mapping[str, object]) -> str:
    errors = native.get("errors")
    if isinstance(errors, list):
        parts = [item for item in errors if isinstance(item, str)]
        if parts:
            return "\n".join(parts)
    result = native.get("result")
    if isinstance(result, str):
        return result
    return ""


def _ignored(native_type: str) -> RuntimeEvent:
    return RuntimeEvent(kind="ignored", native_type=native_type)


def _map_codex(native: Mapping[str, object]) -> RuntimeEvent:
    method = native.get("method")
    params = native.get("params")
    body = params if isinstance(params, Mapping) else {}
    if not isinstance(method, str) or not method:
        return _ignored("unknown")
    if method in {"thread/start", "thread/resume", "thread/started"}:
        thread_id = _codex_thread_id(body)
        if thread_id:
            return RuntimeEvent(kind="session_bound", session_ref=thread_id)
        return _ignored_named("codex", method)
    if method == "item/agentMessage/delta":
        return _delta("text_delta", body) or _ignored_named("codex", method)
    if method in {"item/reasoning/textDelta", "item/reasoning/summaryTextDelta"}:
        return _delta("thinking_delta", body) or _ignored_named("codex", method)
    if method == "item/started":
        return _codex_tool(body.get("item"), finished=False) or _ignored_named("codex", method)
    if method == "item/completed":
        return _codex_tool(body.get("item"), finished=True) or _ignored_named("codex", method)
    if method in _CODEX_APPROVALS:
        return _codex_permission(method, body)
    if method == "turn/completed":
        return _codex_turn(body)
    return _ignored_named("codex", method)


def _map_acp(runtime: str, native: Mapping[str, object]) -> RuntimeEvent:
    native_type = native.get("type")
    if native_type == "session":
        session_id = native.get("session_id")
        if isinstance(session_id, str) and session_id:
            return RuntimeEvent(kind="session_bound", session_ref=session_id)
        return _ignored_named(runtime, "session")
    if native_type == "permission_request":
        return _map_permission(native)
    if native_type == "prompt_response":
        return _acp_stop(native)
    if native_type == "session_update":
        return _acp_update(runtime, native.get("update"))
    if isinstance(native_type, str):
        return _ignored_named(runtime, native_type)
    return _ignored("unknown")


def _delta(kind: str, params: Mapping[str, object]) -> RuntimeEvent | None:
    text = params.get("delta")
    if isinstance(text, str):
        return RuntimeEvent(kind=kind, text=text)
    return None


def _codex_thread_id(params: Mapping[str, object]) -> str | None:
    thread_id = params.get("threadId")
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    thread = params.get("thread")
    if isinstance(thread, Mapping):
        nested = thread.get("id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _codex_tool(item: object, *, finished: bool) -> RuntimeEvent | None:
    if not isinstance(item, Mapping) or item.get("type") not in _CODEX_TOOL_TYPES:
        return None
    name = _codex_tool_name(item)
    if not finished:
        return RuntimeEvent(kind="tool_call_started", name=name, args=_tool_args(item))
    status = item.get("status")
    return RuntimeEvent(
        kind="tool_call_finished",
        name=name,
        ok=status not in {"failed", "declined"},
    )


def _codex_tool_name(item: Mapping[str, object]) -> str:
    tool = item.get("tool")
    if isinstance(tool, str) and tool:
        return tool
    if item.get("type") == "commandExecution":
        return "shell"
    if item.get("type") == "fileChange":
        return "apply_patch"
    return "tool"


def _tool_args(item: Mapping[str, object]) -> dict[str, object]:
    arguments = item.get("arguments")
    if not isinstance(arguments, Mapping):
        arguments = item.get("args")
    if isinstance(arguments, Mapping):
        return {str(key): value for key, value in arguments.items()}
    command = item.get("command")
    if isinstance(command, str):
        return {"command": command}
    return {}


def _codex_permission(method: str, params: Mapping[str, object]) -> RuntimeEvent:
    request_id = params.get("itemId") or params.get("approvalId") or params.get("id")
    if not isinstance(request_id, str) or not request_id:
        request_id = method
    tool = params.get("tool")
    if not isinstance(tool, str) or not tool:
        tool = "permissions"
    return RuntimeEvent(
        kind="permission_request",
        tool=tool,
        args=_tool_args(params),
        request_id=request_id,
    )


def _codex_turn(params: Mapping[str, object]) -> RuntimeEvent:
    turn = params.get("turn")
    body = turn if isinstance(turn, Mapping) else params
    status = body.get("status")
    if status == "interrupted":
        return RuntimeEvent(kind="error", code="interrupted", message="")
    if status == "failed":
        error = body.get("error")
        message = ""
        if isinstance(error, Mapping) and isinstance(error.get("message"), str):
            message = error["message"]
        return RuntimeEvent(kind="error", code="failed", message=message)
    return RuntimeEvent(kind="turn_finished", usage=_usage_dict(params.get("usage")))


def _acp_update(runtime: str, update: object) -> RuntimeEvent:
    if not isinstance(update, Mapping):
        return _ignored_named(runtime, "session_update")
    kind = update.get("sessionUpdate")
    if not isinstance(kind, str):
        return _ignored_named(runtime, "session_update")
    if kind in {"agent_message_chunk", "agent_thought_chunk"}:
        text = update.get("text")
        if isinstance(text, str):
            event_kind = "text_delta" if kind == "agent_message_chunk" else "thinking_delta"
            return RuntimeEvent(kind=event_kind, text=text)
        return _ignored_named(runtime, kind)
    if kind == "tool_call":
        name = update.get("tool")
        if isinstance(name, str) and name:
            return RuntimeEvent(kind="tool_call_started", name=name, args=_tool_args(update))
        return _ignored_named(runtime, kind)
    if kind == "tool_call_update" and update.get("status") in {"completed", "failed"}:
        name = update.get("tool")
        if isinstance(name, str) and name:
            return RuntimeEvent(
                kind="tool_call_finished",
                name=name,
                ok=update.get("status") == "completed",
            )
    return _ignored_named(runtime, kind)


def _acp_stop(native: Mapping[str, object]) -> RuntimeEvent:
    reason = native.get("stopReason")
    if reason == "cancelled":
        return RuntimeEvent(kind="error", code="interrupted", message="cancelled")
    if isinstance(reason, str) and reason in _ACP_STOP_ERRORS:
        return RuntimeEvent(kind="error", code=reason, message=reason)
    return RuntimeEvent(kind="turn_finished", usage=_usage_dict(native.get("usage")))


def _usage_dict(usage: object) -> dict[str, object] | None:
    if not isinstance(usage, Mapping):
        return None
    return {str(key): value for key, value in usage.items()}


def _ignored_named(runtime: str, native_type: str) -> RuntimeEvent:
    documented = IGNORED_NATIVE.get(runtime, frozenset())
    if native_type in documented:
        return _ignored(native_type)
    return _ignored("unknown")
