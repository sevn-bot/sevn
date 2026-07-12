"""``sevn doctor`` secrets_backend probe (`specs/23-cli.md` §3)."""

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
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
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


def test_doctor_no_cli_import_warning(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy probe does not emit the legacy CLI-import stub warning."""
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

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
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    warnings = payload["data"]["warnings"]
    assert not any("CLI does not import" in w for w in warnings)
    sb = next(c for c in payload["data"]["checks"] if c["id"] == "secrets_backend")
    assert sb["ok"] is True
    assert sb.get("severity") is None
    assert "sentinel _sevn_probe read ok" in sb["detail"]


def test_doctor_secrets_sentinel_miss_warns(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reachable backend without sentinel surfaces a single actionable warning."""
    home = tmp_path / "home2"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

    async def _miss_probe(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="warn",
            detail="sentinel _sevn_probe not set (backend reachable)",
            hint="store a probe value with `sevn secrets put` (`specs/06-secrets.md`)",
        )

    monkeypatch.setattr("sevn.cli.commands.doctor.probe_secrets_backend", _miss_probe)
    monkeypatch.setattr(
        "sevn.code_understanding.bootstrap.code_orientation_doctor_checks",
        lambda *_a, **_k: [],
    )
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    sb = next(c for c in payload["data"]["checks"] if c["id"] == "secrets_backend")
    assert sb["ok"] is True
    assert sb["severity"] == "warn"
    warnings = payload["data"]["warnings"]
    assert len(warnings) >= 1
    assert any("sevn secrets put" in w for w in warnings)


def test_doctor_secrets_strict_error_fails(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Encrypted-file workspaces treat backend errors as doctor failures."""
    home = tmp_path / "home3"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "secrets_backend": {
                    "encrypted_file": {"path": ".sevn/secrets/store.enc"},
                    "chain": [{"type": "encrypted_file", "path": ".sevn/secrets/store.enc"}],
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

    async def _fail_probe(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=False,
            severity="error",
            detail="backend error: corrupt store",
            hint="check secrets_backend chain (`specs/06-secrets.md`)",
        )

    monkeypatch.setattr("sevn.cli.commands.doctor.probe_secrets_backend", _fail_probe)
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "secrets_backend" in payload["message"]
