"""Tests for Google Workspace doctor warnings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.workspace_config import WorkspaceConfig

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
from sevn.skills.google_workspace_doctor_check import probe_google_workspace_skill_warnings


def test_probe_skips_when_skill_disabled(tmp_path: Path) -> None:
    """No warnings when ``skills.google_workspace.enabled`` is false."""

    cfg = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "t"},
        skills={"google_workspace": {"enabled": False}},
    )
    assert probe_google_workspace_skill_warnings(cfg, content_root=tmp_path) == []


def test_probe_reports_requested_warnings(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Enabled skill reports token, gws, and optional-deps warnings."""

    cfg = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "t"},
        skills={"google_workspace": {"enabled": True, "prefer_gws": True}},
    )
    monkeypatch.setattr("sevn.skills.google_workspace_doctor_check.gws_binary", lambda: None)

    def _missing_google_deps() -> None:
        raise ImportError("optional deps missing")

    monkeypatch.setattr(
        "sevn.skills.google_workspace_doctor_check.ensure_google_deps",
        _missing_google_deps,
    )

    warnings = probe_google_workspace_skill_warnings(cfg, content_root=tmp_path)

    assert len(warnings) == 3
    assert "token missing" in warnings[0]
    assert "prefer_gws=true but gws is not on PATH" in warnings[1]
    assert "optional deps not installed" in warnings[2]


def test_probe_returns_no_warnings_when_ready(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ready skill configuration returns no warnings."""

    cfg = WorkspaceConfig(
        schema_version=1,
        gateway={"token": "t"},
        skills={"google_workspace": {"enabled": True, "prefer_gws": False}},
    )
    token_file = tmp_path / ".sevn" / "google_token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sevn.skills.google_workspace_doctor_check.ensure_google_deps",
        lambda: None,
    )

    assert probe_google_workspace_skill_warnings(cfg, content_root=tmp_path) == []
