"""Draft ``RuntimeEvent`` mapping for subscription CLI transcripts (D4)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_INTERRUPTED = frozenset({"aborted_streaming", "aborted_tools"})

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
    "codex": frozenset({"unknown"}),
    "opencode": frozenset({"unknown"}),
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
    native_type = native.get("type")
    if isinstance(native_type, str) and native_type:
        documented = IGNORED_NATIVE.get(runtime, frozenset())
        if native_type in documented:
            return _ignored(native_type)
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
        return RuntimeEvent(kind="text_delta", text=block["text"])
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
