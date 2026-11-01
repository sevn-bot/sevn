"""Scratch directories, shared-path locks, and git worktrees (D20)."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.sandbox.env import child_env
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import AgentLock, Message
from sevn.store.models import Bot as BotRow
from sevn.store.models import Turn as TurnRow

_LOCK_TTL = timedelta(minutes=10)
_IGNORED = "worktree ignored: workspace is not a git repo"


@dataclass(frozen=True, slots=True)
class WorkspacePlace:
    """The root file tools use for one agent."""

    bot_id: str
    agent_id: str
    root: Path


def scratch_dir(root: Path, agent_id: str) -> Path:
    """The agent's own folder under ``root``."""
    _check_id(agent_id)
    return root / "tasks" / agent_id


async def make_scratch(workspace: Path, agent_id: str) -> Path:
    """Create ``tasks/<agent_id>/`` and keep it across archive."""
    path = scratch_dir(workspace, agent_id)
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
    return path


async def ensure(agent_id: str) -> str:
    """Prepare scratch space. A worktree note is empty when the checkout is ready."""
    _bot_id, isolation, workspace = await _load(agent_id)
    await make_scratch(workspace, agent_id)
    if isolation != "worktree":
        return ""
    if not await asyncio.to_thread(_is_git, workspace):
        return _IGNORED
    worktree = _worktree_path(workspace, agent_id)
    if await asyncio.to_thread(_is_worktree, worktree):
        await make_scratch(worktree, agent_id)
        return ""
    await _add_worktree(workspace, worktree, agent_id)
    await make_scratch(worktree, agent_id)
    return ""


async def open_place(agent_id: str) -> WorkspacePlace:
    """Root for file tools: the worktree when isolation is active, else the workspace."""
    note = await ensure(agent_id)
    bot_id, isolation, workspace = await _load(agent_id)
    root = workspace
    if isolation == "worktree" and note == "":
        root = _worktree_path(workspace, agent_id)
    return WorkspacePlace(bot_id=bot_id, agent_id=agent_id, root=root)


async def release_turn(agent_id: str) -> None:
    """Drop this agent's path locks. Called when its turn ends."""
    async with open_session() as session:
        await drop_locks(session, agent_id)
        await session.commit()


async def drop_locks(session: AsyncSession, agent_id: str) -> None:
    """Delete lock rows for ``agent_id`` in the caller's transaction."""
    await session.execute(delete(AgentLock).where(AgentLock.agent_id == agent_id))


async def acquire_write(agent_id: str, path: str) -> None:
    """Hold ``path`` for ten minutes, or refresh it. Another holder raises ``path_locked``."""
    now = utcnow()
    conflict: tuple[str, str] | None = None
    async with open_session() as session:
        row = await session.get(AgentLock, path)
        if row is not None and row.agent_id != agent_id and _alive(row.expires_at, now):
            holder = await session.get(AgentRow, row.agent_id)
            title = "" if holder is None else holder.title
            conflict = (row.agent_id, title)
        else:
            expires = now + _LOCK_TTL
            if row is None:
                session.add(
                    AgentLock(
                        path=path,
                        agent_id=agent_id,
                        acquired_at=now,
                        expires_at=expires,
                    )
                )
            else:
                if row.agent_id != agent_id or not _alive(row.expires_at, now):
                    row.agent_id = agent_id
                    row.acquired_at = now
                row.expires_at = expires
            await session.commit()
    if conflict is None:
        return
    holder_id, holder_title = conflict
    await _store_lock_notice(agent_id, holder_id, holder_title)
    raise DomainError(
        "path_locked",
        "path is locked",
        {"holder_agent_id": holder_id, "holder_title": holder_title},
    )


