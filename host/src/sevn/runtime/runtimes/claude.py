"""Claude runtime: claude-agent-sdk on the user's own login (spec §4, D8)."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from claude_agent_sdk import (
    AssistantMessage,
    CanUseTool,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
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
from claude_agent_sdk.types import (
    ContentBlock,
    ConversationResetMessage,
    RateLimitEvent,
    SystemPromptPreset,
)

from sevn.domain.agents import AgentRecord, sibling_block
from sevn.domain.bots import BotService
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.protocol.hub import Hub
from sevn.runtime.base import PendingAnswer, SessionRef, TurnContext
from sevn.runtime.errors import TurnError
from sevn.runtime.events import RuntimeEvent
from sevn.runtime.runtimes.pydantic_ai import build_instructions
from sevn.runtime.usage import usage_record
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import PendingRequest as PendingRow
from sevn.store.models import Turn as TurnRow

_INTERRUPTED = frozenset({"aborted_streaming", "aborted_tools"})
_DENY = "Permission denied. Request permission again and retry the same tool."

type _Ask = Callable[[str, object, object], str | Awaitable[str]]


class ClaudeClient(Protocol):
    """The slice of ``ClaudeSDKClient`` the runtime drives.

    ``receive_response`` yields spike-shaped native dicts, not SDK messages.
    """

    async def connect(
        self,
        cwd: str | None = None,
        resume: str | None = None,
        can_use_tool: object = None,
        **options: object,
    ) -> None: ...

    async def query(self, prompt: str, **options: object) -> None: ...

    def receive_response(self) -> AsyncIterator[dict[str, object]]: ...

    async def interrupt(self) -> None: ...


class SdkClaudeClient:
    """``ClaudeSDKClient`` that yields the spike's native dicts."""

    def __init__(self) -> None:
        self._sdk: ClaudeSDKClient | None = None
        self._tool_names: dict[str, str] = {}
        self._saw_session = False

    async def connect(
        self,
        cwd: str | None = None,
        resume: str | None = None,
        can_use_tool: object = None,
        **options: object,
    ) -> None:
        if self._sdk is not None:
            await self.disconnect()
        self._tool_names = {}
        self._saw_session = False
        system_prompt = options.get("system_prompt")
        model = options.get("model")
        env = options.get("env")
        sdk_options = ClaudeAgentOptions(
            cwd=cwd,
            resume=resume if isinstance(resume, str) and resume != "" else None,
            permission_mode="default",
            can_use_tool=_sdk_hook(can_use_tool),
            include_partial_messages=True,
            system_prompt=_preset_prompt(system_prompt),
            model=model if isinstance(model, str) and model != "" else None,
            env=_env_map(env),
        )
        self._sdk = ClaudeSDKClient(sdk_options)
        await self._sdk.connect()

    async def query(self, prompt: str, **options: object) -> None:
        session_id = options.get("session_id")
        chosen = session_id if isinstance(session_id, str) and session_id != "" else "default"
        await self._require().query(prompt, session_id=chosen)

    async def receive_response(self) -> AsyncIterator[dict[str, object]]:
        async for message in self._require().receive_response():
            for native in self._natives(message):
                yield native

    async def interrupt(self) -> None:
        if self._sdk is None:
            return
        await self._sdk.interrupt()

    async def disconnect(self) -> None:
        sdk = self._sdk
        self._sdk = None
        if sdk is not None:
            await sdk.disconnect()

    def _require(self) -> ClaudeSDKClient:
        sdk = self._sdk
        if sdk is None:
            raise TurnError("claude session is closed")
        return sdk

    def _natives(self, message: object) -> list[dict[str, object]]:
        if isinstance(message, SystemMessage):
            return self._system(message)
        natives = self._session_prefix(_session_id(message))
        natives.extend(_content_natives(message, self._tool_names))
        return natives

    def _system(self, message: SystemMessage) -> list[dict[str, object]]:
        session_id = _mapping_str(message.data, "session_id")
        if message.subtype == "init" and session_id is not None:
            self._note_session(session_id)
            return [{"type": "system", "subtype": "init", "session_id": session_id}]
        subtype = message.subtype if message.subtype != "" else "system"
        return [{"type": "system", "subtype": subtype}]

    def _session_prefix(self, session_id: str | None) -> list[dict[str, object]]:
        if session_id is None or self._saw_session:
            return []
        self._note_session(session_id)
        return [{"type": "system", "subtype": "init", "session_id": session_id}]

    def _note_session(self, session_id: str) -> None:
        self._saw_session = True


