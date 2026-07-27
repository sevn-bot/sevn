"""Tests for ``sevn config`` section menu and ``config_paths`` SSOT (W8)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.config_paths import (
    iter_config_sections,
    menu_registry_root_slugs,
    section_by_slug,
    section_callback,
)
from sevn.gateway.menu.menu_registry import MENU_BUTTON_SPECS


def test_menu_registry_root_slugs_count() -> None:
    slugs = menu_registry_root_slugs()
    assert len(slugs) == 8
    assert slugs[0] == "chat"


def test_config_paths_match_registry_labels() -> None:
    sections = iter_config_sections()
    assert len(sections) == 8
    root_labels = {
        spec.label
        for spec in MENU_BUTTON_SPECS
        if spec.section == "root" and spec.callback_pattern.startswith("^cfg:section:")
    }
    assert sections[0].label in root_labels


def test_section_callback_format() -> None:
    assert section_callback("voice") == "cfg:section:voice"


def test_chat_root_section_exists() -> None:
    chat = section_by_slug("chat")
    assert chat is not None
    assert chat.slug == "chat"


def test_legacy_session_slug_resolves_via_cli_alias() -> None:
    session = section_by_slug("session")
    assert session is not None
    assert session.slug == "chat"


def test_sevn_config_sections_lists_slugs() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "sections"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "chat" in result.stdout
    assert "help" in result.stdout


def test_sevn_config_sections_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "sections", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["data"]["sections"]) == 8


def test_sevn_config_no_args_shows_help_when_non_tty() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "sections" in result.stdout


def test_sevn_config_unknown_section_exit_2() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "not-a-section"])
    assert result.exit_code == 2
