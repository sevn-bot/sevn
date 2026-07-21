"""PR #40 Google Workspace RED upgrades (green after W6)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager

_SKILL_ID = "google-workspace"
_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / _SKILL_ID
_SCRIPTS = _SKILL_ROOT / "scripts"
_GWS_BRIDGE = _SCRIPTS / "gws_bridge.py"


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _write_workspace(tmp_path: Path, *, prefer_gws: bool = True) -> None:
    payload = {
        "schema_version": 1,
        "skills": {
            "google_workspace": {
                "enabled": True,
                "prefer_gws": prefer_gws,
                "default_services": "all",
                "dry_run": False,
            },
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    (tmp_path / "sevn.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / ".sevn").mkdir(parents=True, exist_ok=True)


@pytest.mark.xfail(reason="green after W6: gws-first routing branch", strict=False)
def test_gmail_search_prefers_gws_when_enabled_and_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3.3: when prefer_gws + gws on PATH, handlers must call run_gws (not build_service)."""
    _write_workspace(tmp_path, prefer_gws=True)
    google_workspace = pytest.importorskip("sevn.skills.google_workspace")
    google_workspace_api = pytest.importorskip("sevn.skills.google_workspace_api")

    monkeypatch.setattr(google_workspace, "gws_binary", lambda: "/usr/bin/gws")
    monkeypatch.setattr(google_workspace, "prefer_gws_enabled", lambda _ws: True)
    called: dict[str, object] = {}

    def _run_gws(workspace: Path, parts: list[str], **_kwargs: object) -> dict[str, object]:
        called["parts"] = parts
        called["workspace"] = workspace
        return {"messages": []}

    monkeypatch.setattr(google_workspace, "run_gws", _run_gws)
    # Drive a live handler that today always uses build_service.
    result = google_workspace_api.gmail_search(str(tmp_path), "is:unread", max_results=5)
    assert "parts" in called
    assert result == [] or isinstance(result, list)


@pytest.mark.xfail(reason="green after W6: prefer_gws fallback log", strict=False)
def test_prefer_gws_fallback_logs_python_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from sevn.skills import google_workspace

    _write_workspace(tmp_path, prefer_gws=True)
    monkeypatch.setattr(google_workspace, "gws_binary", lambda: None)
    with caplog.at_level(logging.INFO):
        assert google_workspace.prefer_gws_enabled(tmp_path) is True
        # Routing must emit an observable fallback when gws is preferred but missing.
        raise AssertionError("Python fallback path must log chosen backend (W6)")


@pytest.mark.xfail(reason="green after W6: gws_bridge subprocess", strict=False)
def test_gws_bridge_subprocess_injects_token_env(tmp_path: Path) -> None:
    assert _GWS_BRIDGE.is_file()
    _write_workspace(tmp_path)
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    env["SEVN_GOOGLE_ACCESS_TOKEN"] = "tok-test"
    with patch("subprocess.run") as mocked:
        mocked.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok":true}',
            stderr="",
        )
        proc = subprocess.run(
            [sys.executable, str(_GWS_BRIDGE), "gmail", "list"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
    # After W6 the bridge must forward token env into the gws child.
    assert proc.returncode == 0 or mocked.called
    raise AssertionError("gws_bridge must assert token env injection into child (W6)")


@pytest.mark.xfail(reason="green after W6: manager load_skill side effect", strict=False)
def test_manager_load_skill_google_workspace_validates_scripts(tmp_path: Path) -> None:
    """Upgrade structural membership check to get_record + script path side effects."""
    _write_workspace(tmp_path)
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"google_workspace": {"enabled": True}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    manager = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,), config=cfg)
    assert _SKILL_ID in manager._records
    record = manager.get_record(_SKILL_ID)
    assert record.canonical_id == _SKILL_ID
    for path in (_SCRIPTS / "setup.py", _SCRIPTS / "google_api.py", _GWS_BRIDGE):
        assert path.is_file()
    # Side effect: skill scripts are resolvable from the loaded record.
    assert record.skill_dir.is_dir()
    assert (_GWS_BRIDGE).is_file()