@dataclass(slots=True)
class _Wait:
    future: asyncio.Future[str]
    delivered: asyncio.Event


_installed: ClaudeClient | None = None
_waits: dict[str, _Wait] = {}


def use_client(client: ClaudeClient | None) -> None:
    """Install ``client`` for the next ``ClaudeRuntime`` the worker builds.

    ``None`` clears it. A runtime constructed with an explicit client ignores this.
    The worker reads the override when it is created, so call this before ``bind``.
    """
    global _installed
    _installed = client


def installed_client() -> ClaudeClient | None:
    """The client ``use_client`` installed, if any."""
    return _installed


async def release_permission(pending_id: str, decision: str) -> bool:
    """Wake the in-memory ``can_use_tool`` wait for ``pending_id``.

    Returns false when the wait is not in this process. Claude approvals do not
    survive a restart; those turns are marked interrupted instead.
    """
    wait = _waits.get(pending_id)
    if wait is None:
        return False
    if not wait.future.done():
        wait.future.set_result(decision)
    await wait.delivered.wait()
    return True


class ClaudeRuntime:
    """One Claude Code session per agent. Permissions block inside ``can_use_tool``."""

    def __init__(self, client: ClaudeClient | None = None, hub: Hub | None = None) -> None:
        self._shared = client
        self._hub = hub
        self._owned: dict[str, SdkClaudeClient] = {}
        self._turns: dict[str, TurnContext] = {}

    async def open(self, agent: AgentRecord) -> SessionRef:
        bot = await BotService().get(agent.bot_id)
        client = self._client_for(agent.id)

        async def _can_use_tool(tool: str, args: object, request_id: object) -> str:
            return await self._ask(agent.id, tool, args, request_id)

        siblings = await sibling_block(agent.bot_id, agent.id)
        await client.connect(
            cwd=bot.workspace_path,
            resume=agent.runtime_session_ref,
            can_use_tool=_can_use_tool,
            system_prompt=build_instructions(bot, siblings=siblings),
            model=_claude_model(bot.model),
            env=blanked_env(),
        )
        return SessionRef(agent_id=agent.id, session_ref=agent.runtime_session_ref)

    async def run_turn(self, turn: TurnContext) -> AsyncIterator[RuntimeEvent]:
        agent_id = turn.agent.id
        self._turns[agent_id] = turn
        client = self._client_for(agent_id)
        saw_text = False
        session_id = turn.agent.runtime_session_ref or "default"
        try:
            with logger.contextualize(agent_id=agent_id, turn_id=turn.turn_id):
                logger.info("claude turn started")
            await client.query(turn.text, session_id=session_id)
            async for native in client.receive_response():
                event = map_claude_event(native)
                if event.kind == "session_bound" and event.session_ref is not None:
                    await _save_session_ref(agent_id, event.session_ref)
                if event.kind == "text_delta" and event.text:
                    saw_text = True
                if event.kind == "ignored":
                    continue
                if event.kind == "turn_finished":
                    event.model_messages = []
                    if not saw_text and event.text:
                        yield RuntimeEvent(kind="text_delta", text=event.text)
                yield event
        finally:
            self._turns.pop(agent_id, None)

    async def answer(self, pending_id: str, answer: PendingAnswer) -> None:
        await release_permission(pending_id, answer.decision)

    async def interrupt(self, agent_id: str) -> None:
        await self._client_for(agent_id).interrupt()

    async def close(self, agent_id: str) -> None:
        owned = self._owned.get(agent_id)
        if owned is not None:
            await owned.disconnect()
        self._turns.pop(agent_id, None)

    def _client_for(self, agent_id: str) -> ClaudeClient:
        if self._shared is not None:
            return self._shared
        found = self._owned.get(agent_id)
        if found is None:
            found = SdkClaudeClient()
            self._owned[agent_id] = found
        return found

    async def _ask(self, agent_id: str, tool: str, args: object, request_id: object) -> str:
        turn = self._turns.get(agent_id)
        turn_id = None if turn is None else turn.turn_id
        if turn_id is None or not await _turn_exists(turn_id):
            return "deny"
        if _policy_allows(turn):
            return "approve"
        if isinstance(request_id, str) and request_id != "":
            call_id = request_id
        else:
            call_id = new_id("call_")
        pending_id = new_id("pend_")
        wait = _Wait(
            future=asyncio.get_running_loop().create_future(),
            delivered=asyncio.Event(),
        )
        _waits[pending_id] = wait
        await _insert_pending(
            pending_id=pending_id,
            turn_id=turn_id,
            agent_id=agent_id,
            tool_call_id=call_id,
            name=tool,
            args=_json_object(args),
        )
        hub = self._hub
        if hub is not None:
            await hub.emit(
                "pending.created",
                pending_id,
                {
                    "pending_id": pending_id,
                    "turn_id": turn_id,
                    "agent_id": agent_id,
                    "kind": "approval",
                },
            )
        logger.info("claude permission requested")
        try:
            decision = await wait.future
        finally:
            wait.delivered.set()
            _waits.pop(pending_id, None)
        if decision == "approve":
            return "approve"
        return "deny"


