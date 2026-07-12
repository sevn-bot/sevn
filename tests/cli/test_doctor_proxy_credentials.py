"""``sevn doctor`` proxy LLM credentials probe when healthz succeeds (`specs/23-cli.md` §3)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.onboarding.live_validate import ValidationCheck


class _FakeGatewayResponse:
    """Minimal httpx-like response for patched ``gateway_get``."""

    def __init__(
        self,
        *,
        text: str = "{}",
        status_code: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def json(self) -> dict[str, Any]:
        return json.loads(self.text)


def _install_doctor_workspace(home: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "llm": {"main_model": "openai/gpt-test"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()


def _patch_doctor_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _gateway_get(path: str, **_kwargs: object) -> _FakeGatewayResponse:
        if path == "/health":
            return _FakeGatewayResponse(text='{"status":"ok"}')
        if path == "/ready":
            return _FakeGatewayResponse(text='{"ready":true,"sqlite":true}')
        msg = f"unexpected path {path}"
        raise ValueError(msg)

    monkeypatch.setattr("sevn.cli.commands.doctor.gateway_get", _gateway_get)
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"", b""),
    )
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.proxy_healthz_get",
        lambda *_a, **_k: httpx.Response(200),
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_doctor_probes_proxy_from_workspace_when_env_unset(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor resolves proxy origin from workspace (default port) without SEVN_PROXY_URL."""
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.delenv("SEVN_PROXY_URL", raising=False)
    _patch_doctor_network(monkeypatch)

    probed: list[str] = []

    def _healthz(origin: str, **_kwargs: object) -> httpx.Response:
        probed.append(origin)
        return httpx.Response(200)

    monkeypatch.setattr("sevn.cli.commands.doctor.proxy_healthz_get", _healthz)

    async def _ok_probe(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="info",
            detail="sentinel _sevn_probe read ok",
            hint=None,
        )

    monkeypatch.setattr("sevn.cli.commands.doctor.probe_secrets_backend", _ok_probe)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    assert probed == ["http://127.0.0.1:8787"]
    payload = json.loads(result.stdout)
    proxy_rows = [c for c in payload["data"]["checks"] if c["id"] == "proxy_healthz"]
    assert proxy_rows
    assert proxy_rows[0]["ok"] is True
    assert "8787" in proxy_rows[0]["detail"]


def test_doctor_fails_when_proxy_health_ok_but_llm_503(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_PROXY_URL", "http://127.0.0.1:8787")
    _patch_doctor_network(monkeypatch)

    async def _ok_probe(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="info",
            detail="sentinel _sevn_probe read ok",
            hint=None,
        )

    async def _llm_503(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="llm_reachability",
            ok=False,
            severity="error",
            detail="proxy LLM route returned 503 (provider credentials not loaded on proxy)",
            hint="restart proxy",
        )

    monkeypatch.setattr("sevn.cli.commands.doctor.probe_secrets_backend", _ok_probe)
    monkeypatch.setattr("sevn.cli.commands.doctor.probe_llm_reachability", _llm_503)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    checks = payload["details"]["checks"]
    llm_rows = [c for c in checks if c["id"] == "llm_reachability"]
    assert llm_rows
    assert llm_rows[0]["ok"] is False
