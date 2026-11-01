"""Shell tool. Workspace runs are confined; full runs wait on approval.risk (D12, D15)."""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.domain.workspace import open_place, scratch_dir
from sevn.sandbox.env import child_env
from sevn.sandbox.policy import (
    allow_all_enabled,
    approval_required,
    direct_argv,
    isolated_command,
    workspace_argv,
)
from sevn.sandbox.risk import Risk, risk_of
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import PendingRequest
from sevn.store.models import Turn as TurnRow
from sevn.tools.registry import TurnDeps, register_toolset

# One command may run this long. Past it the whole process group is stopped.
TIMEOUT_SECONDS = 300.0
# Bytes kept per stream. The rest is read and dropped so the command never
# blocks on a full pipe.
OUTPUT_LIMIT = 64_000
_CHUNK = 65_536
_TERM_GRACE = 2.0
_POLL = 0.05


@dataclass(frozen=True, slots=True)
class ShellResult:
    """One shell attempt. ``pending_id`` is set when the command is waiting."""

    executed: bool
    risk: Risk
    pending_id: str | None
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class _Target:
    access: str
    approval_policy: str
    network_on: bool
    root: Path


async def execute(
    bot_id: str,
    agent_id: str,
    command: str,
    *,
    approved: bool = False,
) -> ShellResult:
    """Run ``command`` for one agent, or record an approval and do not run it.

    ``approved`` is set when the runtime resumed this tool call after the user
    approved it. Without it the tool would ask again on resume and never run.
    """
    target = await _load(bot_id, agent_id)
    risk = risk_of(command)
    host_allow_all = await asyncio.to_thread(allow_all_enabled)
    if not approved and approval_required(
        access=target.access,
        policy=target.approval_policy,
        risk=risk,
        host_allow_all=host_allow_all,
    ):
        pending_id = await _ask(agent_id, command, risk)
        return ShellResult(
            executed=False,
            risk=risk,
            pending_id=pending_id,
            returncode=None,
            stdout="",
            stderr="",
        )
    argv = await asyncio.to_thread(
        _argv,
        command,
        target,
        host_allow_all=host_allow_all,
    )
    env = child_env(docker=target.access == "isolated" and not host_allow_all)
    if target.access == "workspace" and not host_allow_all:
        tmp = await _scratch_tmp(target.root.resolve(), agent_id)
        for name in ("TMPDIR", "TMP", "TEMP"):
            env[name] = str(tmp)
    ran = await _run(argv, target.root.resolve(), env)
    return ShellResult(
        executed=True,
        risk=risk,
        pending_id=None,
        returncode=ran.returncode,
        stdout=ran.stdout,
        stderr=ran.stderr,
        timed_out=ran.timed_out,
        truncated=ran.truncated,
    )


def tool_output(result: ShellResult) -> str:
    """What the model reads: the exit code, stdout, then stderr when there is any."""
    lines = [f"exit code: {result.returncode}"]
    if result.timed_out:
        lines.append(f"timed out after {TIMEOUT_SECONDS:g}s; the command was stopped")
    if result.truncated:
        lines.append(f"output was cut at {OUTPUT_LIMIT} bytes per stream")
    if result.stdout:
        lines.extend(["stdout:", result.stdout.rstrip("\n")])
    if result.stderr:
        lines.extend(["stderr:", result.stderr.rstrip("\n")])
    return "\n".join(lines)


def shell_toolset(deps: TurnDeps) -> dict[str, object]:
    """The deferred shell tool for one turn."""

    async def shell(command: str) -> str:
        """Run a shell command under this bot's access level."""
        result = await execute(
            deps.bot_id,
            deps.agent_id,
            command,
            approved=deps.approved,
        )
        if result.pending_id is not None:
            return result.pending_id
        return tool_output(result)

    return {"shell": shell}


register_toolset("shell", shell_toolset, set(), deferred={"shell"})


async def _load(bot_id: str, agent_id: str) -> _Target:
    place = await open_place(agent_id)
    if place.bot_id != bot_id:
        raise DomainError("not_found", "agent not found")
    async with open_session() as session:
        row = await session.get(BotRow, bot_id)
        if row is None:
            raise DomainError("not_found", "bot not found")
        return _Target(
            access=row.access,
            approval_policy=row.approval_policy,
            network_on=row.network == "on",
            root=place.root,
        )


