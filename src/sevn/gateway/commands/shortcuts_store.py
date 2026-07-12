"""Workspace shortcut CRUD for ``workspace/shortcuts.json``.

Module: sevn.gateway.commands.shortcuts_store
Depends: json, pathlib, typing

Exports:
    ShortcutRecord — typed shortcut row shape.
    shortcuts_path — resolve ``shortcuts.json`` under content root.
    load_shortcuts — read shortcut list from disk.
    save_shortcuts — persist shortcut list atomically.
    add_shortcut — append one shortcut with collision checks.
    update_shortcut — replace an existing shortcut by name.
    delete_shortcut — remove a shortcut by name.
    find_shortcut — lookup one shortcut by name.
    list_visible_shortcuts — filter shortcuts for ``setMyCommands``.
    validate_shortcut_name — validate pattern and reserved-name rules.
    republish_set_my_commands — call Telegram ``setMyCommands`` after CRUD.
Examples:
    >>> "start" in CORE_COMMAND_NAMES
    True
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from loguru import logger

ShortcutHandlerType = Literal["menu", "toggle", "prompt", "skill", "action", "scene", "form"]

CORE_COMMAND_NAMES: frozenset[str] = frozenset(
    {
        "start",
        "help",
        "new",
        "status",
        "stop",
        "config",
        "voice",
        "model",
        "menu",
        "steer",
        "topic",
        "ask-config",
    },
)

_SHORTCUT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_SHORTCUTS_FILENAME = "shortcuts.json"
_WARN_AT = 50
_HARD_CAP = 95


class ShortcutRecord(TypedDict, total=False):
    """One user-defined shortcut row."""

    name: str
    description: str
    type: ShortcutHandlerType
    payload: dict[str, Any]
    scope: str
    visibility: bool
    auth: str
    owner_user_id: str
    quarantine: bool


def shortcuts_path(content_root: Path) -> Path:
    """Return ``<content_root>/shortcuts.json``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Absolute shortcuts file path.

    Examples:
        >>> from pathlib import Path
        >>> shortcuts_path(Path("/w/")) == Path("/w/shortcuts.json")
        True
    """
    return content_root.expanduser().resolve() / _SHORTCUTS_FILENAME


def _empty_doc() -> dict[str, Any]:
    """Return an empty shortcuts document shell.

    Returns:
        dict[str, Any]: ``{"schema_version": 1, "shortcuts": []}``.

    Examples:
        >>> _empty_doc()["schema_version"]
        1
    """
    return {"schema_version": 1, "shortcuts": []}


def load_shortcuts(content_root: Path) -> list[ShortcutRecord]:
    """Load shortcuts from ``workspace/shortcuts.json``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        list[ShortcutRecord]: Parsed shortcut rows (may be empty).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> load_shortcuts(Path(tempfile.mkdtemp()))
        []
    """
    path = shortcuts_path(content_root)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("shortcuts.json invalid JSON at {}", path)
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get("shortcuts")
    if not isinstance(rows, list):
        return []
    out: list[ShortcutRecord] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            out.append(row)  # type: ignore[arg-type]
    return out


def save_shortcuts(content_root: Path, shortcuts: list[ShortcutRecord]) -> None:
    """Persist *shortcuts* atomically to ``shortcuts.json``.

    Args:
        content_root (Path): Workspace content root.
        shortcuts (list[ShortcutRecord]): Rows to write.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> save_shortcuts(root, [])
        >>> shortcuts_path(root).is_file()
        True
    """
    if len(shortcuts) >= _WARN_AT:
        logger.warning("shortcuts count {} approaching Telegram cap {}", len(shortcuts), _HARD_CAP)
    if len(shortcuts) > _HARD_CAP:
        msg = f"shortcut hard cap {_HARD_CAP} exceeded"
        raise ValueError(msg)
    path = shortcuts_path(content_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"schema_version": 1, "shortcuts": shortcuts}, indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def validate_shortcut_name(name: str) -> None:
    """Raise when *name* is invalid or collides with a core command.

    Args:
        name (str): Candidate shortcut name without leading ``/``.

    Raises:
        ValueError: Invalid pattern or reserved name.

    Examples:
        >>> validate_shortcut_name("standup")
        >>> try:
        ...     validate_shortcut_name("start")
        ... except ValueError as exc:
        ...     "reserved" in str(exc)
        ... else:
        ...     False
        True
    """
    n = name.strip().lower()
    if not _SHORTCUT_NAME_RE.match(n):
        msg = f"invalid shortcut name {name!r}"
        raise ValueError(msg)
    if n in CORE_COMMAND_NAMES:
        msg = f"reserved core command name {n!r}"
        raise ValueError(msg)


def add_shortcut(content_root: Path, record: ShortcutRecord) -> ShortcutRecord:
    """Append *record* when the name is free.

    Args:
        content_root (Path): Workspace content root.
        record (ShortcutRecord): New shortcut row.

    Returns:
        ShortcutRecord: Stored row (normalised name).

    Raises:
        ValueError: Invalid name, collision, or cap exceeded.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> row = add_shortcut(
        ...     root,
        ...     {"name": "standup", "description": "Daily", "type": "prompt", "payload": {}},
        ... )
        >>> row["name"]
        'standup'
    """
    name = str(record.get("name", "")).strip().lower()
    validate_shortcut_name(name)
    rows = load_shortcuts(content_root)
    if any(str(r.get("name", "")).lower() == name for r in rows):
        msg = f"shortcut {name!r} already exists"
        raise ValueError(msg)
    normalised = cast("ShortcutRecord", dict(record))
    normalised["name"] = name
    rows.append(normalised)
    save_shortcuts(content_root, rows)
    return normalised


def update_shortcut(content_root: Path, name: str, record: ShortcutRecord) -> ShortcutRecord:
    """Replace the shortcut named *name*.

    Args:
        content_root (Path): Workspace content root.
        name (str): Existing shortcut name.
        record (ShortcutRecord): Replacement row.

    Returns:
        ShortcutRecord: Stored row.

    Raises:
        ValueError: When the shortcut does not exist or name is invalid.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> _ = add_shortcut(root, {"name": "ab", "description": "A", "type": "menu", "payload": {}})
        >>> update_shortcut(
        ...     root, "ab", {"name": "ab", "description": "B", "type": "menu", "payload": {}},
        ... )["description"]
        'B'
    """
    key = name.strip().lower()
    validate_shortcut_name(key)
    rows = load_shortcuts(content_root)
    idx = next((i for i, r in enumerate(rows) if str(r.get("name", "")).lower() == key), None)
    if idx is None:
        msg = f"shortcut {key!r} not found"
        raise ValueError(msg)
    normalised = cast("ShortcutRecord", dict(record))
    normalised["name"] = key
    rows[idx] = normalised
    save_shortcuts(content_root, rows)
    return normalised


def delete_shortcut(content_root: Path, name: str) -> bool:
    """Delete the shortcut named *name*.

    Args:
        content_root (Path): Workspace content root.
        name (str): Shortcut name to remove.

    Returns:
        bool: ``True`` when a row was removed.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> _ = add_shortcut(root, {"name": "xy", "description": "X", "type": "prompt", "payload": {}})
        >>> delete_shortcut(root, "xy")
        True
        >>> delete_shortcut(root, "xy")
        False
    """
    key = name.strip().lower()
    rows = load_shortcuts(content_root)
    kept = [r for r in rows if str(r.get("name", "")).lower() != key]
    if len(kept) == len(rows):
        return False
    save_shortcuts(content_root, kept)
    return True


def find_shortcut(content_root: Path, name: str) -> ShortcutRecord | None:
    """Return the shortcut named *name*, if present.

    Args:
        content_root (Path): Workspace content root.
        name (str): Shortcut name without ``/``.

    Returns:
        ShortcutRecord | None: Matching row or ``None``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> find_shortcut(root, "missing") is None
        True
    """
    key = name.strip().lower()
    for row in load_shortcuts(content_root):
        if str(row.get("name", "")).lower() == key:
            return row
    return None


def list_visible_shortcuts(
    content_root: Path,
    *,
    user_id: str,
    is_owner: bool,
) -> list[ShortcutRecord]:
    """Return shortcuts eligible for ``setMyCommands`` for *user_id*.

    Args:
        content_root (Path): Workspace content root.
        user_id (str): Telegram user id string.
        is_owner (bool): Whether the user is workspace owner.

    Returns:
        list[ShortcutRecord]: Visible, non-quarantined shortcuts.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> list_visible_shortcuts(root, user_id="1", is_owner=True)
        []
    """
    out: list[ShortcutRecord] = []
    for row in load_shortcuts(content_root):
        if row.get("quarantine"):
            continue
        if not row.get("visibility", True):
            continue
        auth = str(row.get("auth", "PUBLIC")).upper()
        if auth == "OWNER" and not is_owner:
            continue
        if auth == "ADMIN" and not is_owner:
            continue
        owner = row.get("owner_user_id")
        if isinstance(owner, str) and owner and owner != user_id and auth not in {"PUBLIC"}:
            continue
        out.append(row)
    return out


async def republish_set_my_commands(router: object) -> None:
    """Call Telegram ``setMyCommands`` after shortcut mutations.

    Args:
        router (object): :class:`~sevn.gateway.channel_router.ChannelRouter`
            with a registered Telegram adapter.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(republish_set_my_commands)
        True
    """
    adapters = getattr(router, "_adapters", None)
    if not isinstance(adapters, dict):
        return
    adapter = adapters.get("telegram")
    if adapter is None:
        return
    flush = getattr(adapter, "_flush_set_my_commands", None)
    if callable(flush):
        result = flush()
        if asyncio.iscoroutine(result):
            await result


__all__ = [
    "CORE_COMMAND_NAMES",
    "ShortcutHandlerType",
    "ShortcutRecord",
    "add_shortcut",
    "delete_shortcut",
    "find_shortcut",
    "list_visible_shortcuts",
    "load_shortcuts",
    "republish_set_my_commands",
    "save_shortcuts",
    "shortcuts_path",
    "update_shortcut",
    "validate_shortcut_name",
]
