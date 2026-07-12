"""Persistent terminal session tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 8).

Uses ``pexpect`` for interactive shells in-process. When ``ToolContext.sandbox_client`` is
wired, ``terminal_run`` may delegate one-shot commands to ``sandbox_exec`` instead.

Module: sevn.tools.terminal
Depends: asyncio, os, uuid, sevn.tools.base, sevn.tools.context, sevn.tools.decorator,
    sevn.tools.paths

Exports:
    TerminalSession — one pexpect-backed shell bound to a gateway session.
    terminal_spawn_tool — open a persistent shell session.
    terminal_run_tool — run one command in a session (or via sandbox when configured).
    terminal_close_tool — tear down a session.
    register_terminal_tools — register terminal tools on a ``ToolExecutor``.
    reset_terminal_store_for_tests — clear in-memory sessions (tests only).

Examples:
    >>> from sevn.tools.terminal import reset_terminal_store_for_tests
    >>> reset_terminal_store_for_tests()
    >>> True
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from sevn.runtime.operator_path import augment_operator_path
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.tools.paths import resolve_workspace_relative_path

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

DEFAULT_SHELL: Final[str] = "/bin/sh"
DEFAULT_TERMINAL_TIMEOUT_S: Final[float] = 30.0
MAX_TERMINAL_TIMEOUT_S: Final[float] = 300.0
_PROBE_MARKER: Final[str] = "__sevn_terminal_probe__"
DEFAULT_SESSION_TERMINAL_ID: Final[str] = "__session_default__"

_TERMINAL_TOOLS: tuple[Any, ...] = ()
_sessions_by_gateway: dict[str, dict[str, TerminalSession]] = {}


@dataclass
class TerminalSession:
    """One pexpect-backed shell bound to a gateway session."""

    terminal_id: str
    shell: str
    cwd: Path
    child: Any


def reset_terminal_store_for_tests() -> None:
    """Close and drop all terminal sessions (unit tests only).

    Returns:
        None

    Examples:
        >>> reset_terminal_store_for_tests()
        >>> True
        True
    """
    for sessions in _sessions_by_gateway.values():
        for session in list(sessions.values()):
            _close_sync(session)
        sessions.clear()
    _sessions_by_gateway.clear()


def _session_map(session_id: str) -> dict[str, TerminalSession]:
    """Return the terminal table for ``session_id``.

    Args:
        session_id (str): Gateway session identifier.

    Returns:
        dict[str, TerminalSession]: Terminal id to session mapping.

    Examples:
        >>> reset_terminal_store_for_tests()
        >>> isinstance(_session_map("s"), dict)
        True
    """
    return _sessions_by_gateway.setdefault(session_id, {})


async def _ensure_session_terminal(
    ctx: ToolContext,
    *,
    terminal_id: str | None,
) -> tuple[str, TerminalSession] | str:
    """Resolve ``terminal_id`` or auto-create the per-session default terminal.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        terminal_id (str | None): Explicit session id from ``terminal_spawn``.

    Returns:
        tuple[str, TerminalSession] | str: Resolved id + session, or a §3.1 failure
            envelope string when an explicit id is unknown.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_ensure_session_terminal)
        True
    """
    sessions = _session_map(ctx.session_id)
    if terminal_id:
        session = sessions.get(terminal_id)
        if session is None:
            return enveloped_failure(
                f"unknown terminal_id: {terminal_id}",
                code=ToolResultCode.VALIDATION_ERROR,
                data={"terminal_id": terminal_id},
            )
        return terminal_id, session

    existing = sessions.get(DEFAULT_SESSION_TERMINAL_ID)
    if existing is not None:
        return DEFAULT_SESSION_TERMINAL_ID, existing

    work_cwd = ctx.workspace_path
    shell_path = _resolve_shell(None)
    try:
        child = await asyncio.to_thread(  # nosec B604 — shell binary path, not shell=True
            _spawn_sync,
            shell=shell_path,
            cwd=work_cwd,
        )
    except Exception as exc:
        return enveloped_failure(
            f"terminal_spawn failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
            data={"shell": shell_path},
        )

    ok, reason = await asyncio.to_thread(_probe_spawn_health, child)
    if not ok:
        await asyncio.to_thread(
            _close_sync,
            TerminalSession(
                terminal_id="",
                shell=shell_path,
                cwd=work_cwd,
                child=child,  # nosec B604
            ),
        )
        return enveloped_failure(
            reason,
            code=ToolResultCode.INTERNAL_ERROR,
            data={"shell": shell_path, "readiness": "backend_unwired"},
        )

    session = TerminalSession(
        terminal_id=DEFAULT_SESSION_TERMINAL_ID,
        shell=shell_path,  # nosec B604 — stored shell path label, not subprocess shell=
        cwd=work_cwd,
        child=child,
    )
    sessions[DEFAULT_SESSION_TERMINAL_ID] = session
    return DEFAULT_SESSION_TERMINAL_ID, session


def _resolve_shell(shell: str | None) -> str:
    """Pick an executable shell path.

    Args:
        shell (str | None): Requested shell or ``None`` for default.

    Returns:
        str: Absolute or PATH-resolvable shell binary.

    Examples:
        >>> _resolve_shell(None) in {DEFAULT_SHELL, "/bin/bash", "/bin/zsh"}
        True
    """
    if shell and shell.strip():
        return shell.strip()
    return DEFAULT_SHELL


def _spawn_sync(*, shell: str, cwd: Path) -> Any:
    """Blocking pexpect spawn helper (runs in a worker thread).

    Args:
        shell (str): Shell executable.
        cwd (Path): Working directory for the child.

    Returns:
        Any: ``pexpect.spawn`` instance.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_spawn_sync)
        True
    """
    import pexpect

    env = augment_operator_path()
    child = pexpect.spawn(
        shell,
        encoding="utf-8",
        cwd=str(cwd),
        env=env,
        timeout=int(DEFAULT_TERMINAL_TIMEOUT_S),
    )
    with contextlib.suppress(pexpect.exceptions.TIMEOUT, pexpect.exceptions.EOF):
        child.expect([r"[$#>]", pexpect.EOF], timeout=5)
    return child


def _probe_spawn_health(child: Any, *, timeout_s: float = 5.0) -> tuple[bool, str]:
    """Verify the pexpect shell responds to a trivial echo command.

    Args:
        child (Any): ``pexpect.spawn`` instance.
        timeout_s (float): Probe timeout in seconds.

    Returns:
        tuple[bool, str]: ``(True, "")`` when healthy; ``(False, reason)`` otherwise.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_probe_spawn_health)
        True
    """
    import pexpect

    child.sendline(f"echo {_PROBE_MARKER}")
    try:
        child.expect(_PROBE_MARKER, timeout=timeout_s)
        child.expect([r"[$#>]", pexpect.EOF], timeout=timeout_s)
    except (pexpect.exceptions.TIMEOUT, pexpect.exceptions.EOF) as exc:
        return False, f"terminal backend unwired or unresponsive ({exc})"
    return True, ""


def _run_sync(*, child: Any, command: str, timeout_s: float) -> tuple[str, bool]:
    """Send ``command`` to ``child`` and return captured output before the prompt.

    Polls with short expect intervals so partial output is preserved on timeout.

    Args:
        child (Any): ``pexpect.spawn`` instance.
        command (str): Command line to execute.
        timeout_s (float): Expect timeout in seconds.

    Returns:
        tuple[str, bool]: Combined output and whether the expect deadline was hit.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_run_sync)
        True
    """
    import pexpect

    child.sendline(command)
    chunks: list[str] = []
    deadline = time.monotonic() + timeout_s
    timed_out = False

    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        try:
            child.expect([r"[$#>]", pexpect.EOF], timeout=min(0.5, remaining))
            chunk = str(getattr(child, "before", "") or "")
            if chunk:
                chunks.append(chunk)
            break
        except pexpect.exceptions.TIMEOUT:
            chunk = str(getattr(child, "before", "") or "")
            if chunk:
                chunks.append(chunk)
            continue
    else:
        timed_out = True
        chunk = str(getattr(child, "before", "") or "")
        if chunk:
            chunks.append(chunk)

    output = "".join(chunks).strip()
    return output, timed_out


def _close_sync(session: TerminalSession) -> None:
    """Close a pexpect child if still open.

    Args:
        session (TerminalSession): Session to tear down.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_close_sync)
        True
    """
    child = session.child
    if child is None:
        return
    with contextlib.suppress(Exception):
        if child.isalive():
            child.sendline("exit")
            child.close(force=True)
        else:
            child.close(force=True)


async def _sandbox_run_command(ctx: ToolContext, *, command: str) -> str | None:
    """Run ``command`` via ``ctx.sandbox_client`` when configured.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        command (str): Shell command to execute.

    Returns:
        str | None: §3.1 JSON envelope when sandbox routing succeeds; else ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_sandbox_run_command)
        True
    """
    client = ctx.sandbox_client
    if client is None:
        return None
    try:
        payload = await client.sandbox_exec(language="bash", code=command, ctx=ctx)
    except Exception as exc:
        return enveloped_failure(
            f"terminal_run sandbox_exec failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
            data={"command": command},
        )
    return enveloped_success(
        {
            "routed_via": "sandbox_exec",
            "command": command,
            "exit_code": payload.get("exit_code"),
            "stdout": payload.get("stdout", ""),
            "stderr": payload.get("stderr", ""),
        },
    )


@sevn_tool(
    name="terminal_spawn",
    category="process",
    description="Open a persistent interactive shell session (pexpect).",
    parameters={
        "type": "object",
        "properties": {
            "shell": {
                "type": "string",
                "description": "Optional shell executable (default /bin/sh).",
            },
            "cwd": {
                "type": "string",
                "description": "Workspace-relative working directory.",
            },
        },
    },
    abortable=False,
    sandbox_mode="subprocess",
)
async def terminal_spawn_tool(
    ctx: ToolContext,
    *,
    shell: str | None = None,
    cwd: str | None = None,
) -> str:
    """Spawn a persistent terminal session for the active gateway session.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        shell (str | None): Optional shell executable path.
        cwd (str | None): Optional workspace-relative working directory.

    Returns:
        str: §3.1 JSON envelope string with ``terminal_id``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(terminal_spawn_tool)
        True
    """
    work_cwd = ctx.workspace_path
    if cwd:
        try:
            work_cwd = resolve_workspace_relative_path(ctx.workspace_path, cwd)
        except ValueError as exc:
            return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)

    shell_path = _resolve_shell(shell)
    try:
        child = await asyncio.to_thread(_spawn_sync, shell=shell_path, cwd=work_cwd)  # nosec B604 — shell binary path, not shell=True
    except Exception as exc:
        return enveloped_failure(
            f"terminal_spawn failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
            data={"shell": shell_path},
        )

    ok, reason = await asyncio.to_thread(_probe_spawn_health, child)
    if not ok:
        await asyncio.to_thread(
            _close_sync,
            TerminalSession(
                terminal_id="",
                shell=shell_path,
                cwd=work_cwd,
                child=child,  # nosec B604
            ),
        )
        return enveloped_failure(
            reason,
            code=ToolResultCode.INTERNAL_ERROR,
            data={"shell": shell_path, "readiness": "backend_unwired"},
        )

    terminal_id = uuid.uuid4().hex[:12]
    _session_map(ctx.session_id)[terminal_id] = TerminalSession(
        terminal_id=terminal_id,
        shell=shell_path,  # nosec B604 — stored shell path label, not subprocess shell=
        cwd=work_cwd,
        child=child,
    )
    return enveloped_success(
        {
            "terminal_id": terminal_id,
            "shell": shell_path,
            "cwd": str(work_cwd),
        },
    )


@sevn_tool(
    name="terminal_run",
    category="process",
    description=(
        "Run a command in a terminal session or via sandbox_exec when wired. "
        "Use process (not terminal_run) for pip install and other long non-interactive commands."
    ),
    parameters={
        "type": "object",
        "properties": {
            "terminal_id": {
                "type": "string",
                "description": "Session id from terminal_spawn (ignored when sandbox routed).",
            },
            "command": {"type": "string", "description": "Shell command to execute."},
            "timeout_s": {
                "type": "number",
                "description": f"Expect timeout in seconds (default {DEFAULT_TERMINAL_TIMEOUT_S:.0f}, max {MAX_TERMINAL_TIMEOUT_S:.0f}).",
            },
            "prefer_sandbox": {
                "type": "boolean",
                "description": "When true and sandbox_client is wired, route via sandbox_exec.",
            },
        },
        "required": ["command"],
    },
    abortable=False,
)
async def terminal_run_tool(
    ctx: ToolContext,
    *,
    terminal_id: str | None = None,
    command: str,
    timeout_s: float | None = None,
    prefer_sandbox: bool = True,
) -> str:
    """Execute ``command`` in a spawned terminal or sandbox when configured.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        terminal_id (str | None): Existing session from ``terminal_spawn``.
        command (str): Shell command line.
        timeout_s (float | None): Optional expect timeout.
        prefer_sandbox (bool): Route through ``sandbox_exec`` when client is wired.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(terminal_run_tool)
        True
    """
    body = command.strip()
    if not body:
        return enveloped_failure(
            'command must be non-empty. Usage: terminal_run(command="<shell command>") — '
            "spawn a session first with terminal_spawn if you need an interactive shell.",
            code=ToolResultCode.VALIDATION_ERROR,
        )

    if prefer_sandbox and ctx.sandbox_client is not None:
        routed = await _sandbox_run_command(ctx, command=body)
        if routed is not None:
            return routed

    resolved = await _ensure_session_terminal(ctx, terminal_id=terminal_id)
    if isinstance(resolved, str):
        return resolved
    terminal_id, session = resolved

    wall = (
        DEFAULT_TERMINAL_TIMEOUT_S
        if timeout_s is None
        else min(max(1.0, timeout_s), MAX_TERMINAL_TIMEOUT_S)
    )
    try:
        output, timed_out = await asyncio.to_thread(
            _run_sync,
            child=session.child,
            command=body,
            timeout_s=wall,
        )
    except Exception as exc:
        return enveloped_failure(
            f"terminal_run failed: {exc}",
            code=ToolResultCode.INTERNAL_ERROR,
            data={"terminal_id": terminal_id, "command": body},
        )
    payload: dict[str, object] = {
        "terminal_id": terminal_id,
        "command": body,
        "output": output,
    }
    if timed_out:
        payload["timed_out"] = True
        payload["partial"] = True
    return enveloped_success(payload)


@sevn_tool(
    name="terminal_close",
    category="process",
    description="Close a persistent terminal session opened with terminal_spawn.",
    parameters={
        "type": "object",
        "properties": {
            "terminal_id": {"type": "string", "description": "Session id from terminal_spawn."},
        },
        "required": ["terminal_id"],
    },
    abortable=False,
)
async def terminal_close_tool(ctx: ToolContext, *, terminal_id: str) -> str:
    """Tear down one terminal session.

    Args:
        ctx (ToolContext): Active tool runtime frame.
        terminal_id (str): Session id from ``terminal_spawn``.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(terminal_close_tool)
        True
    """
    sessions = _session_map(ctx.session_id)
    session = sessions.pop(terminal_id, None)
    if session is None:
        return enveloped_failure(
            f"unknown terminal_id: {terminal_id}",
            code=ToolResultCode.VALIDATION_ERROR,
            data={"terminal_id": terminal_id},
        )
    await asyncio.to_thread(_close_sync, session)
    return enveloped_success({"terminal_id": terminal_id, "closed": True})


_TERMINAL_TOOLS = (
    terminal_spawn_tool,
    terminal_run_tool,
    terminal_close_tool,
)


def register_terminal_tools(executor: ToolExecutor) -> None:
    """Register Wave 8 terminal session tools.

    Args:
        executor (ToolExecutor): Registry under construction.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.terminal import register_terminal_tools
        >>> exe = ToolExecutor()
        >>> register_terminal_tools(exe)
        >>> {"terminal_spawn", "terminal_run", "terminal_close"} <= {d.name for d in exe.definitions()}
        True
    """
    for tool_fn in _TERMINAL_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "register_terminal_tools",
    "reset_terminal_store_for_tests",
    "terminal_close_tool",
    "terminal_run_tool",
    "terminal_spawn_tool",
]
