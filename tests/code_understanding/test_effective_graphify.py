"""Tests for install-preset Graphify settings."""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.effective_settings import (
    effective_graphify_settings,
    graphify_enabled_for_checkout,
)
from sevn.config.workspace_config import MySevnWorkspaceConfig, WorkspaceConfig


def _write_sevn_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")


def test_graphify_enabled_when_my_sevn_and_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_sevn_repo(repo)
    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert graphify_enabled_for_checkout(ws, repo)
    settings = effective_graphify_settings(ws, repo)
    assert settings.enabled is True


def test_graphify_stays_off_without_checkout() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        my_sevn=MySevnWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert not graphify_enabled_for_checkout(ws, None)
    assert effective_graphify_settings(ws, None).enabled is False
