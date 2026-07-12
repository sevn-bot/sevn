"""``sevn doctor`` browser readiness probe."""

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


def _install_workspace(home: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "skills": {"browser": {"engine": "brave"}},
            },
        ),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_doctor_browser_readiness_reports_brave(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor emits browser_readiness with resolved Brave binary."""
    home = tmp_path / "home"
    _install_workspace(home)
    brave_bin = tmp_path / "brave-browser"
    brave_bin.write_text("", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_CHROME_EXECUTABLE", str(brave_bin))

    def _which(name: str) -> str | None:
        if name == "docker":
            return "/usr/bin/docker"
        if name == "playwright":
            return "/usr/local/bin/playwright"
        return None

    monkeypatch.setattr(
        "sevn.skills.browser_session.cdp_reachable",
        lambda *_a, **_k: False,
    )
    _patch_doctor_network(monkeypatch, which=_which)

    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    checks = {row["id"]: row for row in payload["details"]["checks"]}
    readiness = checks["browser_readiness"]
    assert readiness["ok"] is True
    assert "Brave" in readiness["detail"]
    assert str(brave_bin) in readiness["detail"]


def test_doctor_browser_readiness_warns_without_binary_forced_headless(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing binary is a warning even when headless mode is forced."""
    home = tmp_path / "home"
    _install_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.delenv("SEVN_CHROME_EXECUTABLE", raising=False)

    def _which(name: str) -> str | None:
        if name == "docker":
            return "/usr/bin/docker"
        if name == "playwright":
            return "/usr/local/bin/playwright"
        return None

    monkeypatch.setattr(
        "sevn.skills.browser_session.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "sevn.skills.browser_session.cdp_reachable",
        lambda *_a, **_k: False,
    )
    _patch_doctor_network(monkeypatch, which=_which)

    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    checks = {row["id"]: row for row in payload["details"]["checks"]}
    readiness = checks["browser_readiness"]
    assert readiness["ok"] is False
    assert readiness["severity"] == "warn"
    warnings = payload["details"].get("warnings", [])
    assert any("no browser binary resolved" in str(w) for w in warnings)
