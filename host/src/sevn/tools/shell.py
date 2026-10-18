"""Shell tool. Workspace runs are confined; full runs wait on approval.risk (D12, D15)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.domain.workspace import open_place
from sevn.sandbox.policy import (
    Risk,
    allow_all_enabled,
    approval_required,
    direct_argv,
    isolated_command,
    risk_of,
    workspace_argv,
)
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import Bot as BotRow
from sevn.store.models import PendingRequest
from sevn.store.models import Turn as TurnRow
from sevn.tools.registry import TurnDeps, register_toolset


@dataclass(frozen=True, slots=True)
class ShellResult:
    """One shell attempt. ``pending_id`` is set when the command is waiting."""

    executed: bool
    risk: Risk
    pending_id: str | None
    returncode: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class _Target:
    access: str
    approval_policy: str
    network_on: bool
    root: Path


async def execute(bot_id: str, agent_id: str, command: str) -> ShellResult:
    """Run ``command`` for one agent, or record an approval and do not run it."""
    target = await _load(bot_id, agent_id)
    risk = risk_of(command)
    host_allow_all = await asyncio.to_thread(allow_all_enabled)
    if approval_required(
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
    code, stdout, stderr = await _run(argv, target.root.resolve())
    return ShellResult(
        executed=True,
        risk=risk,
        pending_id=None,
        returncode=code,
        stdout=stdout,
        stderr=stderr,
    )


def shell_toolset(deps: TurnDeps) -> dict[str, object]:
    """The deferred shell tool for one turn."""

    async def shell(command: str) -> str:
        """Run a shell command under this bot's access level."""
        result = await execute(deps.bot_id, deps.agent_id, command)
        if result.pending_id is not None:
            return result.pending_id
        return result.stdout

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


async def _run(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    code = 1 if process.returncode is None else process.returncode
    return code, _text(stdout), _text(stderr)


def _text(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")
