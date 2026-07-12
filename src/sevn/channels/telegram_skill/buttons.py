"""Workspace custom Telegram inline button store (teleshell-style).

Module: sevn.channels.telegram_skill.buttons
Depends: json, pathlib

Exports:
    buttons_store_path — resolve ``.sevn/telegram_buttons.json``.
    list_custom_buttons — list stored buttons.
    add_custom_button — append one button.
    remove_custom_button — delete by display name.
    clear_custom_buttons — empty the store.
    build_custom_inline_keyboard — two-column ``inline_keyboard`` rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BUTTONS_FILENAME = "telegram_buttons.json"


def buttons_store_path(workspace: Path) -> Path:
    """Return the workspace custom-button JSON path.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        Path: ``<workspace>/.sevn/telegram_buttons.json``.

    Examples:
        >>> buttons_store_path(Path("/w")).name
        'telegram_buttons.json'
    """
    return workspace / ".sevn" / _BUTTONS_FILENAME


def _load_store(path: Path) -> dict[str, Any]:
    """Load the button store JSON from disk.

    Args:
        path (Path): Store file path.

    Returns:
        dict[str, Any]: Parsed store with a ``buttons`` list.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "telegram_buttons.json"
        >>> _load_store(p)["buttons"]
        []
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"buttons": []}
        if isinstance(data, dict):
            buttons = data.get("buttons")
            if isinstance(buttons, list):
                return {"buttons": buttons}
    return {"buttons": []}


def _save_store(path: Path, data: dict[str, Any]) -> None:
    """Persist the button store JSON to disk.

    Args:
        path (Path): Store file path.
        data (dict[str, Any]): Store payload to write.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "telegram_buttons.json"
        >>> _save_store(p, {"buttons": []})
        >>> p.is_file()
        True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_custom_buttons(workspace: Path) -> list[dict[str, str]]:
    """List custom inline buttons stored for the workspace.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        list[dict[str, str]]: Rows with ``name`` and ``command`` keys.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> list_custom_buttons(ws)
        []
    """
    store = _load_store(buttons_store_path(workspace))
    rows = store.get("buttons", [])
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        command = str(row.get("command") or "").strip()
        if name and command:
            out.append({"name": name, "command": command})
    return out


def add_custom_button(workspace: Path, *, name: str, command: str) -> bool:
    """Add a custom button when the display name is not already present.

    Args:
        workspace (Path): Workspace content root.
        name (str): Button label shown in Telegram.
        command (str): Slash command or callback payload stored for the button.

    Returns:
        bool: ``False`` when the name already exists.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> add_custom_button(ws, name="Help", command="/help")
        True
        >>> add_custom_button(ws, name="Help", command="/help")
        False
    """
    label = name.strip()
    cmd = command.strip()
    if not label or not cmd:
        return False
    path = buttons_store_path(workspace)
    data = _load_store(path)
    buttons = data.get("buttons", [])
    if not isinstance(buttons, list):
        buttons = []
    for row in buttons:
        if isinstance(row, dict) and str(row.get("name") or "").strip() == label:
            return False
    buttons.append({"name": label, "command": cmd})
    data["buttons"] = buttons
    _save_store(path, data)
    return True


def remove_custom_button(workspace: Path, *, name: str) -> bool:
    """Remove one custom button by display name.

    Args:
        workspace (Path): Workspace content root.
        name (str): Button label to remove.

    Returns:
        bool: ``False`` when no matching button exists.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = add_custom_button(ws, name="A", command="/a")
        >>> remove_custom_button(ws, name="A")
        True
        >>> remove_custom_button(ws, name="A")
        False
    """
    label = name.strip()
    if not label:
        return False
    path = buttons_store_path(workspace)
    data = _load_store(path)
    buttons = data.get("buttons", [])
    if not isinstance(buttons, list):
        return False
    orig_len = len(buttons)
    filtered = [
        row
        for row in buttons
        if not (isinstance(row, dict) and str(row.get("name") or "").strip() == label)
    ]
    if len(filtered) == orig_len:
        return False
    data["buttons"] = filtered
    _save_store(path, data)
    return True


def clear_custom_buttons(workspace: Path) -> int:
    """Remove all custom buttons from the workspace store.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        int: Number of buttons removed.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = add_custom_button(ws, name="A", command="/a")
        >>> clear_custom_buttons(ws)
        1
        >>> list_custom_buttons(ws)
        []
    """
    path = buttons_store_path(workspace)
    data = _load_store(path)
    buttons = data.get("buttons", [])
    count = len(buttons) if isinstance(buttons, list) else 0
    data["buttons"] = []
    _save_store(path, data)
    return count


def build_custom_inline_keyboard(workspace: Path) -> dict[str, Any]:
    """Build a Telegram ``inline_keyboard`` from stored custom buttons (two per row).

    Args:
        workspace (Path): Workspace content root.

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict with ``inline_keyboard`` rows.

    Examples:
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> kb = build_custom_inline_keyboard(ws)
        >>> kb["inline_keyboard"] == []
        True
    """
    buttons = list_custom_buttons(workspace)
    keyboard: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for btn in buttons:
        row.append({"text": btn["name"], "callback_data": f"btn:{btn['name']}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return {"inline_keyboard": keyboard}