async def _scratch_tmp(root: Path, agent_id: str) -> Path:
    """A writable temp folder for the confined shell.

    The host ``TMPDIR`` is read-only under Seatbelt and hidden by the ``/tmp``
    tmpfs under bubblewrap. The agent's scratch folder is writable on both.
    """
    tmp = scratch_dir(root, agent_id) / ".tmp"
    await asyncio.to_thread(tmp.mkdir, parents=True, exist_ok=True)
    return tmp


def _argv(command: str, target: _Target, *, host_allow_all: bool) -> list[str]:
    if host_allow_all or target.access == "full":
        return direct_argv(command)
    if target.access == "isolated":
        return isolated_command(command, root=target.root, network=target.network_on)
    return workspace_argv(command, root=target.root, network=target.network_on)


async def _ask(agent_id: str, command: str, risk: Risk) -> str:
    pending_id = new_id("pend_")
    now = utcnow()
    async with open_session() as session:
        agent = await session.get(AgentRow, agent_id)
        if agent is None:
            raise DomainError("not_found", "agent not found")
        turn_id = new_id("turn_")
        session.add(
            TurnRow(
                id=turn_id,
                agent_id=agent_id,
                thread_id=agent.thread_id,
                job_ids=[],
                status="waiting",
                model="",
                usage={},
                model_messages=None,
                started_at=now,
                finished_at=None,
            )
        )
        await session.flush()
        session.add(
            PendingRequest(
                id=pending_id,
                turn_id=turn_id,
                agent_id=agent_id,
                kind="approval",
                tool_call_id=None,
                payload={"name": "shell", "args": {"command": command}, "risk": risk},
                answer=None,
                status="waiting",
                created_at=now,
                resolved_at=None,
            )
        )
        await session.commit()
    return pending_id


@dataclass(frozen=True, slots=True)
class _Ran:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


async def _run(argv: list[str], cwd: Path, env: dict[str, str]) -> _Ran:
    """Run ``argv`` in its own session so a timeout or cancel stops every child."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    collected = asyncio.gather(
        _read_capped(process.stdout),
        _read_capped(process.stderr),
        process.wait(),
    )
    timed_out = False
    try:
        (out, out_cut), (err, err_cut), _code = await asyncio.wait_for(
            collected, timeout=TIMEOUT_SECONDS
        )
    except TimeoutError:
        timed_out = True
        await _stop(process)
        out, out_cut, err, err_cut = b"", False, b"", False
    except asyncio.CancelledError:
        await asyncio.shield(_stop(process))
        raise
    code = 1 if process.returncode is None else process.returncode
    return _Ran(
        returncode=code,
        stdout=_text(out),
        stderr=_text(err),
        timed_out=timed_out,
        truncated=out_cut or err_cut,
    )


async def _read_capped(stream: asyncio.StreamReader | None) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    kept = bytearray()
    cut = False
    while chunk := await stream.read(_CHUNK):
        room = OUTPUT_LIMIT - len(kept)
        if room > 0:
            kept.extend(chunk[:room])
        if len(chunk) > room:
            cut = True
    return bytes(kept), cut


async def _stop(process: asyncio.subprocess.Process) -> None:
    """SIGTERM the process group, then SIGKILL what is left after a short grace.

    The group is the unit, not the leader: a background child keeps working
    after its shell exits, and a child that ignores SIGTERM outlives a leader
    that does not. ``start_new_session`` makes the leader's pid the group id.
    """
    group = process.pid
    _signal_group(group, signal.SIGTERM)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TERM_GRACE
    # No event exists for "the group is empty": poll it.
    while _group_alive(group) and loop.time() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(_POLL)
    if _group_alive(group):
        _signal_group(group, signal.SIGKILL)
    if process.returncode is None:
        await process.wait()


def _signal_group(pid: int, sig: signal.Signals) -> None:
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _group_alive(pid: int) -> bool:
    """True while any member of the group exists. A group we may not signal is gone to us."""
    try:
        os.killpg(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _text(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")
