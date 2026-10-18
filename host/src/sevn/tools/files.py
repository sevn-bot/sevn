"""Workspace file tools. Paths stay inside the workspace or Shared (D13, D20)."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from sevn.decisions.registry import screen_inbound
from sevn.domain.errors import DomainError
from sevn.domain.workspace import WorkspacePlace, acquire_write, open_place, scratch_dir
from sevn.paths import Paths
from sevn.tools.registry import TurnDeps, register_toolset

_OUTSIDE = "path is outside the workspace"
_SKIP = frozenset({".git", ".sevn"})
_MATCH_LIMIT = 50
_FILE_LIMIT = 200


async def read_file(bot_id: str, agent_id: str, path: str) -> str:
    """Read a text file inside the workspace or Shared."""
    located = await _owned(bot_id, agent_id)
    text = await asyncio.to_thread(_read_text, located.root, path)
    return await screen_inbound(text)


async def write_file(bot_id: str, agent_id: str, path: str, content: str) -> str:
    """Write a text file. Shared paths take an advisory lock; scratch paths do not."""
    located = await _owned(bot_id, agent_id)
    resolved, locked = await asyncio.to_thread(_target, located.root, agent_id, path)
    if locked:
        await acquire_write(agent_id, str(resolved))
    await asyncio.to_thread(_write_text, resolved, content)
    return path


async def edit_file(bot_id: str, agent_id: str, path: str, old: str, new: str) -> str:
    """Replace the first ``old`` span in the file on disk.

    ``read_file`` may wrap flagged content for the model (D11). That view is not
    the file, so the replacement is applied to the bytes on disk.
    """
    if old == "":
        raise DomainError("invalid_params", "edit text is empty")
    located = await _owned(bot_id, agent_id)
    current = await asyncio.to_thread(_read_text, located.root, path)
    if old not in current:
        raise DomainError("invalid_params", "edit text was not found")
    await write_file(bot_id, agent_id, path, current.replace(old, new, 1))
    return path


async def list_dir(bot_id: str, agent_id: str, path: str = ".") -> str:
    """List one directory inside the workspace or Shared."""
    located = await _owned(bot_id, agent_id)
    names = await asyncio.to_thread(_list_names, located.root, path)
    return "\n".join(names)


async def grep(bot_id: str, agent_id: str, pattern: str, path: str = ".") -> str:
    """Search text files under a workspace path."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise DomainError("invalid_params", "invalid pattern") from exc
    located = await _owned(bot_id, agent_id)
    hits = await asyncio.to_thread(_search, located.root, path, compiled)
    return "\n".join(hits)


async def attach(bot_id: str, agent_id: str, path: str) -> str:
    """Check a workspace file and return its path so the reply can include it."""
    located = await _owned(bot_id, agent_id)
    resolved = await asyncio.to_thread(_resolve, located.root, path)
    is_file = await asyncio.to_thread(resolved.is_file)
    if not is_file:
        raise DomainError("not_found", "file not found")
    return str(resolved)


def files_toolset(deps: TurnDeps) -> dict[str, object]:
    """File tools bound to one turn."""

    async def read_path(path: str) -> str:
        """Read a text file in the workspace or Shared."""
        return await read_file(deps.bot_id, deps.agent_id, path)

    async def write_path(path: str, content: str) -> str:
        """Write a text file in the workspace or Shared."""
        return await write_file(deps.bot_id, deps.agent_id, path, content)

    async def edit_path(path: str, old: str, new: str) -> str:
        """Replace the first exact span in a workspace file."""
        return await edit_file(deps.bot_id, deps.agent_id, path, old, new)

    async def list_path(path: str = ".") -> str:
        """List names in a workspace directory."""
        return await list_dir(deps.bot_id, deps.agent_id, path)

    async def search_path(pattern: str, path: str = ".") -> str:
        """Find lines matching a regular expression."""
        return await grep(deps.bot_id, deps.agent_id, pattern, path)

    async def attach_path(path: str) -> str:
        """Add a workspace file to the reply."""
        return await attach(deps.bot_id, deps.agent_id, path)

    return {
        "read_file": read_path,
        "write_file": write_path,
        "edit_file": edit_path,
        "list_dir": list_path,
        "grep": search_path,
        "files.attach": attach_path,
    }


register_toolset(
    "files",
    files_toolset,
    {"files.attach", "read_file", "write_file", "edit_file", "list_dir", "grep"},
)


async def _owned(bot_id: str, agent_id: str) -> WorkspacePlace:
    located = await open_place(agent_id)
    if located.bot_id != bot_id:
        raise DomainError("not_found", "agent not found")
    return located


def _target(root: Path, agent_id: str, raw: str) -> tuple[Path, bool]:
    resolved = _resolve(root, raw)
    scratch = scratch_dir(root, agent_id).resolve()
    return resolved, not _inside(resolved, scratch)


def _read_text(root: Path, raw: str) -> str:
    resolved = _resolve(root, raw)
    if not resolved.is_file():
        raise DomainError("not_found", "file not found")
    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise DomainError("invalid_params", "file is not text") from exc


def _write_text(path: Path, content: str) -> None:
    if path.exists() and path.is_dir():
        raise DomainError("invalid_params", "path is a directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _list_names(root: Path, raw: str) -> list[str]:
    resolved = _resolve(root, raw)
    if not resolved.is_dir():
        raise DomainError("invalid_params", "path is not a directory")
    return sorted(item.name for item in resolved.iterdir())


def _search(root: Path, raw: str, pattern: re.Pattern[str]) -> list[str]:
    resolved = _resolve(root, raw)
    hits: list[str] = []
    for item in _files(resolved):
        if len(hits) >= _MATCH_LIMIT:
            break
        checked = item.resolve()
        if not _allowed(checked, root):
            continue
        try:
            text = checked.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        label = _label(checked, root)
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line) is None:
                continue
            hits.append(f"{label}:{number}:{line}")
            if len(hits) >= _MATCH_LIMIT:
                break
    return hits


def _files(start: Path) -> list[Path]:
    if start.is_file():
        return [start]
    if not start.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in _SKIP]
        for name in filenames:
            found.append(Path(dirpath) / name)
            if len(found) >= _FILE_LIMIT:
                return found
    return found


def _resolve(root: Path, raw: str) -> Path:
    if raw == "" or "\x00" in raw:
        raise DomainError("path_outside_workspace", _OUTSIDE)
    base = root.resolve()
    candidate = Path(raw)
    target = candidate if candidate.is_absolute() else base / candidate
    resolved = target.resolve(strict=False)
    if _allowed(resolved, root):
        return resolved
    raise DomainError("path_outside_workspace", _OUTSIDE)


def _allowed(path: Path, root: Path) -> bool:
    if _inside(path, root.resolve()):
        return True
    shared = (Paths.from_env().workspaces.parent / "Shared").resolve()
    return _inside(path, shared)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)
