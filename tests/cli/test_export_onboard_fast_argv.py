"""Argv parsing for ``sevn export-secrets`` and ``sevn onboard fast``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.onboarding.export_bundle import ExportBundleError, ExportResult
from sevn.onboarding.fast_onboard import FastOnboardResult


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_export_secrets_invokes_runner(runner: ClickCliRunner, tmp_path: Path) -> None:
    """``export-secrets <ws> --to-file f`` calls the exporter and reports the count."""
    out = tmp_path / "bundle.env"
    fake = ExportResult(path=out, secret_count=2, bot_name="Luluu")
    with patch(
        "sevn.cli.commands.export_secrets_cmd.run_export_secrets",
        new=AsyncMock(return_value=fake),
    ) as mock:
        result = runner.invoke(
            get_command(app),
            ["export-secrets", str(tmp_path / "ws"), "--to-file", str(out)],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "2 secret(s)" in result.stdout
    assert "Luluu" in result.stdout
    kwargs = mock.call_args.kwargs
    assert kwargs["workspace_root"] == tmp_path / "ws"
    assert kwargs["to_file"] == out
    assert kwargs["force"] is False


def test_export_secrets_maps_error_exit_code(runner: ClickCliRunner, tmp_path: Path) -> None:
    """An ``ExportBundleError`` maps to its carried exit code."""
    with patch(
        "sevn.cli.commands.export_secrets_cmd.run_export_secrets",
        new=AsyncMock(side_effect=ExportBundleError("locked", exit_code=3)),
    ):
        result = runner.invoke(
            get_command(app),
            ["export-secrets", str(tmp_path / "ws"), "--to-file", str(tmp_path / "x.env")],
        )
    assert result.exit_code == 3
    assert "locked" in result.stderr + result.stdout


def test_export_secrets_requires_to_file(runner: ClickCliRunner, tmp_path: Path) -> None:
    """``--to-file`` is mandatory."""
    result = runner.invoke(get_command(app), ["export-secrets", str(tmp_path / "ws")])
    assert result.exit_code == 2


def test_export_secrets_warns_on_unignored_path(runner: ClickCliRunner, tmp_path: Path) -> None:
    """When export reports an unignored git path, stderr nudges ``.gitignore`` and exits 0."""
    out = tmp_path / "bundle.env"
    fake = ExportResult(
        path=out,
        secret_count=1,
        bot_name="Luluu",
        git_unignored_warning=True,
    )
    with patch(
        "sevn.cli.commands.export_secrets_cmd.run_export_secrets",
        new=AsyncMock(return_value=fake),
    ):
        result = runner.invoke(
            get_command(app),
            ["export-secrets", str(tmp_path / "ws"), "--to-file", str(out)],
        )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "not gitignored" in result.stderr
    assert ".gitignore" in result.stderr


def test_onboard_fast_dispatches_with_seed_secrets(
    runner: ClickCliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``onboard fast <file>`` parses the bundle and seeds secrets into onboarding."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    export = tmp_path / "bundle.env"
    export.write_text(
        "SEVN_EXPORT_VERSION=1\n"
        "SEVN_BOT_NAME=Nova\n"
        "SEVN_SECRET_MINIMAX=k\n"
        "config.schema_version=1\n"
        "config.agent.display_name=Nova\n",
        encoding="utf-8",
    )
    fake = FastOnboardResult(
        sevn_json_path=home / "workspace" / "sevn.json",
        seeded_paths=(),
        daemon_install_line=None,
        pdf_native_install_line=None,
        services_restart=None,
    )
    with patch(
        "sevn.cli.commands.onboard.run_fast_onboard",
        new=AsyncMock(return_value=fake),
    ) as mock:
        result = runner.invoke(get_command(app), ["onboard", "fast", str(export)])
    assert result.exit_code == 0, result.stdout + result.stderr
    kwargs = mock.call_args.kwargs
    assert kwargs["bot_name"] == "Nova"
    assert kwargs["prompt_for_bot_name"] is False
    assert kwargs["seed_secrets"] == {"SEVN_SECRET_MINIMAX": "k"}


def test_onboard_fast_missing_file_errors(runner: ClickCliRunner) -> None:
    """``onboard fast`` without a path is a usage error."""
    result = runner.invoke(get_command(app), ["onboard", "fast"])
    assert result.exit_code == 2


def test_onboard_fast_unreadable_file_errors(runner: ClickCliRunner, tmp_path: Path) -> None:
    """A missing export file is a precondition failure (exit 4)."""
    result = runner.invoke(get_command(app), ["onboard", "fast", str(tmp_path / "absent.env")])
    assert result.exit_code == 4


def test_onboard_rejects_extra_positional(runner: ClickCliRunner, tmp_path: Path) -> None:
    """A non-``fast`` second positional is rejected (no silent drop)."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    result = runner.invoke(get_command(app), ["onboard", str(cfg), str(tmp_path / "extra.json")])
    assert result.exit_code == 2
