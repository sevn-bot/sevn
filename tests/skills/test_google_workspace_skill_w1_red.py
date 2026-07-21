"""PR #40 Google Workspace RED upgrades (green after W6)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from loguru import logger as loguru_logger

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


def _load_gws_bridge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gws_bridge_under_test", _GWS_BRIDGE)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    result = google_workspace_api.gmail_search(str(tmp_path), "is:unread", max_results=5)
    assert "parts" in called
    assert result == [] or isinstance(result, list)


def test_prefer_gws_fallback_logs_python_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.skills import google_workspace

    _write_workspace(tmp_path, prefer_gws=True)
    monkeypatch.setattr(google_workspace, "gws_binary", lambda: None)
    messages: list[str] = []
    sink_id = loguru_logger.add(lambda message: messages.append(str(message)), level="INFO")
    try:
        assert google_workspace.prefer_gws_enabled(tmp_path) is True
        assert google_workspace.use_gws_backend(tmp_path) is False
    finally:
        loguru_logger.remove(sink_id)
    assert any("Python backend" in line for line in messages)


def test_gws_bridge_subprocess_injects_token_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _GWS_BRIDGE.is_file()
    _write_workspace(tmp_path)
    monkeypatch.setenv("SEVN_WORKSPACE", str(tmp_path))
    mod = _load_gws_bridge()
    monkeypatch.setattr(mod, "gws_binary", lambda: "/usr/bin/gws")
    monkeypatch.setattr(mod, "get_valid_token_for_gws", lambda _ws: "tok-test")
    captured: dict[str, object] = {}

    def _fake_run(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = False,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["env"] = env
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    code = mod.main(["gmail", "list"])
    assert code == 0
    assert captured.get("command") == ["/usr/bin/gws", "gmail", "list"]
    env = captured.get("env")
    assert isinstance(env, dict)
    assert env.get("GOOGLE_WORKSPACE_CLI_TOKEN") == "tok-test"


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
    assert record.skill_dir.is_dir()
    assert (_GWS_BRIDGE).is_file()
    scripts = {entry.path for entry in record.manifest.scripts}
    assert "scripts/gws_bridge.py" in scripts
    assert "scripts/google_api.py" in scripts


def test_gmail_send_passes_raw_body_to_run_gws(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prefer_gws write path must forward the MIME raw body to run_gws."""
    _write_workspace(tmp_path, prefer_gws=True)
    google_workspace = pytest.importorskip("sevn.skills.google_workspace")
    google_workspace_api = pytest.importorskip("sevn.skills.google_workspace_api")

    monkeypatch.setattr(google_workspace, "gws_binary", lambda: "/usr/bin/gws")
    monkeypatch.setattr(google_workspace, "prefer_gws_enabled", lambda _ws: True)
    called: dict[str, object] = {}

    def _run_gws(
        workspace: Path,
        parts: list[str],
        *,
        params: object = None,
        body: object = None,
    ) -> dict[str, object]:
        called["parts"] = parts
        called["params"] = params
        called["body"] = body
        return {"id": "msg-1", "threadId": "thr-1"}

    monkeypatch.setattr(google_workspace, "run_gws", _run_gws)
    result = google_workspace_api.gmail_send(
        str(tmp_path),
        to="a@example.com",
        subject="hi",
        body="hello",
    )
    assert called.get("parts") == ["gmail", "users", "messages", "send"]
    body = called.get("body")
    assert isinstance(body, dict)
    raw = body.get("raw")
    assert isinstance(raw, str)
    assert raw
    assert result["status"] == "sent"
    assert result["id"] == "msg-1"


def test_drive_search_passes_query_params_to_run_gws(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prefer_gws list path must forward q/pageSize (not an unfiltered list)."""
    _write_workspace(tmp_path, prefer_gws=True)
    google_workspace = pytest.importorskip("sevn.skills.google_workspace")
    google_workspace_api = pytest.importorskip("sevn.skills.google_workspace_api")

    monkeypatch.setattr(google_workspace, "gws_binary", lambda: "/usr/bin/gws")
    monkeypatch.setattr(google_workspace, "prefer_gws_enabled", lambda _ws: True)
    called: dict[str, object] = {}

    def _run_gws(
        workspace: Path,
        parts: list[str],
        *,
        params: object = None,
        body: object = None,
    ) -> dict[str, object]:
        called["parts"] = parts
        called["params"] = params
        called["body"] = body
        return {"files": [{"id": "f1", "name": "x"}]}

    monkeypatch.setattr(google_workspace, "run_gws", _run_gws)
    result = google_workspace_api.drive_search(str(tmp_path), "invoice", max_results=3)
    params = called.get("params")
    assert isinstance(params, dict)
    assert params.get("q") == "fullText contains 'invoice'"
    assert params.get("pageSize") == 3
    assert called.get("body") is None
    assert result == [{"id": "f1", "name": "x"}]


def test_drive_download_skips_hollow_gws_metadata_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prefer_gws must not short-circuit download with files.get metadata."""
    import sys
    import types

    _write_workspace(tmp_path, prefer_gws=True)
    google_workspace = pytest.importorskip("sevn.skills.google_workspace")
    google_workspace_api = pytest.importorskip("sevn.skills.google_workspace_api")

    # Stub optional Google client so the download path can reach build_service.
    fake_http = types.ModuleType("googleapiclient.http")
    fake_http.MediaIoBaseDownload = object  # type: ignore[attr-defined]
    fake_root = types.ModuleType("googleapiclient")
    monkeypatch.setitem(sys.modules, "googleapiclient", fake_root)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", fake_http)

    monkeypatch.setattr(google_workspace, "gws_binary", lambda: "/usr/bin/gws")
    monkeypatch.setattr(google_workspace, "prefer_gws_enabled", lambda _ws: True)
    called = {"gws": False, "build": False}

    def _run_gws(*_a: object, **_k: object) -> dict[str, object]:
        called["gws"] = True
        return {"id": "fid", "name": "note.txt", "mimeType": "text/plain"}

    def _build(*_a: object, **_k: object) -> object:
        called["build"] = True
        raise RuntimeError("stop-after-build")

    monkeypatch.setattr(google_workspace, "run_gws", _run_gws)
    monkeypatch.setattr(google_workspace, "build_service", _build)
    with pytest.raises(RuntimeError, match="stop-after-build"):
        google_workspace_api.drive_download(str(tmp_path), "fid", output=tmp_path / "out.txt")
    assert called["gws"] is False
    assert called["build"] is True
