"""Shortcut CRUD tests (`plan/control-surface-wave-plan.md` Wave 3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.gateway.commands.shortcuts_store import (
    add_shortcut,
    delete_shortcut,
    load_shortcuts,
    republish_set_my_commands,
    validate_shortcut_name,
)


def test_add_edit_delete_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    add_shortcut(
        root,
        {"name": "standup", "description": "Daily standup", "type": "prompt", "payload": {}},
    )
    rows = load_shortcuts(root)
    assert len(rows) == 1
    assert rows[0]["name"] == "standup"
    assert delete_shortcut(root, "standup")
    assert load_shortcuts(root) == []


def test_core_name_collision_rejected(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    with pytest.raises(ValueError, match="reserved"):
        add_shortcut(
            root,
            {"name": "start", "description": "bad", "type": "prompt", "payload": {}},
        )


def test_validate_shortcut_name_pattern() -> None:
    validate_shortcut_name("ok_name")
    with pytest.raises(ValueError, match="invalid"):
        validate_shortcut_name("1bad")


@pytest.mark.asyncio
async def test_republish_calls_flush_set_my_commands() -> None:
    adapter = AsyncMock()
    adapter._flush_set_my_commands = AsyncMock()
    router = type("R", (), {"_adapters": {"telegram": adapter}})()
    await republish_set_my_commands(router)
    adapter._flush_set_my_commands.assert_awaited_once()
