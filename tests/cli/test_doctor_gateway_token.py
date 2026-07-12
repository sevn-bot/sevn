"""``sevn doctor`` tolerates legacy workspaces missing ``gateway.token``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sevn.cli.app import app


def _patch_doctor_network(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.shutil.which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
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


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_doctor_runs_on_legacy_tokenless_sevn_json(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor reports gateway_token_configured FAIL but does not abort early."""
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps({"schema_version": 1, "workspace_root": "."}),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    checks = {row["id"]: row for row in payload["details"]["checks"]}
    assert checks["sevn_json"]["ok"] is True
    assert checks["gateway_token_configured"]["ok"] is False
    assert "secrets_backend" in checks
