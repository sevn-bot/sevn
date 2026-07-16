"""Bundled ``google-workspace`` skill registration and script tests."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager
from sevn.skills.manifest import parse_skill_markdown

_SKILL_ID = "google-workspace"
_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / _SKILL_ID
_SKILL_MD = _SKILL_ROOT / "SKILL.md"
_SCRIPTS = _SKILL_ROOT / "scripts"
_SETUP_SCRIPT = _SCRIPTS / "setup.py"
_API_SCRIPT = _SCRIPTS / "google_api.py"
_EXPECTED_EGRESS = {
    "gmail.googleapis.com",
    "www.googleapis.com",
    "oauth2.googleapis.com",
    "people.googleapis.com",
    "sheets.googleapis.com",
    "docs.googleapis.com",
    "drive.googleapis.com",
    "calendar.googleapis.com",
}


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    """Isolate ``SkillsManager.shared()`` across tests."""
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _write_workspace(tmp_path: Path) -> None:
    """Write a minimal workspace config for skill-script tests."""
    payload = {
        "schema_version": 1,
        "skills": {
            "google_workspace": {
                "enabled": True,
                "prefer_gws": True,
                "default_services": "all",
                "dry_run": False,
            },
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    (tmp_path / "sevn.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / ".sevn").mkdir(parents=True, exist_ok=True)


def _require_script(path: Path) -> None:
    """Skip script-bound tests when the bundled wrapper is absent."""
    if not path.is_file():
        pytest.skip(f"bundled script not present: {path.name}")


def _run_script(
    script: Path,
    workspace: Path,
    cli_args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run one bundled script in a subprocess and parse its JSON envelope."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(script), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def _run_script_main(
    script: Path,
    workspace: Path,
    cli_args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, object]]:
    """Run a bundled skill script ``main()`` in-process."""
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))
    if extra_env:
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(f"google_workspace_{script.stem}", script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.main(cli_args)
    payload = json.loads(buf.getvalue().strip() or "{}")
    return code, payload


def test_bundled_skill_manifest_exists() -> None:
    """Manifest exists, declares expected egress, and marks write-capable wrappers non-abortable."""
    assert _SKILL_MD.is_file()
    text = _SKILL_MD.read_text(encoding="utf-8")
    manifest = parse_skill_markdown(_SKILL_MD.read_text(encoding="utf-8"), "core")
    assert manifest.name == _SKILL_ID
    for domain in _EXPECTED_EGRESS:
        assert f"  - {domain}" in text
    scripts = {entry.path: entry for entry in manifest.scripts}
    assert scripts["scripts/setup.py"].abortable is False
    assert scripts["scripts/google_api.py"].abortable is False


def test_manager_registers_google_workspace(tmp_path: Path) -> None:
    """The bundled skill loads through ``SkillsManager`` without path validation failures."""
    manager = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert _SKILL_ID in manager._records


def test_setup_check_returns_not_authenticated_without_token(tmp_path: Path) -> None:
    """``setup.py --check`` reports ``NOT_AUTHENTICATED`` when no token file exists."""
    _require_script(_SETUP_SCRIPT)
    _write_workspace(tmp_path)
    code, payload = _run_script(
        _SETUP_SCRIPT,
        tmp_path,
        ["--check"],
        extra_env={"SEVN_GOOGLE_TOKEN_PATH": str(tmp_path / ".sevn" / "missing_google_token.json")},
    )
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "NOT_AUTHENTICATED"


def test_gmail_search_dry_run_returns_plan_envelope(tmp_path: Path) -> None:
    """``google_api.py gmail search --dry-run`` plans work without importing Google deps."""
    _require_script(_API_SCRIPT)
    _write_workspace(tmp_path)
    code, payload = _run_script(
        _API_SCRIPT,
        tmp_path,
        ["gmail", "search", "is:unread", "--max", "10", "--dry-run"],
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("service") == "gmail"
    assert data.get("operation") == "search"
    assert data.get("query") == "is:unread"


def test_gmail_search_uses_mocked_api_function(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-process ``gmail search`` can be driven by a mocked runtime helper."""
    _require_script(_API_SCRIPT)
    _write_workspace(tmp_path)

    captured: dict[str, object] = {}
    fake_module = types.ModuleType("sevn.skills.google_workspace")

    def _gmail_search(query: str, *, max_results: int) -> list[dict[str, object]]:
        captured["query"] = query
        captured["max_results"] = max_results
        return [
            {
                "id": "msg-1",
                "threadId": "thread-1",
                "from": "sender@example.com",
                "to": "me@example.com",
                "subject": "Status update",
                "date": "2026-07-16T18:00:00Z",
                "snippet": "Preview text",
                "labels": ["UNREAD"],
            },
        ]

    fake_module.gmail_search = _gmail_search  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sevn.skills.google_workspace", fake_module)

    code, payload = _run_script_main(
        _API_SCRIPT,
        tmp_path,
        ["gmail", "search", "label:unread", "--max", "7"],
        monkeypatch=monkeypatch,
    )
    assert code == 0
    assert captured == {"query": "label:unread", "max_results": 7}
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "live"
    assert data.get("count") == 1
    messages = data.get("messages")
    assert isinstance(messages, list)
    assert messages[0]["id"] == "msg-1"
