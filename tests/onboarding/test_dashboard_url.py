"""Onboarding ``web_ui.url`` for Mission Control (`specs/24-dashboard.md` MC-13)."""

from __future__ import annotations

from sevn.config.workspace_config import WorkspaceConfig
from sevn.onboarding.dashboard_url import (
    apply_web_ui_url_for_dashboard,
    mission_control_entry_url,
)


def test_apply_web_ui_url_when_dashboard_enabled() -> None:
    doc = {
        "schema_version": 1,
        "gateway": {
            "host": "127.0.0.1",
            "port": 3002,
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "dashboard": {"enabled": True},
    }
    apply_web_ui_url_for_dashboard(doc)
    assert doc["web_ui"]["url"] == "http://127.0.0.1:3002"


def test_apply_web_ui_url_skips_when_disabled() -> None:
    doc = {
        "schema_version": 1,
        "gateway": {"port": 3001, "token": "${SECRET:keychain:sevn.gateway.token}"},
        "dashboard": {"enabled": False},
    }
    apply_web_ui_url_for_dashboard(doc)
    assert "web_ui" not in doc


def test_apply_web_ui_url_preserves_existing() -> None:
    doc = {
        "schema_version": 1,
        "dashboard": {"enabled": True},
        "web_ui": {"url": "https://custom.example/"},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    apply_web_ui_url_for_dashboard(doc)
    assert doc["web_ui"]["url"] == "https://custom.example/"


def test_mission_control_entry_url_default() -> None:
    assert mission_control_entry_url(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        )
    ) == ("http://127.0.0.1:3001/mission/")
