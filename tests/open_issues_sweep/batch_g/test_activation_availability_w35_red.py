"""W35.3 — availability verdict, not a crash (#102 → W36, D25).

Absent hardware, missing optional extra, and unsupported platforms must yield a
structured **unavailable** verdict — never a gateway/doctor crash.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    activation_enabled_workspace_doc,
    import_voice_activation_module,
)
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.config.workspace_config import parse_workspace_config


def _assert_unavailable_verdict(verdict: dict[str, Any]) -> None:
    assert verdict.get("available") is False
    assert verdict.get("status") in {"unavailable", "disabled"}
    reason = str(verdict.get("reason") or verdict.get("detail") or "").strip()
    assert reason, "unavailable verdict must include a human-readable reason"


@pytest.mark.xfail(reason="green after W36: probe_voice_activation extra missing", strict=False)
def test_probe_voice_activation_extra_missing() -> None:
    activation = import_voice_activation_module()
    ws = parse_workspace_config(activation_enabled_workspace_doc(enabled=True))
    with patch("importlib.util.find_spec", return_value=None):
        verdict = activation.probe_voice_activation(ws)
    _assert_unavailable_verdict(verdict)
    assert "extra" in str(verdict.get("reason") or verdict.get("detail") or "").lower()


@pytest.mark.xfail(reason="green after W36: probe_voice_activation no input device", strict=False)
def test_probe_voice_activation_no_input_device() -> None:
    activation = import_voice_activation_module()
    ws = parse_workspace_config(activation_enabled_workspace_doc(enabled=True))
    with (
        patch("importlib.util.find_spec", return_value=object()),
        patch.object(activation, "has_input_device", return_value=False, create=True),
    ):
        verdict = activation.probe_voice_activation(ws)
    _assert_unavailable_verdict(verdict)
    assert "device" in str(verdict.get("reason") or verdict.get("detail") or "").lower()


@pytest.mark.xfail(
    reason="green after W36: probe_voice_activation unsupported platform", strict=False
)
def test_probe_voice_activation_unsupported_platform() -> None:
    activation = import_voice_activation_module()
    ws = parse_workspace_config(activation_enabled_workspace_doc(enabled=True))
    with (
        patch("importlib.util.find_spec", return_value=object()),
        patch.object(activation, "has_input_device", return_value=True, create=True),
        patch.object(activation, "activation_supported_platform", return_value=False, create=True),
    ):
        verdict = activation.probe_voice_activation(ws)
    _assert_unavailable_verdict(verdict)
    assert "platform" in str(verdict.get("reason") or verdict.get("detail") or "").lower()


@pytest.mark.xfail(reason="green after W36: doctor voice_activation probe", strict=False)
def test_sevn_doctor_reports_activation_unavailable_without_failing_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import_voice_activation_module()
    home = tmp_path / "home"
    ws_dir = home / "workspace"
    ws_dir.mkdir(parents=True)
    doc = activation_enabled_workspace_doc(enabled=True)
    (ws_dir / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    (ws_dir / ".llmignore").mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "batch-g-gw-token")
    monkeypatch.chdir(ws_dir)

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self) -> dict[str, object]:
            return {"status": "ok", "ready": True}

    monkeypatch.setattr("sevn.cli.commands.doctor.gateway_get", lambda _path, **_kw: _Resp())
    monkeypatch.setattr("sevn.cli.commands.doctor.shutil.which", lambda _n: None)
    monkeypatch.setattr(
        "sevn.cli.commands.doctor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"", b""),
    )
    monkeypatch.setattr("sevn.cli.commands.doctor.proxy_healthz_get", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "sevn.code_understanding.bootstrap.code_orientation_doctor_checks",
        lambda *_a, **_k: [],
    )

    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--json"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    checks = data.get("checks") or []
    activation_checks = [c for c in checks if c.get("id") == "voice_activation"]
    assert activation_checks, "doctor must expose voice_activation check (D25)"
    row = activation_checks[0]
    assert row.get("ok") is False or row.get("severity") in {"warn", "info"}
    assert str(row.get("detail") or "").strip()
