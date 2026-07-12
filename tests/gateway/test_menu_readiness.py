"""Tests for menu readiness gating and schema loading without repo checkout."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.cli.repo_sync import RepoSyncError
from sevn.cli.workspace_schema import load_workspace_json_schema
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.menu import (
    _apply_operator_readiness_gate,
    _workspace_json_schema,
    build_config_menu_keyboard,
    config_menu_message_text,
)
from sevn.gateway.menu_readiness import (
    config_menu_help_catalog_text,
    gate_config_keyboard_rows,
    readiness_for_callback,
)


def test_load_workspace_json_schema_without_repo_root() -> None:
    with patch(
        "sevn.cli.workspace_schema.resolve_sevn_repo_root",
        side_effect=RepoSyncError("no repo"),
    ):
        doc = load_workspace_json_schema()
    assert isinstance(doc.get("properties"), dict)


def test_help_section_catalog_not_command_submenu() -> None:
    text = config_menu_message_text(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        section="help",
    )
    assert "Session" in text
    assert "Tools" in text
    assert "/new — start" not in text
    assert config_menu_help_catalog_text() == text


def test_help_keyboard_has_no_action_rows() -> None:
    kb = build_config_menu_keyboard(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        section="help",
    )
    rows = kb["inline_keyboard"]
    assert len(rows) == 1
    assert rows[0][0]["callback_data"] == "cfg:nav:back"


def test_readiness_allows_voice_tts_toggle() -> None:
    # Voice TTS mode buttons (C3.1-C3.3) are operator-enabled: pressable, not locked.
    rows = [[{"text": "TTS: all", "callback_data": "cfg:voice:mode:all"}]]
    gated = gate_config_keyboard_rows(rows)
    assert gated[0][0]["callback_data"] == "cfg:voice:mode:all"
    assert not gated[0][0]["callback_data"].startswith("cfg:disabled:")


def test_readiness_allows_session_toggle() -> None:
    assert (
        readiness_for_callback("cfg:toggle:channels.telegram.quick_actions.show_regen:true")
        == "Ready"
    )


def test_readiness_allows_codemode_toggle() -> None:
    assert readiness_for_callback("cfg:toggle:agent.codemode.enabled:true") == "Ready"
    rows = [
        [
            {
                "text": "CodeMode off",
                "callback_data": "cfg:toggle:agent.codemode.enabled:true",
            },
        ],
    ]
    gated = gate_config_keyboard_rows(rows)
    assert gated[0][0]["callback_data"] == "cfg:toggle:agent.codemode.enabled:true"


def test_apply_operator_readiness_gate_preserves_chrome() -> None:
    raw = build_config_menu_keyboard(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        section="voice",
    )
    gated = _apply_operator_readiness_gate(raw)
    chrome = gated["inline_keyboard"][-1]
    assert chrome[0]["callback_data"] == "cfg:nav:back"


@pytest.mark.asyncio
async def test_build_tools_keyboard_without_repo_sync_error(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    _workspace_json_schema.cache_clear()
    with patch(
        "sevn.cli.workspace_schema.resolve_sevn_repo_root",
        side_effect=RepoSyncError("no repo"),
    ):
        kb = build_config_menu_keyboard(ws, section="tools", content_root=tmp_path)
    assert "inline_keyboard" in kb
