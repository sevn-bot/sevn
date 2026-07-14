"""Telegram /config Second Brain vault path menu tests."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.menu.menu import _second_brain_vault_display, config_menu_message_text


def test_second_brain_caption_shows_vault_path(tmp_path: Path) -> None:
    sj = tmp_path / "sevn.json"
    sj.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "x"},
                "second_brain": {
                    "enabled": True,
                    "paths": {"vault": "obsidian/alex_AI"},
                },
            },
        ),
        encoding="utf-8",
    )
    ws = WorkspaceConfig.model_validate(json.loads(sj.read_text(encoding="utf-8")))
    caption = config_menu_message_text(ws, section="second_brain", content_root=tmp_path)
    assert "Vault: obsidian/alex_AI" in caption


def test_vault_display_default_layout(tmp_path: Path) -> None:
    rel = _second_brain_vault_display(tmp_path, WorkspaceConfig.minimal())
    assert rel == "second_brain/users/owner"
