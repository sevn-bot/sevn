"""``sevn doctor`` optional ``browser_extra`` probe (``specs/23-cli.md`` §3)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sevn.cli.app import app


def _patch_doctor_network(
    monkeypatch: pytest.MonkeyPatch,
    *,
    which: Callable[[str], str | None],
) -> None:
    class _Resp:
        def __init__(self, text: str = "{}") -> None:
            self.text = text
            self.status_code = 200
            self.headers = {"content-type": "application/json"}

        def json(self) -> dict[str, object]:
            return json.loads(self.text)

    def _gateway_get(path: str, **_kwargs: object) -> _Resp:
        if path == "/health":
            return _Resp('{"status":"ok"}')
        if path == "/ready":
            return _Resp('{"ready":true}')
        msg = f"unexpected path {path}"
        raise ValueError(msg)

    monkeypatch.setattr("sevn.cli.commands.doctor.gateway_get", _gateway_get)
    monkeypatch.setattr("sevn.cli.commands.doctor.shutil.which", which)
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"", b""),
    )
    monkeypatch.setattr(
        "sevn.code_understanding.bootstrap.code_orientation_doctor_checks",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.proxy_healthz_get",
        lambda *_a, **_k: httpx.Response(200),
    )


def _install_legacy_workspace(home: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps({"schema_version": 1, "workspace_root": "."}),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_browser_extra_ok_when_playwright_on_path(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Playwright is on PATH, ``browser_extra`` is ok with no install warning."""
    home = tmp_path / "home"
    _install_legacy_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    def _which(name: str) -> str | None:
        if name == "docker":
            return "/usr/bin/docker"
        if name == "playwright":
            return "/usr/local/bin/playwright"
        return None

    _patch_doctor_network(monkeypatch, which=_which)

    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    checks = {row["id"]: row for row in payload["details"]["checks"]}
    browser = checks["browser_extra"]
    assert browser["ok"] is True
    assert browser["detail"] == "/usr/local/bin/playwright"
    warnings = payload["details"].get("warnings", [])
    assert not any("--extra browser" in str(w) for w in warnings)


def test_browser_extra_warns_when_playwright_missing(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Playwright is absent, ``browser_extra`` stays ok but emits a warning."""
    home = tmp_path / "home"
    _install_legacy_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))

    def _which(name: str) -> str | None:
        if name == "docker":
            return "/usr/bin/docker"
        return None

    _patch_doctor_network(monkeypatch, which=_which)

    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    checks = {row["id"]: row for row in payload["details"]["checks"]}
    browser = checks["browser_extra"]
    assert browser["ok"] is True
    assert "--extra browser" in browser["detail"]
    warnings = payload["details"].get("warnings", [])
    assert any("--extra browser" in str(w) for w in warnings)
