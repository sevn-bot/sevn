"""Claude Code adapter: one ``ClaudeSDKClient`` session per workspace (D3, D5)."""

from __future__ import annotations

import inspect
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from claude_agent_sdk.types import ContentBlock, ConversationResetMessage, RateLimitEvent

from spike_rt.events import RuntimeEvent, map_native_event
from spike_rt.mcp_server import BoundServer, echo_server

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "claude"
_SYSTEM_APPEND = (
    "sevn tools: when the user asks you to call sevn_echo, call that MCP tool exactly "
    "once and pass the text argument exactly as they wrote it. Do not simulate the call "
    "with a shell command. When tool permission is denied, request permission again and "
    "retry the same tool. When asked to create out.txt, create that file in the working "
    "directory with the contents ok and no other files. When told not to use tools, do "
    "not use tools."
)
_SCRUBBERS = (
    (re.compile(r"/Users/[^/\s\"]+"), "<HOME>"),
    (re.compile(r"/home/[^/\s\"]+"), "<HOME>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "sk-x"),
    (re.compile(r"Bearer [A-Za-z0-9._~+/=-]{8,}"), "Bearer x"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh-x"),
)

PermissionCallback = Callable[[RuntimeEvent], str | Awaitable[str]]
EventCallback = Callable[[RuntimeEvent], Awaitable[None] | None]


class ClaudeSession:
    """One Claude Code process bound to a workspace and a loopback MCP server."""

    def __init__(
        self,
        workspace: Path,
        server: BoundServer,
        manager: object,
        session_ref: str | None,
    ) -> None:
        self._workspace = workspace
        self._server = server
        self._manager = manager
        self._client: ClaudeSDKClient | None = None
        self._closed = False
        self._stderr: list[str] = []
        self._tool_names: dict[str, str] = {}
        self._on_permission: PermissionCallback | None = None
        self._on_event: EventCallback | None = None
        self._events: list[RuntimeEvent] = []
        self._turn_natives: list[dict[str, object]] = []
        self._saw_session = False
        self.session_ref = session_ref
        self.bearer = server.bearer
        self.mcp_calls = server.calls

    async def connect(self) -> None:
        options = ClaudeAgentOptions(
            cwd=self._workspace,
            resume=self.session_ref,
            mcp_servers={
                "sevn": {
                    "type": "http",
                    "url": self._server.url,
                    "headers": {"Authorization": f"Bearer {self._server.bearer}"},
                }
            },
            strict_mcp_config=True,
            permission_mode="default",
            can_use_tool=self._can_use_tool,
            setting_sources=[],
            skills=[],
            include_partial_messages=True,
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": _SYSTEM_APPEND,
            },
            stderr=self._remember_stderr,
        )
        self._client = ClaudeSDKClient(options)
        try:
            await self._client.connect()
        except Exception as exc:
            detail = _scrub("\n".join(self._stderr[-30:]))
            raise RuntimeError(f"claude connect failed: {exc}\n{detail}") from exc

    async def turn(
        self,
        prompt: str,
        *,
        on_permission: PermissionCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> list[RuntimeEvent]:
        client = self._require_client()
        self._on_permission = on_permission
        self._on_event = on_event
        self._events = []
        self._turn_natives = []
        self._saw_session = False
        try:
            await client.query(prompt, session_id=self.session_ref or "default")
            async for message in client.receive_response():
                for native in self._natives_from(message):
                    await self._push(native)
        finally:
            self._on_permission = None
            self._on_event = None
            self._write_fixture()
        return list(self._events)

    async def interrupt(self) -> None:
        await self._require_client().interrupt()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        client = self._client
        self._client = None
        try:
            if client is not None:
                await client.disconnect()
        finally:
            exit_cm = getattr(self._manager, "__exit__", None)
            if exit_cm is not None:
                exit_cm(None, None, None)

    async def _can_use_tool(
        self,
        tool_name: str,
        tool_input: dict[str, object],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        request_id = context.tool_use_id or uuid.uuid4().hex
        event = await self._push(
            {
                "type": "permission_request",
                "tool": tool_name,
                "args": _as_dict(tool_input),
                "request_id": request_id,
            }
        )
        decision = await _invoke(self._on_permission, event)
        if decision == "approve":
            return PermissionResultAllow()
        return PermissionResultDeny(
            message="Permission denied. Request permission again and retry the same tool.",
            interrupt=False,
        )

    async def _push(self, native: dict[str, object]) -> RuntimeEvent:
        event = map_native_event("claude", native)
        self._turn_natives.append(native)
        self._events.append(event)
        if event.kind == "session_bound" and event.session_ref:
            self.session_ref = event.session_ref
        await _invoke(self._on_event, event)
        return event

    def _natives_from(self, message: object) -> list[dict[str, object]]:
        if isinstance(message, SystemMessage):
            return self._system_natives(message)
        natives = self._session_prefix(_session_id(message))
        natives.extend(self._content_natives(message))
        return natives

    def _system_natives(self, message: SystemMessage) -> list[dict[str, object]]:
        session_id = message.data.get("session_id") if isinstance(message.data, dict) else None
        sid = session_id if isinstance(session_id, str) and session_id else None
        if message.subtype == "init" and sid is not None:
            self._note_session(sid)
            return [{"type": "system", "subtype": "init", "session_id": sid}]
        subtype = message.subtype if message.subtype else "system"
        return [{"type": "system", "subtype": subtype}]

    def _session_prefix(self, session_id: str | None) -> list[dict[str, object]]:
        if session_id is None or self._saw_session:
            return []
        self._note_session(session_id)
        return [{"type": "system", "subtype": "init", "session_id": session_id}]

    def _note_session(self, session_id: str) -> None:
        self._saw_session = True
        self.session_ref = session_id

    def _content_natives(self, message: object) -> list[dict[str, object]]:
        if isinstance(message, AssistantMessage):
            natives = [native for block in message.content if (native := self._block_native(block))]
            if message.error:
                natives.append({"type": "error", "code": message.error, "message": message.error})
            return natives
        if isinstance(message, UserMessage):
            if isinstance(message.content, str):
                return [{"type": "user"}]
            return [native for block in message.content if (native := self._block_native(block))]
        if isinstance(message, StreamEvent):
            return [{"type": "stream_event", "event": _as_dict(message.event)}]
        if isinstance(message, ResultMessage):
            errors = message.errors
            return [
                {
                    "type": "result",
                    "subtype": message.subtype,
                    "is_error": message.is_error,
                    "terminal_reason": message.terminal_reason,
                    "usage": _as_dict(message.usage) if isinstance(message.usage, dict) else None,
                    "result": message.result if isinstance(message.result, str) else None,
                    "errors": [item for item in errors if isinstance(item, str)]
                    if isinstance(errors, list)
                    else None,
                }
            ]
        if isinstance(message, RateLimitEvent):
            return [{"type": "rate_limit_event"}]
        if isinstance(message, ConversationResetMessage):
            return [{"type": "conversation_reset"}]
        return [{"type": "unknown"}]

    def _block_native(self, block: ContentBlock) -> dict[str, object] | None:
        if isinstance(block, TextBlock):
            return {"type": "assistant", "block": {"type": "text", "text": block.text}}
        if isinstance(block, ThinkingBlock):
            return {"type": "assistant", "block": {"type": "thinking", "thinking": block.thinking}}
        if isinstance(block, ToolUseBlock | ServerToolUseBlock):
            self._tool_names[block.id] = block.name
            return {
                "type": "assistant",
                "block": {
                    "type": "tool_use",
                    "name": block.name,
                    "input": _as_dict(block.input),
                    "id": block.id,
                },
            }
        if isinstance(block, ToolResultBlock | ServerToolResultBlock):
            name = self._tool_names.get(block.tool_use_id, "")
            if not name:
                return {"type": "user"}
            is_error = bool(block.is_error) if isinstance(block, ToolResultBlock) else False
            return {
                "type": "user",
                "block": {"type": "tool_result", "name": name, "is_error": is_error},
            }
        return None

    def _write_fixture(self) -> None:
        if not self._turn_natives:
            return
        kinds = [
            event.kind
            for native in self._turn_natives
            if (event := map_native_event("claude", native)).kind != "ignored"
        ]
        if "session_bound" not in kinds or "turn_finished" not in kinds:
            return
        if kinds.index("session_bound") > kinds.index("turn_finished"):
            return
        _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        lines = [_scrub(json.dumps(native, ensure_ascii=False)) for native in self._turn_natives]
        (_FIXTURE_DIR / f"{uuid.uuid4().hex}.jsonl").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

    def _remember_stderr(self, line: str) -> None:
        self._stderr.append(line)
        if len(self._stderr) > 100:
            del self._stderr[:-100]

    def _require_client(self) -> ClaudeSDKClient:
        if self._client is None:
            raise RuntimeError("claude session is closed")
        return self._client


async def open_claude_session(workspace: Path, session_ref: str | None) -> ClaudeSession:
    """Start a Claude session in ``workspace``, optionally resuming ``session_ref``."""

    manager = echo_server(session_ref or uuid.uuid4().hex)
    server = manager.__enter__()
    session = ClaudeSession(workspace, server, manager, session_ref)
    try:
        await session.connect()
    except BaseException:
        await session.aclose()
        raise
    return session


def _session_id(message: object) -> str | None:
    value = getattr(message, "session_id", None)
    if isinstance(value, str) and value:
        return value
    return None


async def _invoke(
    callback: Callable[[RuntimeEvent], object] | None,
    event: RuntimeEvent,
) -> object:
    if callback is None:
        return None
    result = callback(event)
    if inspect.isawaitable(result):
        return await result
    return result


def _as_dict(value: object) -> dict[str, object]:
    plain = _plain(value)
    if isinstance(plain, dict):
        return cast(dict[str, object], plain)
    return {}


def _plain(value: object) -> object:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return str(value)


def _scrub(text: str) -> str:
    home = Path.home().as_posix()
    if home:
        text = text.replace(home, "<HOME>")
    for pattern, replacement in _SCRUBBERS:
        text = pattern.sub(replacement, text)
    return text
