"""Remote SSH deploy orchestration tests (mocked ssh/scp)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.deploy.inventory import load_inventory
from sevn.deploy.remote import DeployMode, RemoteDeployRunner, validate_bundle
from sevn.deploy.report import DeployReport, build_report_dict, write_deploy_report
from sevn.deploy.ssh_runner import SSHResult, SSHRunner

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "deploy"


class _RecordingRunner(SSHRunner):
    """Capture planned ssh/scp commands without subprocess."""

    def run(
        self,
        argv,
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> SSHResult:
        cmd = tuple(str(part) for part in argv)
        self.planned_commands.append(cmd)
        return SSHResult(command=cmd, exit_code=0, stdout="ok", stderr="", duration_ms=1)


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_validate_bundle_parses_fixture() -> None:
    bundle_path = _FIXTURES / "sample-bundle.env"
    os.chmod(bundle_path, stat.S_IMODE(stat.S_IRUSR | stat.S_IWUSR))
    validated = validate_bundle(bundle_path)
    assert validated.bundle.bot_name == "Sevn"


def test_dry_run_plans_ssh_commands() -> None:
    bundle_path = _FIXTURES / "sample-bundle.env"
    os.chmod(bundle_path, stat.S_IMODE(stat.S_IRUSR | stat.S_IWUSR))
    inv = load_inventory(_FIXTURES / "inventory.toml")
    deploy = RemoteDeployRunner(
        inventory=inv,
        host_id="staging",
        mode=DeployMode.DRY_RUN,
        bundle_path=bundle_path,
    )
    recording = _RecordingRunner(host=deploy._host, dry_run=True)
    with patch.object(deploy, "_runner", recording):
        report = deploy.run()
    assert report.mode == "dry-run"
    assert any(step["id"] == "scp_bundle" for step in report.steps)
    assert recording.planned_commands


def test_check_mode_calls_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    inv = load_inventory(_FIXTURES / "inventory.toml")
    deploy = RemoteDeployRunner(
        inventory=inv,
        host_id="staging",
        mode=DeployMode.CHECK,
    )
    recording = _RecordingRunner(host=deploy._host, dry_run=False)

    def _fake_run(self, argv, *, check=True, input_text=None):
        return recording.run(argv, check=check, input_text=input_text)

    monkeypatch.setattr(SSHRunner, "run", _fake_run)
    report = deploy.run()
    assert report.mode == "check"
    assert report.steps[0]["id"] == "preflight"


def test_deploy_check_cli_missing_inventory(runner: ClickCliRunner) -> None:
    result = runner.invoke(
        get_command(app),
        ["deploy", "check", "--host", "staging", "--inventory", "/nonexistent/inventory.toml"],
    )
    assert result.exit_code == 2
    assert "not found" in result.stderr


def test_deploy_dry_run_cli(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports = tmp_path / "reports"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        get_command(app),
        [
            "deploy",
            "remote",
            "--host",
            "staging",
            "--bundle",
            str(_FIXTURES / "sample-bundle.env"),
            "--inventory",
            str(_FIXTURES / "inventory.toml"),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "dry-run plan" in result.stdout
    assert list(reports.glob("remote-deploy-*.json"))


def test_report_schema_fixture() -> None:
    payload = build_report_dict(
        DeployReport(
            host_id="staging",
            bundle_path="sample.env",
            bot_name="Sevn",
            mode="dry-run",
        )
    )
    assert payload["schema_version"] == 1
    fixture = (_FIXTURES / "remote-deploy-check.json").read_text(encoding="utf-8")
    assert '"schema_version": 1' in fixture


def test_write_deploy_report(tmp_path: Path) -> None:
    path = write_deploy_report(
        DeployReport(
            host_id="staging",
            bundle_path="b.env",
            bot_name="Sevn",
            mode="check",
        ),
        reports_dir=tmp_path,
    )
    assert path.exists()
