"""Sectioned doctor framework tests (W2 — `specs/23-cli.md` §3)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.sections import SECTION_ORDER, section_for
from sevn.cli.json_util import CLI_JSON_SCHEMA_VERSION
from sevn.cli.render.console import configure_render
from sevn.onboarding.live_validate import ValidationCheck

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "cli" / "doctor_w0_golden_check_ids.json"


def _load_golden() -> dict[str, object]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _install_doctor_workspace(home: Path) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    (ws / ".llmignore").mkdir()


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

    async def _ok_probe(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="info",
            detail="sentinel _sevn_probe read ok",
            hint=None,
        )

    monkeypatch.setattr("sevn.cli.commands.doctor.probe_secrets_backend", _ok_probe)
    monkeypatch.setattr(
        "sevn.agent.runtimes.pyodide_deno.resolve_sandbox_exec_driver",
        lambda _cfg: "pyodide_deno",
    )
    monkeypatch.setattr(
        "sevn.agent.runtimes.pyodide_deno.effective_sandbox_exec_driver",
        lambda _cfg: "pyodide_deno",
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _reset_render() -> None:
    configure_render(json_mode=False, no_color=False, force_plain=False)
    yield
    configure_render(json_mode=False, no_color=False, force_plain=False)


def test_check_result_by_section_orders_canonical_sections() -> None:
    result = CheckResult()
    result.add(
        DoctorCheck("gateway_health", section_for("gateway_health"), "Gateway /health", True),
    )
    result.add(DoctorCheck("sevn_json", section_for("sevn_json"), "sevn.json", True))
    names = [name for name, _rows in result.by_section()]
    assert names.index("Workspace") < names.index("Gateway")


def test_doctor_json_envelope_matches_w0_golden_keys(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--json`` envelope keys and required check ids are W0-stable (additive-only)."""
    golden = _load_golden()
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code in (0, 4)
    payload = json.loads(result.stdout)
    assert set(payload.keys()) >= set(golden["envelope_keys"])
    assert payload["command"] == golden["command"]
    assert payload["schema_version"] == CLI_JSON_SCHEMA_VERSION
    data = payload["data"] if payload["ok"] else payload["details"]
    assert set(data.keys()) >= set(golden["data_keys"])
    ids = {row["id"] for row in data["checks"]}
    for check_id in golden["required_check_ids"]:
        assert check_id in ids
    for row in data["checks"]:
        assert set(row.keys()) >= {"id", "ok", "detail"}
        extra = set(row.keys()) - {"id", "ok", "detail"}
        assert extra <= set(golden.get("optional_check_row_keys", [])) | {"solution"}


def test_doctor_human_output_is_sectioned_plain(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

    result = runner.invoke(app, ["doctor"])
    assert "◆ Workspace" in result.stdout
    assert " ok · " in result.stdout
    assert "\x1b[" not in result.stdout


def test_doctor_strict_elevates_warnings_to_exit_4(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _install_doctor_workspace(home)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_doctor_network(monkeypatch)

    async def _warn_probe(**_kwargs: object) -> ValidationCheck:
        return ValidationCheck(
            check_id="secrets_backend",
            ok=True,
            severity="warn",
            detail="sentinel missing",
            hint="run sevn secrets set",
        )

    monkeypatch.setattr("sevn.cli.commands.doctor.probe_secrets_backend", _warn_probe)

    loose = runner.invoke(app, ["doctor", "--json"])
    assert loose.exit_code == 0

    strict = runner.invoke(app, ["doctor", "--json", "--strict"])
    assert strict.exit_code == 4
    payload = json.loads(strict.stdout)
    assert payload["ok"] is False
    assert payload["error_code"] == "DOCTOR_FAILED"


def test_doctor_checks_map_to_known_sections() -> None:
    golden = _load_golden()
    required = golden["required_check_ids"]
    assert isinstance(required, list)
    for check_id in required:
        assert section_for(str(check_id)) in SECTION_ORDER
