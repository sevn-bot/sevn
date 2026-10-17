"""Codex adapter: one ``codex app-server`` process per session (D3, D5).

The process speaks JSON-RPC over stdio. A thread id is the resume ref. The
protocol can multiplex threads; this spike keeps one thread on one process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from spike_rt.events import IGNORED_NATIVE, RuntimeEvent, map_native_event
from spike_rt.mcp_server import BoundServer, echo_server
from spike_rt.transcripts import GUIDE, invoke, note_metric, scrub, write_guide, write_turn_fixture

_APPROVALS = frozenset(
    {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "mcpServer/elicitation/request",
    }
)
_DELTAS = frozenset(
    {
        "item/agentMessage/delta",
        "item/reasoning/summaryTextDelta",
        "item/reasoning/textDelta",
    }
)
_HANDSHAKE_TIMEOUT_S = 45.0
# Pinned CLI catalog model. A user config model newer than this pin fails the turn.
_CODEX_MODEL = "gpt-5.6-sol"

PermissionCallback = Callable[[RuntimeEvent], str | Awaitable[str]]
EventCallback = Callable[[RuntimeEvent], Awaitable[None] | None]


class _Closed:
    """Queue sentinel: the app-server stdout closed."""


_CLOSED = _Closed()


class CodexSession:
    """One Codex app-server process bound to a workspace and a loopback MCP server."""

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
        self._resumed = session_ref is not None
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[object, asyncio.Future[dict[str, object]]] = {}
        self._queue: asyncio.Queue[dict[str, object] | _Closed] = asyncio.Queue()
        self._write_lock = asyncio.Lock()
        self._next_id = 1
        self._closed = False
        self._finished = False
        self._turn_id: str | None = None
        self._early: list[dict[str, object]] = []
        self._stderr: list[str] = []
        self._methods: set[str] = set()
        self._on_permission: PermissionCallback | None = None
        self._on_event: EventCallback | None = None
        self._events: list[RuntimeEvent] = []
        self._natives: list[dict[str, object]] = []
        self._turn_started = 0.0
        self._first_text: float | None = None
        self.session_ref = session_ref
        self.bearer = server.bearer
        self.mcp_calls = server.calls

    async def connect(self) -> None:
        binary = shutil.which("codex")
        if binary is None:
            raise RuntimeError("codex is not on PATH")
        env = os.environ.copy()
        env["SEVN_SPIKE_MCP_BEARER"] = self.bearer
        self._proc = await asyncio.create_subprocess_exec(
            binary,
            "app-server",
            "--stdio",
            "-c",
            f'mcp_servers.sevn.url="{self._server.url}"',
            "-c",
            'mcp_servers.sevn.bearer_token_env_var="SEVN_SPIKE_MCP_BEARER"',
            "-c",
            f'model="{_CODEX_MODEL}"',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self._workspace,
            start_new_session=True,
        )
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        try:
            await self._request(
                "initialize",
                {"clientInfo": {"name": "sevn-spike", "version": "0.1.0"}},
                timeout=_HANDSHAKE_TIMEOUT_S,
            )
            await self._notify("initialized", {})
            await self._open_thread()
        except Exception as exc:
            detail = self._tail()
            raise RuntimeError(f"{exc}\n{detail}") from exc

    async def turn(
        self,
        prompt: str,
        *,
        on_permission: PermissionCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> list[RuntimeEvent]:
        if not self.session_ref:
            raise RuntimeError("codex thread is not bound")
        self._on_permission = on_permission
        self._on_event = on_event
        self._events = []
        self._natives = []
        self._methods = set()
        self._finished = False
        self._turn_id = None
        self._early = []
        self._turn_started = time.monotonic()
        self._first_text = None
        try:
            await self._push(
                {
                    "method": "thread/resume" if self._resumed else "thread/start",
                    "params": {"threadId": self.session_ref},
                }
            )
            await self._drive_turn(
                {
                    "threadId": self.session_ref,
                    "input": [{"type": "text", "text": prompt}],
                    "approvalPolicy": "untrusted",
                    "cwd": str(self._workspace),
                }
            )
        finally:
            self._on_permission = None
            self._on_event = None
            write_turn_fixture(
                "codex",
                self._natives,
                secrets=(self.bearer,),
                paths=(str(self._workspace),),
            )
            note_metric(self._metric())
        return list(self._events)

    async def interrupt(self) -> None:
        if not self.session_ref or not self._turn_id:
            return
        await self._request(
            "turn/interrupt",
            {"threadId": self.session_ref, "turnId": self._turn_id},
        )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fail_pending(RuntimeError("session closed"))
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            _terminate(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
        for task in (self._reader, self._stderr_task):
            if task is not None:
                task.cancel()
        _close_manager(self._manager)

    async def _open_thread(self) -> None:
        params: dict[str, object] = {
            "cwd": str(self._workspace),
            "approvalPolicy": "untrusted",
            "sandbox": "workspace-write",
            "developerInstructions": GUIDE,
            "ephemeral": False,
        }
        if self.session_ref:
            params["threadId"] = self.session_ref
            result = await self._request("thread/resume", params, timeout=_HANDSHAKE_TIMEOUT_S)
        else:
            result = await self._request("thread/start", params, timeout=_HANDSHAKE_TIMEOUT_S)
        thread = result.get("thread")
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError("codex did not return a thread id")
        self.session_ref = thread_id

    async def _drive_turn(self, params: dict[str, object]) -> None:
        request = asyncio.create_task(self._request("turn/start", params))
        try:
            while not self._finished:
                incoming = asyncio.create_task(self._queue.get())
                waiting: set[asyncio.Future[object] | asyncio.Task[object]] = {incoming}
                if not request.done():
                    waiting.add(request)
                done, _pending = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if request in done:
                    self._apply_turn_result(request.result())
                    await self._flush_early()
                if incoming in done:
                    await self._handle(incoming.result())
                else:
                    incoming.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await incoming
            if not request.done():
                self._apply_turn_result(await request)
                await self._flush_early()
        finally:
            if not request.done():
                request.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await request

    def _apply_turn_result(self, result: dict[str, object]) -> None:
        turn = result.get("turn")
        if isinstance(turn, dict) and isinstance(turn.get("id"), str):
            self._turn_id = turn["id"]

    async def _flush_early(self) -> None:
        pending = self._early
        self._early = []
        for message in pending:
            await self._handle(message)

    async def _handle(self, message: dict[str, object] | _Closed) -> None:
        if isinstance(message, _Closed):
            if not self._finished:
                raise RuntimeError(f"codex app-server exited\n{self._tail()}")
            return
        if _is_server_request(message) and self._turn_id is not None and not self._belongs(message):
            await self._respond(message.get("id"), _denied(message))
            return
        if not self._belongs(message):
            if self._turn_id is None and _message_turn_id(message) is not None:
                self._early.append(message)
            return
        method = message.get("method")
        if isinstance(method, str):
            self._methods.add(method)
        if _is_server_request(message):
            await self._answer(message)
            return
        native = _reduce(message)
        if native is None:
            return
        await self._push(native)
        if native.get("method") == "turn/completed":
            self._finished = True

    def _belongs(self, message: dict[str, object]) -> bool:
        turn_id = _message_turn_id(message)
        if turn_id is None:
            return True
        return self._turn_id is not None and turn_id == self._turn_id

    async def _answer(self, message: dict[str, object]) -> None:
        method = message.get("method")
        params = message.get("params")
        body = params if isinstance(params, dict) else {}
        request_id = message.get("id")
        if method in _APPROVALS and isinstance(method, str):
            event = await self._push(_permission_native(method, body))
            decision = await invoke(self._on_permission, event)
            await self._respond(request_id, _approval_body(method, body, decision == "approve"))
            return
        if method == "item/tool/requestUserInput":
            await self._respond(request_id, {"answers": _user_answers(body)})
            return
        if method == "item/tool/call":
            await self._respond(
                request_id,
                {
                    "success": False,
                    "contentItems": [{"type": "inputText", "text": "unsupported"}],
                },
            )
            return
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "unsupported server request"},
            }
        )

    async def _push(self, native: dict[str, object]) -> RuntimeEvent:
        event = map_native_event("codex", native)
        self._natives.append(native)
        self._events.append(event)
        if event.kind == "session_bound" and event.session_ref:
            self.session_ref = event.session_ref
        if event.kind == "text_delta" and event.text and self._first_text is None:
            self._first_text = time.monotonic() - self._turn_started
        await invoke(self._on_event, event)
        return event

    async def _request(
        self,
        method: str,
        params: dict[str, object],
        timeout: float | None = None,
    ) -> dict[str, object]:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("codex session is closed")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            message = await (asyncio.wait_for(future, timeout) if timeout else future)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise RuntimeError(f"codex {method} timed out") from exc
        error = message.get("error")
        if error is not None:
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(self._scrub(f"codex {method} failed: {detail}"))
        result = message.get("result")
        if isinstance(result, dict):
            return result
        return {}

    async def _notify(self, method: str, params: dict[str, object]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _respond(self, request_id: object, result: dict[str, object]) -> None:
        await self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _send(self, payload: dict[str, object]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("codex session is closed")
        raw = json.dumps(payload).encode() + b"\n"
        async with self._write_lock:
            proc.stdin.write(raw)
            await proc.stdin.drain()

    async def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                pending = self._pending.get(request_id) if request_id is not None else None
                is_response = (
                    pending is not None
                    and "method" not in message
                    and ("result" in message or "error" in message)
                )
                if is_response:
                    self._pending.pop(request_id, None)
                    if not pending.done():
                        pending.set_result(message)
                    continue
                await self._queue.put(message)
        finally:
            self._fail_pending(RuntimeError("codex app-server closed"))
            await self._queue.put(_CLOSED)

    async def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            self._stderr.append(line.decode("utf-8", errors="replace"))
            if len(self._stderr) > 50:
                del self._stderr[:-50]

    def _fail_pending(self, exc: Exception) -> None:
        for pending in self._pending.values():
            if not pending.done():
                pending.set_exception(exc)
        self._pending.clear()

    def _metric(self) -> dict[str, object]:
        tools = [event.name for event in self._events if event.kind == "tool_call_started"]
        error = next(
            (event.message for event in reversed(self._events) if event.kind == "error"),
            None,
        )
        terminal = self._events[-1].kind if self._events else None
        return {
            "runtime": "codex",
            "first_text_s": _seconds(self._first_text),
            "methods": sorted(self._methods),
            "kinds": [event.kind for event in self._events],
            "tools": tools,
            "error": error,
            "stderr": self._tail()[-800:],
            "terminal": terminal,
        }

    def _tail(self) -> str:
        return self._scrub("".join(self._stderr[-20:]))

    def _scrub(self, text: str) -> str:
        return scrub(text, secrets=(self.bearer,), paths=(str(self._workspace),))


async def open_codex_session(workspace: Path, session_ref: str | None) -> CodexSession:
    """Start a Codex thread in ``workspace``, optionally resuming ``session_ref``."""

    write_guide(workspace)
    manager = echo_server(session_ref or uuid.uuid4().hex)
    server = manager.__enter__()
    session = CodexSession(_absolute(workspace), server, manager, session_ref)
    try:
        await session.connect()
    except BaseException:
        await session.aclose()
        raise
    return session


def _seconds(elapsed: float | None) -> float | None:
    if elapsed is None:
        return None
    return round(elapsed, 3)


def _absolute(path: Path) -> Path:
    return Path(os.path.realpath(path))


def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.pid is None:
        proc.terminate()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _close_manager(manager: object) -> None:
    exit_cm = getattr(manager, "__exit__", None)
    if exit_cm is not None:
        exit_cm(None, None, None)


def _is_server_request(message: dict[str, object]) -> bool:
    return isinstance(message.get("method"), str) and "id" in message and "result" not in message


def _message_turn_id(message: dict[str, object]) -> str | None:
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    turn_id = params.get("turnId")
    if isinstance(turn_id, str) and turn_id:
        return turn_id
    turn = params.get("turn")
    if isinstance(turn, dict):
        nested = turn.get("id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _reduce(message: dict[str, object]) -> dict[str, object] | None:
    method = message.get("method")
    if not isinstance(method, str) or method.startswith(("account/", "remoteControl/")):
        return None
    params = message.get("params")
    body = params if isinstance(params, dict) else {}
    if method in {"thread/start", "thread/resume", "thread/started"}:
        thread_id = _thread_id(body)
        return {"method": method, "params": {"threadId": thread_id} if thread_id else {}}
    if method in _DELTAS:
        delta = body.get("delta")
        if not isinstance(delta, str) or not delta:
            return None
        return {"method": method, "params": {"delta": delta}}
    if method in {"item/started", "item/completed"}:
        item = _reduce_item(body.get("item"))
        return {"method": method, "params": {"item": item} if item else {}}
    if method == "turn/completed":
        return {"method": method, "params": {"turn": _reduce_turn(body.get("turn"))}}
    if method in IGNORED_NATIVE["codex"]:
        return {"method": method, "params": {}}
    return {"method": method, "params": {}}


def _thread_id(params: dict[str, object]) -> str:
    thread_id = params.get("threadId")
    if isinstance(thread_id, str):
        return thread_id
    thread = params.get("thread")
    if isinstance(thread, dict) and isinstance(thread.get("id"), str):
        return thread["id"]
    return ""


def _reduce_item(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
        return None
    reduced: dict[str, object] = {"type": item["type"]}
    for key in ("id", "tool", "status"):
        if isinstance(item.get(key), str):
            reduced[key] = item[key]
    command = item.get("command")
    if isinstance(command, str):
        reduced["command"] = command[:500]
    arguments = item.get("arguments")
    if isinstance(arguments, dict):
        reduced["arguments"] = arguments
    return reduced


def _reduce_turn(turn: object) -> dict[str, object]:
    if not isinstance(turn, dict):
        return {}
    reduced: dict[str, object] = {}
    if isinstance(turn.get("id"), str):
        reduced["id"] = turn["id"]
    if isinstance(turn.get("status"), str):
        reduced["status"] = turn["status"]
    error = turn.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        reduced["error"] = {"message": error["message"][:500]}
    return reduced


def _permission_native(method: str, params: dict[str, object]) -> dict[str, object]:
    request_id = params.get("itemId") or params.get("approvalId") or method
    if not isinstance(request_id, str) or not request_id:
        request_id = method
    tool = "permissions"
    arguments: dict[str, object] = {}
    if method == "item/commandExecution/requestApproval":
        tool = "shell"
        command = params.get("command")
        if isinstance(command, str):
            arguments = {"command": command[:500]}
    elif method == "item/fileChange/requestApproval":
        tool = "apply_patch"
    else:
        if "sevn_echo" in json.dumps(params, default=str):
            tool = "sevn_echo"
        elif method == "mcpServer/elicitation/request":
            tool = "mcp"
        permissions = params.get("permissions")
        if isinstance(permissions, dict):
            arguments = {str(key): value for key, value in permissions.items()}
    return {
        "method": method,
        "params": {"itemId": request_id, "tool": tool, "arguments": arguments},
    }


def _approval_body(method: str, params: dict[str, object], approve: bool) -> dict[str, object]:
    if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
        return {"decision": _choice(params, approve)}
    if method == "item/permissions/requestApproval":
        permissions = params.get("permissions")
        granted = permissions if approve and isinstance(permissions, dict) else {}
        return {"permissions": granted, "scope": "turn"}
    if method == "mcpServer/elicitation/request":
        return {"action": "accept" if approve else "decline"}
    return {"decision": "accept" if approve else "decline"}


def _choice(params: dict[str, object], approve: bool) -> str:
    available = params.get("availableDecisions")
    options = set()
    if isinstance(available, list):
        options = {item for item in available if isinstance(item, str)}
    if approve:
        if not options or "accept" in options:
            return "accept"
        if "acceptForSession" in options:
            return "acceptForSession"
        return "accept"
    if not options or "decline" in options:
        return "decline"
    if "cancel" in options:
        return "cancel"
    return "decline"


def _denied(message: dict[str, object]) -> dict[str, object]:
    method = message.get("method")
    params = message.get("params")
    body = params if isinstance(params, dict) else {}
    if isinstance(method, str):
        return _approval_body(method, body, False)
    return {"decision": "decline"}


def _user_answers(params: dict[str, object]) -> dict[str, object]:
    questions = params.get("questions")
    answers: dict[str, object] = {}
    if not isinstance(questions, list):
        return answers
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = question.get("id") or question.get("questionId")
        if isinstance(question_id, str) and question_id:
            answers[question_id] = {"answers": ["ok"]}
    return answers
