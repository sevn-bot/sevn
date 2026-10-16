"""ACP adapter for ``opencode acp`` and ``cursor-agent acp`` (D5, D6).

One subprocess per session. Resume is ``session/load``. Interrupt is
``session/cancel``. Cursor uses the same client; a failure there is bonus D6.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from acp import PROTOCOL_VERSION, spawn_agent_process
from acp.client.connection import ClientSideConnection
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    DeniedOutcome,
    FileSystemCapabilities,
    HttpHeader,
    HttpMcpServer,
    Implementation,
    PermissionOption,
    RequestPermissionResponse,
    TextContentBlock,
    ToolCallUpdate,
)

from spike_rt.events import RuntimeEvent, map_native_event
from spike_rt.mcp_server import BoundServer, echo_server
from spike_rt.transcripts import GUIDE, invoke, note_metric, scrub, write_guide, write_turn_fixture

_COMMANDS = {
    "opencode": ("opencode", "acp"),
    "cursor": ("cursor-agent", "acp"),
}
_ALLOW = ("allow_once", "allow_always")
_REJECT = ("reject_once", "reject_always")
# OpenCode 2.0.15 ends the prompt on reject_once. Follow-ups must be tool calls:
# a prose "please grant permission" does not raise session/request_permission.
_DENY_RETRY = (
    "Permission was rejected. Invoke the same tool again right now with the "
    "arguments the user asked for. Do not ask the user to grant permission and "
    "do not describe the plan. The tool call is what requests permission."
)
_DENY_RETRY_AGAIN = (
    "You replied with text and did not call a tool. Call the tool now, before "
    "any other text. Do not ask the user a question."
)

PermissionCallback = Callable[[RuntimeEvent], str | Awaitable[str]]
EventCallback = Callable[[RuntimeEvent], Awaitable[None] | None]


class AcpSession:
    """One ACP CLI process bound to a workspace and a loopback MCP server."""

    def __init__(
        self,
        runtime: str,
        workspace: Path,
        server: BoundServer,
        manager: object,
        session_ref: str | None,
    ) -> None:
        self.runtime = runtime
        self._workspace = workspace
        self._server = server
        self._manager = manager
        self._resumed = session_ref is not None
        self._client = _AcpClient(self)
        self._cm: object | None = None
        self._conn: ClientSideConnection | None = None
        self._closed = False
        self._in_turn = False
        self._interrupt_sent = False
        self._tool_names: dict[str, str] = {}
        self._on_permission: PermissionCallback | None = None
        self._on_event: EventCallback | None = None
        self._saw_deny = False
        self._saw_approve = False
        self._permission_count = 0
        self._events: list[RuntimeEvent] = []
        self._natives: list[dict[str, object]] = []
        self._turn_started = 0.0
        self._first_text: float | None = None
        self.session_ref = session_ref
        self.bearer = server.bearer
        self.mcp_calls = server.calls

    async def connect(self) -> None:
        command = _COMMANDS.get(self.runtime)
        if command is None:
            raise RuntimeError(f"runtime {self.runtime!r} is not an ACP runtime")
        binary = shutil.which(command[0])
        if binary is None:
            raise RuntimeError(f"{command[0]} is not on PATH")
        _write_runtime_files(self.runtime, self._workspace)
        context = spawn_agent_process(
            self._client,
            binary,
            *command[1:],
            cwd=self._workspace,
            env=_child_env(self.runtime, self._workspace),
        )
        self._conn, _process = await context.__aenter__()
        self._cm = context
        try:
            await self._conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_capabilities=ClientCapabilities(
                    fs=FileSystemCapabilities(read_text_file=False, write_text_file=False),
                    terminal=False,
                ),
                client_info=Implementation(name="sevn-spike", version="0.1.0"),
            )
            await self._open_session()
        except Exception as exc:
            raise RuntimeError(self._scrub(f"{self.runtime} session failed: {exc}")) from exc

    async def turn(
        self,
        prompt: str,
        *,
        on_permission: PermissionCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> list[RuntimeEvent]:
        conn = self._require_conn()
        if not self.session_ref:
            raise RuntimeError(f"{self.runtime} session is not bound")
        self._on_permission = on_permission
        self._on_event = on_event
        self._events = []
        self._natives = []
        self._saw_deny = False
        self._saw_approve = False
        self._permission_count = 0
        self._interrupt_sent = False
        self._in_turn = True
        self._turn_started = time.monotonic()
        self._first_text = None
        try:
            await self._push(
                {
                    "type": "session",
                    "subtype": "load" if self._resumed else "new",
                    "session_id": self.session_ref,
                }
            )
            await self._complete_prompt(conn, prompt, recover_deny=True)
            # A rejected OpenCode call ends the prompt. Nudge until a tool call
            # raises a new permission request, at most twice.
            nudge = _DENY_RETRY
            for _ in range(2):
                if not self._needs_deny_retry():
                    break
                before = self._permission_count
                await self._complete_prompt(conn, nudge, recover_deny=False)
                if self._permission_count > before:
                    break
                nudge = _DENY_RETRY_AGAIN
        finally:
            self._in_turn = False
            self._on_permission = None
            self._on_event = None
            write_turn_fixture(
                self.runtime,
                self._natives,
                secrets=(self.bearer,),
                paths=(str(self._workspace),),
            )
            last = self._events[-1] if self._events else None
            note_metric(
                {
                    "runtime": self.runtime,
                    "first_text_s": _seconds(self._first_text),
                    "terminal": last.kind if last else None,
                    "code": last.code if last else None,
                    "error": last.message if last and last.kind == "error" else None,
                }
            )
        return list(self._events)

    async def _complete_prompt(
        self,
        conn: ClientSideConnection,
        prompt: str,
        *,
        recover_deny: bool,
    ) -> None:
        session_id = self.session_ref
        if not session_id:
            raise RuntimeError(f"{self.runtime} session is not bound")
        try:
            response = await conn.prompt(
                session_id,
                [TextContentBlock(type="text", text=prompt)],
            )
        except Exception as exc:
            retry = recover_deny and self._needs_deny_retry()
            if not self._interrupt_sent and not retry:
                message = self._scrub(f"{self.runtime} prompt failed: {exc}")
                raise RuntimeError(message) from exc
            await self._push({"type": "prompt_response", "stopReason": "cancelled"})
            return
        usage = _usage(response.usage)
        native: dict[str, object] = {
            "type": "prompt_response",
            "stopReason": response.stop_reason,
        }
        if usage is not None:
            native["usage"] = usage
        await self._push(native)

    def _needs_deny_retry(self) -> bool:
        return (
            self.runtime == "opencode"
            and self._saw_deny
            and not self._saw_approve
            and not self._interrupt_sent
        )

    async def interrupt(self) -> None:
        self._interrupt_sent = True
        conn = self._conn
        if conn is None or not self.session_ref:
            return
        await conn.cancel(self.session_ref)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._conn = None
        cm = self._cm
        self._cm = None
        try:
            if cm is not None:
                await cm.__aexit__(None, None, None)
        finally:
            _close_manager(self._manager)

    async def _open_session(self) -> None:
        conn = self._require_conn()
        mcp_servers = [
            HttpMcpServer(
                name="sevn",
                url=self._server.url,
                headers=[HttpHeader(name="Authorization", value=f"Bearer {self.bearer}")],
                type="http",
            )
        ]
        cwd = str(self._workspace)
        if self.session_ref:
            await conn.load_session(cwd=cwd, session_id=self.session_ref, mcp_servers=mcp_servers)
            return
        created = await conn.new_session(cwd=cwd, mcp_servers=mcp_servers)
        self.session_ref = created.session_id

    async def _push(self, native: dict[str, object]) -> RuntimeEvent:
        event = map_native_event(self.runtime, native)
        self._natives.append(native)
        self._events.append(event)
        if event.kind == "session_bound" and event.session_ref:
            self.session_ref = event.session_ref
        if event.kind == "text_delta" and event.text and self._first_text is None:
            self._first_text = time.monotonic() - self._turn_started
        await invoke(self._on_event, event)
        return event

    def _require_conn(self) -> ClientSideConnection:
        if self._conn is None:
            raise RuntimeError(f"{self.runtime} session is closed")
        return self._conn

    def _scrub(self, text: str) -> str:
        return scrub(text, secrets=(self.bearer,), paths=(str(self._workspace),))


class _AcpClient:
    """Client callbacks the ACP agent invokes while a turn is running."""

    def __init__(self, session: AcpSession) -> None:
        self._session = session

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **_kwargs: object,
    ) -> RequestPermissionResponse:
        del session_id
        name = _tool_name(tool_call)
        tool_id = tool_call.tool_call_id or uuid.uuid4().hex
        self._session._tool_names[tool_id] = name
        event = await self._session._push(
            {
                "type": "permission_request",
                "tool": name,
                "args": _raw_args(tool_call),
                "request_id": tool_id,
            }
        )
        self._session._permission_count += 1
        decision = await invoke(self._session._on_permission, event)
        # No callback means allow for OpenCode (resume turns omit one). An explicit
        # deny selects reject_once so the tool does not run.
        reject = decision == "deny" or (
            self._session.runtime != "opencode" and decision != "approve"
        )
        if reject:
            self._session._saw_deny = True
            kinds = _REJECT
        else:
            if decision == "approve":
                self._session._saw_approve = True
            kinds = _ALLOW
        option = _pick(options, kinds)
        if option is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=option.option_id)
        )

    async def session_update(self, session_id: str, update: object, **_kwargs: object) -> None:
        del session_id
        if not self._session._in_turn:
            return
        for native in _update_natives(self._session, update):
            await self._session._push(native)

    async def ext_method(self, method: str, params: dict[str, object]) -> dict[str, object]:
        del method, params
        return {}

    async def ext_notification(self, method: str, params: dict[str, object]) -> None:
        del method, params


async def open_acp_session(
    runtime: str,
    workspace: Path,
    session_ref: str | None,
) -> AcpSession:
    """Start an ACP session in ``workspace``, optionally resuming ``session_ref``."""

    write_guide(workspace)
    manager = echo_server(session_ref or uuid.uuid4().hex)
    server = manager.__enter__()
    session = AcpSession(runtime, _absolute(workspace), server, manager, session_ref)
    try:
        await session.connect()
    except BaseException:
        await session.aclose()
        raise
    return session


def _child_env(runtime: str, workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    if runtime == "opencode":
        # The user's global file watcher indexes every project. Keep this process local.
        env["OPENCODE_DISABLE_FILEWATCHER"] = "1"
        env["OPENCODE_FILEWATCHER_DISABLE"] = "1"
        env["OPENCODE_FAST_BOOT"] = "1"
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"
        # Process-local only. A user config that allows edit/shell would skip the prompt.
        config_dir = workspace / ".opencode-spike"
        _write_opencode_config(config_dir)
        env["OPENCODE_CONFIG_DIR"] = str(config_dir)
    return env


def _write_opencode_config(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "permissions": [{"action": "*", "resource": "*", "effect": "ask"}],
        "experimental": {"continue_loop_on_deny": True},
    }
    (config_dir / "opencode.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _write_runtime_files(runtime: str, workspace: Path) -> None:
    guide = workspace / "AGENTS.md"
    if guide.is_file():
        text = guide.read_text(encoding="utf-8")
        if GUIDE not in text:
            guide.write_text(text.rstrip() + "\n\n" + GUIDE + "\n", encoding="utf-8")
    if runtime != "opencode":
        return


def _update_natives(session: AcpSession, update: object) -> list[dict[str, object]]:
    kind = getattr(update, "session_update", None)
    if not isinstance(kind, str):
        return []
    if kind in {"agent_message_chunk", "agent_thought_chunk"}:
        text = _chunk_text(update)
        body: dict[str, object] = {"sessionUpdate": kind}
        if text:
            body["text"] = text
        return [{"type": "session_update", "update": body}]
    if kind == "tool_call":
        name = _remember_tool(session, update)
        natives: list[dict[str, object]] = [
            {
                "type": "session_update",
                "update": {
                    "sessionUpdate": "tool_call",
                    "tool": name,
                    "args": _raw_args(update),
                },
            }
        ]
        status = getattr(update, "status", None)
        if status in {"completed", "failed"}:
            natives.append(_tool_finished(name, status))
        return natives
    if kind == "tool_call_update":
        name = _remember_tool(session, update)
        status = getattr(update, "status", None)
        if status in {"completed", "failed"}:
            return [_tool_finished(name, status)]
        if isinstance(status, str):
            return [_tool_progress(name, status)]
        return [{"type": "session_update", "update": {"sessionUpdate": kind}}]
    return [{"type": "session_update", "update": {"sessionUpdate": kind}}]


def _tool_finished(name: str, status: str) -> dict[str, object]:
    return {
        "type": "session_update",
        "update": {"sessionUpdate": "tool_call_update", "tool": name, "status": status},
    }


def _tool_progress(name: str, status: str) -> dict[str, object]:
    return {
        "type": "session_update",
        "update": {"sessionUpdate": "tool_call_update", "tool": name, "status": status},
    }


def _remember_tool(session: AcpSession, update: object) -> str:
    name = _tool_name(update)
    tool_id = getattr(update, "tool_call_id", None)
    if isinstance(tool_id, str) and tool_id:
        if name == "tool":
            name = session._tool_names.get(tool_id, name)
        else:
            session._tool_names[tool_id] = name
    return name


def _tool_name(update: object) -> str:
    raw = getattr(update, "raw_input", None)
    title = getattr(update, "title", None)
    if isinstance(raw, dict):
        for key in ("name", "tool", "toolName"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                return value
        if "sevn_echo" in json.dumps(raw, default=str):
            return "sevn_echo"
    if isinstance(title, str) and title:
        if "sevn_echo" in title:
            return "sevn_echo"
        return title
    return "tool"


def _raw_args(update: object) -> dict[str, object]:
    raw = getattr(update, "raw_input", None)
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    return {}


def _chunk_text(update: object) -> str:
    content = getattr(update, "content", None)
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _pick(options: list[PermissionOption], kinds: tuple[str, ...]) -> PermissionOption | None:
    for kind in kinds:
        for option in options:
            if option.kind == kind:
                return option
    return None


def _usage(value: object) -> dict[str, object] | None:
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        return None
    raw = dump(mode="json", exclude_none=True)
    if isinstance(raw, dict):
        return {str(key): item for key, item in raw.items()}
    return None


def _seconds(elapsed: float | None) -> float | None:
    if elapsed is None:
        return None
    return round(elapsed, 3)


def _absolute(path: Path) -> Path:
    return Path(os.path.realpath(path))


def _close_manager(manager: object) -> None:
    exit_cm = getattr(manager, "__exit__", None)
    if exit_cm is not None:
        exit_cm(None, None, None)
