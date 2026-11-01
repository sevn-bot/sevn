"""Scratch directories, shared-path locks, and git worktrees (D20)."""

from __future__ import annotations

import asyncio
import errno
import os
import shlex
import shutil
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from weakref import WeakValueDictionary

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.log import logger
from sevn.paths import Paths
from sevn.sandbox.bubblewrap import argv as bwrap_argv
from sevn.sandbox.env import child_env
from sevn.sandbox.paths import directory, regular_file, write_text
from sevn.sandbox.seatbelt import argv as seatbelt_argv
from sevn.store.db import utcnow
from sevn.store.models import Agent as AgentRow
from sevn.store.models import AgentLock, Message
from sevn.store.models import Bot as BotRow
from sevn.store.models import Turn as TurnRow

_LOCK_TTL = timedelta(minutes=10)
_GIT_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_IGNORED = "worktree ignored: workspace is not a git repo"


@dataclass(frozen=True, slots=True)
class WorkspacePlace:
    """The root file tools use for one agent."""

    bot_id: str
    agent_id: str
    root: Path
    git_metadata: Path | None = None


def scratch_dir(root: Path, agent_id: str) -> Path:
    """The agent's own folder under ``root``."""
    _check_id(agent_id)
    return root / "tasks" / agent_id


async def make_scratch(workspace: Path, agent_id: str) -> Path:
    """Create ``tasks/<agent_id>/`` and keep it across archive."""
    path = scratch_dir(workspace, agent_id)
    await asyncio.to_thread(_make_directory, path)
    return path


async def ensure(agent_id: str) -> str:
    """Prepare scratch space. A worktree note is empty when the checkout is ready."""
    bot_id, isolation, workspace = await _load(agent_id)
    await make_scratch(workspace, agent_id)
    if isolation != "worktree":
        return ""
    lock = _GIT_LOCKS.setdefault(bot_id, asyncio.Lock())
    async with lock:
        metadata = _metadata_path(bot_id)
        if not await asyncio.to_thread(_is_git, workspace) and not metadata.exists():
            return _IGNORED
        worktree = _worktree_path(agent_id)
        await asyncio.to_thread(_check_worktree_path, worktree)
        await _prepare_metadata(workspace, metadata)
        if await asyncio.to_thread(_is_worktree, worktree):
            await asyncio.to_thread(_repair_pointer, worktree, workspace, metadata)
        else:
            await _add_worktree(workspace, worktree, agent_id, metadata)
        await make_scratch(worktree, agent_id)
        return ""


def _metadata_path(bot_id: str) -> Path:
    _check_id(bot_id)
    return Paths.from_env().home.expanduser().resolve() / "git" / bot_id


async def _prepare_metadata(workspace: Path, metadata: Path) -> None:
    # The granted container's parent is host-owned. Never derive a sandbox
    # grant from a .git file or a directory the agent can replace with a link.
    await asyncio.to_thread(_make_directory, metadata)
    repo = metadata / "repo"
    await asyncio.to_thread(_restore_metadata, workspace, metadata)
    if repo.exists():
        await asyncio.to_thread(_check_worktree_path, repo)
        if (workspace / ".git").is_dir():
            raise DomainError("invalid_params", "git metadata migration needs recovery")
        # Resume a migration interrupted after moving the common directory.
        if not (workspace / ".git").exists():
            await asyncio.to_thread(write_text, workspace / ".git", f"gitdir: {repo}\n")
        return
    await _normalize_git_config(workspace, metadata)
    try:
        await asyncio.to_thread(_relocate_metadata, workspace, metadata)
    except (OSError, DomainError):
        await asyncio.to_thread(_restore_metadata, workspace, metadata)
        raise
    await asyncio.to_thread(write_text, workspace / ".git", f"gitdir: {repo}\n")


def _restore_metadata(workspace: Path, metadata: Path) -> None:
    backup = workspace / ".sevn-git-backup"
    if (metadata / "repo").exists() or os.path.lexists(workspace / ".git") or not backup.exists():
        return
    # Resume an interrupted/failed cross-volume copy from the intact source.
    with directory(backup), directory(workspace) as parent:
        os.rename(backup.name, ".git", src_dir_fd=parent, dst_dir_fd=parent)