_KEEP_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TERM",
        "SSH_AUTH_SOCK",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "CLAUDE_CONFIG_DIR",
    }
)


def blanked_env() -> dict[str, str]:
    """Overlay that blanks every parent env var the Claude CLI must not inherit.

    The SDK merges this dict over ``os.environ``. A missing key is still inherited,
    so every other key is set to an empty string.
    """
    overlay: dict[str, str] = {}
    for key, value in os.environ.items():
        overlay[key] = value if _keep_env(key) else ""
    return overlay


def _keep_env(key: str) -> bool:
    if key in _KEEP_ENV or key.startswith("LC_"):
        return True
    if key.startswith("CLAUDE_") and "API_KEY" not in key and "SECRET" not in key:
        return True
    return False


def _claude_model(model: str) -> str | None:
    prefix = "anthropic:"
    if not model.startswith(prefix):
        return None
    name = model[len(prefix) :]
    if name == "":
        return None
    return name


def _preset_prompt(value: object) -> SystemPromptPreset | None:
    if isinstance(value, str) and value != "":
        return SystemPromptPreset(type="preset", preset="claude_code", append=value)
    if isinstance(value, dict):
        body = cast("dict[object, object]", value)
        if body.get("type") == "preset":
            return cast("SystemPromptPreset", value)
    return None


def _env_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return blanked_env()
    mapped: dict[str, str] = {}
    items = cast("dict[object, object]", value)
    for key, item in items.items():
        if isinstance(key, str) and isinstance(item, str):
            mapped[key] = item
    if mapped:
        return mapped
    return blanked_env()


def _policy_allows(turn: TurnContext | None) -> bool:
    """Per-bot auto and allow_all still wait. Host-wide allow_all is not a bot field."""
    _ = turn
    return False


def map_claude_event(native: Mapping[str, object]) -> RuntimeEvent:
    """Map one spike-shaped Claude native object to a sevn ``RuntimeEvent``."""
    body = _record(native)
    if body is None:
        return _ignored("unknown")
    native_type = body.get("type")
    if native_type == "system":
        return _map_system(body)
    if native_type == "stream_event":
        return _map_stream(body.get("event"))
    if native_type == "assistant":
        return _map_block(body.get("block"))
    if native_type == "user":
        block = _record(body.get("block"))
        if block is not None and block.get("type") == "tool_result":
            return _map_block(block)
        return _ignored("user")
    if native_type == "result":
        return _map_result(body)
    if native_type == "permission_request":
        return _map_permission(body)
    if native_type == "error":
        return _map_error(body)
    if isinstance(native_type, str):
        return _ignored(native_type)
    return _ignored("unknown")


