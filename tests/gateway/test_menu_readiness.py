"""Tests for menu readiness gating and schema loading without repo checkout."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.cli.repo_sync import RepoSyncError
from sevn.cli.workspace_schema import load_workspace_json_schema
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.menu.menu import (
    _apply_operator_readiness_gate,
    _workspace_json_schema,
    build_config_menu_keyboard,
    config_menu_message_text,
)
from sevn.gateway.menu.menu_readiness import (
    config_menu_help_catalog_text,
    gate_config_keyboard_rows,
    readiness_for_callback,
)
from sevn.gateway.menu.menu_registry import match_menu_button_spec
from tests.gateway.telegram_menu_redesign_helpers import (
    iter_rendered_buttons,
    load_baseline_wip_spec_ids,
)


def test_load_workspace_json_schema_without_repo_root() -> None:
    with patch(
        "sevn.cli.workspace_schema.resolve_sevn_repo_root",
        side_effect=RepoSyncError("no repo"),
    ):
        doc = load_workspace_json_schema()
    assert isinstance(doc.get("properties"), dict)


def test_help_section_catalog_not_command_submenu() -> None:
    catalog = config_menu_help_catalog_text()
    assert "Session" in catalog
    assert "Tools" in catalog
    assert "/new — start" not in catalog
    help_caption = config_menu_message_text(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        section="help",
    )
    assert help_caption.startswith("Help")


def test_help_keyboard_includes_sevn_bot_actions() -> None:
    kb = build_config_menu_keyboard(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        section="help",
    )
    rows = kb["inline_keyboard"]
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert any(cb.startswith("act:sevn_bot:") for cb in callbacks)
    assert "cfg:section:sevn_bot" in callbacks
    assert any(cb.startswith("cfg:nav:") for cb in callbacks)


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
        section="chat_voice",
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
        kb = build_config_menu_keyboard(ws, section="skills_tools", content_root=tmp_path)
    assert "inline_keyboard" in kb


def _callbacks_for_spec_id(spec_id: str) -> list[str]:
    hits: list[str] = []
    for _section, _label, cb in iter_rendered_buttons():
        spec = match_menu_button_spec(cb)
        if spec is not None and spec.spec_id == spec_id:
            hits.append(cb)
    return hits


@pytest.mark.parametrize("spec_id", sorted(load_baseline_wip_spec_ids()))
def test_wip_spec_id_becomes_ready(spec_id: str) -> None:
    """W1.7 — each W0 WIP id is allow-listed and resolves to Ready."""
    callbacks = _callbacks_for_spec_id(spec_id)
    if not callbacks:
        pytest.skip(f"{spec_id} not rendered on redesign tree yet")
    for cb in callbacks:
        assert readiness_for_callback(cb) == "Ready"


def test_non_ready_disabled_callbacks_still_prefixed_and_toast() -> None:
    """W1.7 — anything left non-Ready keeps 🚧 prefix and cfg:disabled:* answers."""
    from sevn.gateway.menu.menu_readiness import DISABLED_CALLBACK_PREFIX, gate_config_keyboard_rows

    rows = [
        [
            {
                "text": "Refresh skills",
                "callback_data": "cfg:skills:refresh",
            }
        ]
    ]
    gated = gate_config_keyboard_rows(rows)
    cb = gated[0][0]["callback_data"]
    assert cb.startswith(DISABLED_CALLBACK_PREFIX)
    assert readiness_for_callback("cfg:skills:refresh") != "Ready"