async def _normalize_git_config(workspace: Path, metadata: Path) -> None:
    # core.worktree is relative to the common directory. Preserve its meaning
    # before moving that directory. Local includes may also depend on its old
    # location, so refuse them rather than silently changing repository config.
    git = await asyncio.to_thread(shutil.which, "git")
    if git is None:
        raise DomainError("invalid_params", "git is not available")
    process = await asyncio.create_subprocess_exec(
        git,
        "config",
        "--local",
        "--no-includes",
        "--null",
        "--get-regexp",
        r"^(core\.worktree|include.*\.path)$",
        cwd=workspace,
        env=child_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, _error = await process.communicate()
    if process.returncode not in (0, 1):
        raise DomainError("invalid_params", "git config could not be read")
    normalize = False
    for entry in output.decode("utf-8", "surrogateescape").split("\0"):
        key, separator, value = entry.partition("\n")
        if not separator:
            continue
        if key.startswith("include"):
            raise DomainError(
                "invalid_params", "flatten local git config includes before worktree isolation"
            )
        if key == "core.worktree":
            actual = Path(await asyncio.to_thread(os.path.abspath, workspace / ".git" / value))
            if actual != workspace:
                raise DomainError(
                    "invalid_params", "git working tree differs from the bot workspace"
                )
            normalize = not Path(value).is_absolute()
    if (
        normalize
        and await _git(
            workspace, "config", "--local", "core.worktree", str(workspace), target=metadata
        )
        != 0
    ):
        raise DomainError("invalid_params", "git config could not be normalized")


def _relocate_metadata(workspace: Path, metadata: Path) -> None:
    # Rename outside the sandbox's bind mounts; even paths on one host volume
    # are different mounts in bubblewrap. Pin both parents and the source,
    # refusing a .git symlink and detecting replacement during the rename.
    with directory(workspace) as source, directory(metadata) as target:
        with directory(workspace / ".git") as original:
            expected = os.fstat(original)
            try:
                os.rename(".git", "repo", src_dir_fd=source, dst_dir_fd=target)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                # Withdraw the old gitdir before copying: concurrent commands
                # using .git must fail instead of successfully committing into
                # a source whose refs/objects have already been copied. Retain
                # this backup for recovery; never delete newer source history.
                backup = ".sevn-git-backup"
                if (workspace / backup).exists():
                    raise DomainError(
                        "invalid_params", "git migration backup already exists"
                    ) from exc
                _exclude_backup(workspace / ".git" / "info" / "exclude")
                os.rename(".git", backup, src_dir_fd=source, dst_dir_fd=source)
                moved = os.stat(backup, dir_fd=source, follow_symlinks=False)
                if (moved.st_dev, moved.st_ino) != (expected.st_dev, expected.st_ino):
                    raise DomainError(
                        "invalid_params", "git metadata changed during migration"
                    ) from exc
                # External workspace volumes need a copy. All reads are pinned
                # and O_NOFOLLOW; copied symlinks are never traversed.
                staging = metadata / "copying"
                if staging.exists():
                    shutil.rmtree("copying", dir_fd=target)
                with directory(staging, create=True) as copy:
                    _copy_metadata(original, copy)
                current = os.stat(backup, dir_fd=source, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
                    raise DomainError(
                        "invalid_params", "git metadata changed during migration"
                    ) from exc
                # Publish only a complete copy. A crash after publication is
                # detected on restart without discarding either Git history.
                os.rename("copying", "repo", src_dir_fd=target, dst_dir_fd=target)
                return
            moved = os.stat("repo", dir_fd=target, follow_symlinks=False)
            if (moved.st_dev, moved.st_ino) != (expected.st_dev, expected.st_ino):
                raise DomainError("invalid_params", "git metadata changed during migration")


def _exclude_backup(path: Path) -> None:
    with regular_file(path, write=True, create_parents=True) as descriptor:
        with os.fdopen(os.dup(descriptor), "r+", encoding="utf-8") as stream:
            content = stream.read()
            if "/.sevn-git-backup/" not in content.splitlines():
                stream.seek(0, os.SEEK_END)
                stream.write("\n/.sevn-git-backup/\n")


def _copy_metadata(source: int, target: int) -> None:
    with os.scandir(source) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                os.symlink(os.readlink(entry.name, dir_fd=source), entry.name, dir_fd=target)
            elif stat.S_ISDIR(info.st_mode):
                os.mkdir(entry.name, mode=0o700, dir_fd=target)
                src = os.open(
                    entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source
                )
                try:
                    dst = os.open(
                        entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=target
                    )
                    try:
                        _copy_metadata(src, dst)
                    finally:
                        os.close(dst)
                finally:
                    os.close(src)
            elif stat.S_ISREG(info.st_mode):
                src = os.open(
                    entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source
                )
                with os.fdopen(src, "rb") as incoming:
                    if not stat.S_ISREG(os.fstat(src).st_mode):
                        raise DomainError("invalid_params", "invalid git metadata file")
                    dst = os.open(
                        entry.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=target
                    )
                    with os.fdopen(dst, "wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                        os.fchmod(dst, stat.S_IMODE(info.st_mode))
            else:
                raise DomainError("invalid_params", "invalid git metadata file")


def _repair_pointer(worktree: Path, workspace: Path, metadata: Path) -> None:
    # Git normally repairs linked worktrees during relocation. Its confined
    # migration cannot write other lanes, so repair this known lane on entry.
    with regular_file(worktree / ".git") as descriptor:
        with os.fdopen(os.dup(descriptor), encoding="utf-8") as stream:
            pointer = stream.read().strip()
    if not pointer.startswith("gitdir: "):
        raise DomainError("invalid_params", "invalid worktree metadata")
    old = Path(os.path.abspath(worktree / pointer.removeprefix("gitdir: ")))
    if old.parent == workspace / ".git" / "worktrees":
        replacement = metadata / "repo" / "worktrees" / old.name
        write_text(worktree / ".git", f"gitdir: {replacement}\n")
    elif old.parent != metadata / "repo" / "worktrees":
        raise DomainError("invalid_params", "invalid worktree metadata")
    # Relative backpointers were based on the old common directory location.
    write_text(metadata / "repo" / "worktrees" / old.name / "gitdir", str(worktree / ".git") + "\n")


async def open_place(agent_id: str) -> WorkspacePlace:
    """Root for file tools: the worktree when isolation is active, else the workspace."""
    note = await ensure(agent_id)
    bot_id, isolation, workspace = await _load(agent_id)
    workspace = workspace.resolve()
    root = workspace
    if isolation == "worktree" and note == "":
        root = _worktree_path(agent_id)
    metadata = _metadata_path(bot_id)
    if metadata.exists():
        await asyncio.to_thread(_check_worktree_path, metadata)
    return WorkspacePlace(
        bot_id=bot_id,
        agent_id=agent_id,
        root=root,
        git_metadata=metadata if metadata.exists() else None,
    )


def _make_directory(path: Path) -> None:
    with directory(path, create=True):
        pass


def _check_worktree_path(worktree: Path) -> None:
    # The parent lives outside every bot workspace. A confined shell cannot
    # replace it between this check and git/sandbox setup.
    if worktree.resolve() != worktree:
        raise DomainError("path_outside_workspace", "path is outside the workspace")
    ancestor = worktree
    while not ancestor.exists():
        ancestor = ancestor.parent
    with directory(ancestor):
        pass


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


def _worktree_path(agent_id: str) -> Path:
    _check_id(agent_id)
    return Paths.from_env().home.expanduser().resolve() / "worktrees" / agent_id


def purge_worktrees(agent_ids: list[str], bot_id: str) -> None:
    """Remove owned checkouts; the bot purge also removes their repository metadata.

    The parent is pinned and rmtree refuses symlink traversal. A symlink entry
    is unlinked rather than following it into a directory outside host storage.
    """
    for path in [*(_worktree_path(agent_id) for agent_id in agent_ids), _metadata_path(bot_id)]:
        if not path.parent.exists():
            continue
        with directory(path.parent) as parent:
            try:
                if path.is_symlink():
                    path.unlink()
                else:
                    shutil.rmtree(path.name, dir_fd=parent)
            except FileNotFoundError:
                pass


def _is_git(workspace: Path) -> bool:
    return (workspace / ".git").exists()


def _is_worktree(path: Path) -> bool:
    return (path / ".git").exists()


async def _add_worktree(workspace: Path, worktree: Path, agent_id: str, metadata: Path) -> None:
    await asyncio.to_thread(_make_directory, worktree)
    code = await _git(
        workspace,
        "worktree",
        "add",
        "-b",
        f"sevn/{agent_id}",
        str(worktree),
        target=worktree,
        git_metadata=metadata,
    )
    if code != 0:
        logger.warning("git worktree add failed")
        raise DomainError("invalid_params", "git worktree add failed")


async def _git(cwd: Path, *args: str, target: Path, git_metadata: Path | None = None) -> int:
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
    # Config can change after enumeration. Confinement is the security boundary
    # for any newly introduced driver, hook, include or worktree config.
    command = shlex.join([git, *args])
    if sys.platform == "darwin":
        argv = seatbelt_argv(
            command, workspace=cwd, shared=target, network=False, git_metadata=git_metadata
        )
    elif sys.platform == "linux":
        argv = bwrap_argv(
            command, workspace=cwd, shared=target, network=False, git_metadata=git_metadata
        )
    else:
        raise DomainError("invalid_params", "sandbox is unavailable")
    process = await asyncio.create_subprocess_exec(
        *argv,
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