def _sdk_hook(callback: object) -> CanUseTool:
    async def _hook(
        tool_name: str,
        tool_input: dict[str, object],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        request_id = context.tool_use_id if isinstance(context.tool_use_id, str) else ""
        decision = await _invoke_ask(callback, tool_name, tool_input, request_id)
        if decision == "approve":
            return PermissionResultAllow()
        return PermissionResultDeny(message=_DENY, interrupt=False)

    return cast("CanUseTool", _hook)


async def _invoke_ask(callback: object, tool: str, args: object, request_id: str) -> str:
    if not callable(callback):
        return "deny"
    ask = cast("_Ask", callback)
    outcome = ask(tool, args, request_id)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    if outcome == "approve":
        return "approve"
    return "deny"


def _content_natives(
    message: object,
    tool_names: dict[str, str],
) -> list[dict[str, object]]:
    if isinstance(message, AssistantMessage):
        natives = [_block_native(block, tool_names) for block in message.content]
        found = [native for native in natives if native is not None]
        if message.error is not None:
            found.append({"type": "error", "code": message.error, "message": message.error})
        return found
    if isinstance(message, UserMessage):
        if isinstance(message.content, str):
            return [{"type": "user"}]
        natives = [_block_native(block, tool_names) for block in message.content]
        return [native for native in natives if native is not None]
    if isinstance(message, StreamEvent):
        return [{"type": "stream_event", "event": _json_object(message.event)}]
    if isinstance(message, ResultMessage):
        return [_result_native(message)]
    if isinstance(message, RateLimitEvent):
        return [{"type": "rate_limit_event"}]
    if isinstance(message, ConversationResetMessage):
        return [{"type": "conversation_reset"}]
    return [{"type": "unknown"}]


def _block_native(block: ContentBlock, tool_names: dict[str, str]) -> dict[str, object] | None:
    if isinstance(block, TextBlock):
        return {"type": "assistant", "block": {"type": "text", "text": block.text}}
    if isinstance(block, ThinkingBlock):
        return {"type": "assistant", "block": {"type": "thinking", "thinking": block.thinking}}
    if isinstance(block, ToolUseBlock | ServerToolUseBlock):
        tool_names[block.id] = block.name
        return {
            "type": "assistant",
            "block": {
                "type": "tool_use",
                "name": block.name,
                "input": _json_object(block.input),
                "id": block.id,
            },
        }
    name = tool_names.get(block.tool_use_id, "")
    if name == "":
        return {"type": "user"}
    is_error = isinstance(block, ToolResultBlock) and bool(block.is_error)
    return {
        "type": "user",
        "block": {"type": "tool_result", "name": name, "is_error": is_error},
    }


def _result_native(message: ResultMessage) -> dict[str, object]:
    usage = _json_object(message.usage) if isinstance(message.usage, dict) else None
    return {
        "type": "result",
        "subtype": message.subtype,
        "is_error": message.is_error,
        "terminal_reason": message.terminal_reason,
        "usage": usage,
        "total_cost_usd": message.total_cost_usd,
        "num_turns": message.num_turns,
        "result": message.result,
        "errors": None if message.errors is None else list(message.errors),
    }


def _session_id(message: object) -> str | None:
    if isinstance(message, AssistantMessage | StreamEvent | ResultMessage | RateLimitEvent):
        value = message.session_id
        if isinstance(value, str) and value != "":
            return value
    return None


def _map_system(native: dict[str, object]) -> RuntimeEvent:
    session_id = native.get("session_id")
    if native.get("subtype") == "init" and isinstance(session_id, str) and session_id != "":
        return RuntimeEvent(kind="session_bound", session_ref=session_id)
    return _ignored("system")


def _map_stream(event: object) -> RuntimeEvent:
    body = _record(event)
    if body is None or body.get("type") != "content_block_delta":
        return _ignored("stream_event")
    delta = _record(body.get("delta"))
    if delta is None:
        return _ignored("stream_event")
    text = delta.get("text")
    if delta.get("type") == "text_delta" and isinstance(text, str):
        return RuntimeEvent(kind="text_delta", text=text)
    thinking = delta.get("thinking")
    if delta.get("type") == "thinking_delta" and isinstance(thinking, str):
        return RuntimeEvent(kind="thinking_delta", text=thinking)
    return _ignored("stream_event")


def _map_block(block: object) -> RuntimeEvent:
    body = _record(block)
    if body is None:
        return _ignored("assistant")
    block_type = body.get("type")
    text = body.get("text")
    if block_type == "text" and isinstance(text, str):
        return _ignored("assistant")
    thinking = body.get("thinking")
    if block_type == "thinking" and isinstance(thinking, str):
        return RuntimeEvent(kind="thinking_delta", text=thinking)
    if block_type == "tool_use":
        name = body.get("name")
        if isinstance(name, str) and name != "":
            return RuntimeEvent(
                kind="tool_call_started",
                name=name,
                args=_json_object(body.get("input")),
            )
    if block_type == "tool_result":
        name = body.get("name")
        if isinstance(name, str) and name != "":
            return RuntimeEvent(
                kind="tool_call_finished",
                name=name,
                ok=body.get("is_error") is not True,
            )
    return _ignored("assistant")


def _map_permission(native: dict[str, object]) -> RuntimeEvent:
    tool = native.get("tool")
    request_id = native.get("request_id")
    args = _record(native.get("args"))
    if isinstance(tool, str) and tool != "" and args is not None and isinstance(request_id, str):
        if request_id != "":
            return RuntimeEvent(
                kind="permission_request",
                tool=tool,
                args=args,
                request_id=request_id,
            )
    return _ignored("permission_request")


def _map_result(native: dict[str, object]) -> RuntimeEvent:
    terminal = native.get("terminal_reason")
    if terminal in _INTERRUPTED:
        return RuntimeEvent(
            kind="error",
            code="interrupted",
            message=_message_text(native),
            usage=_claude_usage(native),
        )
    if native.get("is_error") is True:
        code = native.get("subtype")
        return RuntimeEvent(
            kind="error",
            code=code if isinstance(code, str) and code != "" else "error",
            message=_message_text(native),
            # An error result still reports what the run used.
            usage=_claude_usage(native),
        )
    result = native.get("result")
    return RuntimeEvent(
        kind="turn_finished",
        text=result if isinstance(result, str) and result != "" else None,
        usage=_claude_usage(native),
        model_messages=[],
    )


def _claude_usage(native: dict[str, object]) -> dict[str, object]:
    """The shared usage shape. A Claude turn runs on the user's own login."""
    raw = _json_object(native.get("usage")) or {}
    estimate = native.get("total_cost_usd")
    turns = native.get("num_turns")
    cache_read = _count(raw.get("cache_read_input_tokens"))
    cache_write = _count(raw.get("cache_creation_input_tokens"))
    return usage_record(
        {
            "requests": turns if isinstance(turns, int) else 0,
            # Anthropic's input_tokens leaves out cache reads and writes. The
            # shared shape, like pydantic-ai, counts them in the input.
            "input_tokens": _count(raw.get("input_tokens")) + cache_read + cache_write,
            "output_tokens": raw.get("output_tokens"),
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
        },
        cost_usd=None,
        cost_source="subscription",
        estimated_usd=float(estimate) if isinstance(estimate, int | float) else None,
    )


def _count(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _map_error(native: dict[str, object]) -> RuntimeEvent:
    code = native.get("code")
    message = native.get("message")
    if isinstance(code, str) and code != "" and isinstance(message, str):
        return RuntimeEvent(kind="error", code=code, message=message)
    return _ignored("unknown")


def _message_text(native: dict[str, object]) -> str:
    parts = _strings(native.get("errors"))
    if len(parts) > 0:
        return "\n".join(parts)
    result = native.get("result")
    if isinstance(result, str):
        return result
    return ""


def _record(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        raw = cast("dict[object, object]", value)
        return {str(key): item for key, item in raw.items()}
    if not isinstance(value, Mapping):
        return None
    raw_map = cast("Mapping[object, object]", value)
    return {str(key): item for key, item in raw_map.items()}


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    raw = cast("list[object]", value)
    return [item for item in raw if isinstance(item, str)]


def _ignored(native_type: str) -> RuntimeEvent:
    return RuntimeEvent(kind="ignored", native_type=native_type)


def _mapping_str(value: object, key: str) -> str | None:
    body = _record(value)
    if body is None:
        return None
    found = body.get(key)
    if isinstance(found, str) and found != "":
        return found
    return None


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    try:
        encoded = json.dumps(value)
    except TypeError:
        return {}
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        return {}
    body: dict[str, object] = {}
    for key, item in cast("dict[object, object]", loaded).items():
        body[str(key)] = item
    return body


async def _save_session_ref(agent_id: str, session_ref: str) -> None:
    async with open_session() as session:
        row = await session.get(AgentRow, agent_id)
        if row is None:
            return
        row.runtime_session_ref = session_ref
        await session.commit()


async def _turn_exists(turn_id: str) -> bool:
    async with open_session() as session:
        row = await session.get(TurnRow, turn_id)
        return row is not None


async def _insert_pending(
    *,
    pending_id: str,
    turn_id: str,
    agent_id: str,
    tool_call_id: str,
    name: str,
    args: dict[str, object],
) -> None:
    payload: dict[str, object] = {"name": name, "args": args}
    async with open_session() as session:
        session.add(
            PendingRow(
                id=pending_id,
                turn_id=turn_id,
                agent_id=agent_id,
                kind="approval",
                tool_call_id=tool_call_id,
                payload=payload,
                answer=None,
                status="waiting",
                created_at=utcnow(),
                resolved_at=None,
            )
        )
        await session.commit()