async def _store_lock_notice(agent_id: str, holder_id: str, holder_title: str) -> None:
    """Persist the lock refusal so the chat can show who holds the path."""
    now = utcnow()
    async with open_session() as session:
        agent = await session.get(AgentRow, agent_id)
        if agent is None:
            return
        turn_id = new_id("turn_")
        session.add(
            TurnRow(
                id=turn_id,
                agent_id=agent_id,
                thread_id=agent.thread_id,
                job_ids=[],
                status="done",
                model="",
                usage={},
                model_messages=None,
                started_at=now,
                finished_at=now,
            )
        )
        await session.flush()
        session.add(
            Message(
                id=new_id("msg_"),
                thread_id=agent.thread_id,
                turn_id=turn_id,
                agent_id=agent_id,
                role="assistant",
                author="system",
                parts=[
                    {
                        "type": "error",
                        "code": "path_locked",
                        "holder_title": holder_title,
                        "holder_agent_id": holder_id,
                    }
                ],
                created_at=now,
            )
        )
        await session.commit()


def _check_id(agent_id: str) -> None:
    if agent_id == "" or agent_id in {".", ".."} or "/" in agent_id or "\\" in agent_id:
        raise DomainError("invalid_params", "invalid agent id")


def _worktree_path(workspace: Path, agent_id: str) -> Path:
    _check_id(agent_id)
    return workspace / ".sevn" / "worktrees" / agent_id


def _is_git(workspace: Path) -> bool:
    return (workspace / ".git").exists()


def _is_worktree(path: Path) -> bool:
    return (path / ".git").exists()


async def _add_worktree(workspace: Path, worktree: Path, agent_id: str) -> None:
    await asyncio.to_thread(worktree.parent.mkdir, parents=True, exist_ok=True)
    code = await _git(
        workspace,
        "worktree",
        "add",
        "-b",
        f"sevn/{agent_id}",
        str(worktree),
    )
    if code != 0:
        logger.warning("git worktree add failed")
        raise DomainError("invalid_params", "git worktree add failed")


async def _git(cwd: Path, *args: str) -> int:
    git = await asyncio.to_thread(shutil.which, "git")
    if git is None or not Path(git).is_absolute():
        raise DomainError("invalid_params", "git is not available")
    env = child_env()
    env["GIT_TERMINAL_PROMPT"] = "0"
    # The bot can write the workspace's .git, so its hooks, fsmonitor, checkout
    # filters and submodule recursion would run here on the host, outside the
    # sandbox. Filters are blanked through GIT_CONFIG_* rather than ``-c``:
    # a driver name may contain ``=``, which ``-c`` cannot express.
    overrides = [
        ("core.hooksPath", "/dev/null"),
        ("core.fsmonitor", "false"),
        ("submodule.recurse", "false"),
    ]
    for name in await _filter_drivers(git, cwd, env):
        for key in ("smudge", "clean", "process"):
            overrides.append((f"filter.{name}.{key}", ""))
        overrides.append((f"filter.{name}.required", "false"))
    env["GIT_CONFIG_COUNT"] = str(len(overrides))
    for index, (key, value) in enumerate(overrides):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    process = await asyncio.create_subprocess_exec(
        git,
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, _stderr = await process.communicate()
    if process.returncode is None:
        return 1
    return process.returncode


async def _filter_drivers(git: str, cwd: Path, env: dict[str, str]) -> set[str]:
    """Every ``filter.<name>`` driver git sees from ``cwd``, in any config file.

    Reading config runs no command. A failed read refuses the git call, since
    the drivers it would have found could not be blanked.
    """
    process = await asyncio.create_subprocess_exec(
        git,
        "config",
        "--null",
        "--get-regexp",
        r"^filter\.",
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    # ``git config --get-regexp`` exits 1 when nothing matches.
    if process.returncode not in (0, 1):
        raise DomainError("invalid_params", "git config could not be read")
    names: set[str] = set()
    for entry in stdout.decode("utf-8", "surrogateescape").split("\0"):
        key = entry.split("\n", 1)[0]
        if not key.startswith("filter.") or key.count(".") < 2:
            continue
        names.add(key[len("filter.") : key.rindex(".")])
    return names


async def _load(agent_id: str) -> tuple[str, str, Path]:
    async with open_session() as session:
        agent = await session.get(AgentRow, agent_id)
        if agent is None:
            raise DomainError("not_found", "agent not found")
        bot = await session.get(BotRow, agent.bot_id)
        if bot is None:
            raise DomainError("not_found", "bot not found")
        return bot.id, agent.isolation, Path(bot.workspace_path)


def _alive(expires: datetime, now: datetime) -> bool:
    return _stamp(expires) > _stamp(now)


def _stamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
