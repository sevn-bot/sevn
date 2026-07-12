"""``sevn telegram-test`` Typer entry (`specs/23-cli.md` §2.11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.commands import telegram_test as tg_mod


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_telegram_test_list_prints_session(runner: ClickCliRunner) -> None:
    result = runner.invoke(get_command(app), ["telegram-test", "list"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "session"


def test_telegram_test_run_unknown_suite_exit2(runner: ClickCliRunner) -> None:
    result = runner.invoke(
        get_command(app),
        ["telegram-test", "run", "unknown", "--target", "local"],
    )
    assert result.exit_code == 2
    assert "unknown suite" in result.stderr


def test_telegram_test_run_invokes_runner(
    runner: ClickCliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(tg_mod, "_run_tester", fake_run)
    result = runner.invoke(
        get_command(app),
        ["telegram-test", "run", "session", "--target", "local", "--json"],
    )
    assert result.exit_code == 0
    assert captured
    argv = captured[0]
    assert "run" in argv
    assert "session" in argv
    assert "--target" in argv
    assert "local" in argv
    assert "--json" in argv


def test_telegram_test_run_forwards_headless_flag(
    runner: ClickCliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(tg_mod, "_run_tester", fake_run)
    result = runner.invoke(
        get_command(app),
        ["telegram-test", "run", "session", "--target", "prod", "--headless"],
    )
    assert result.exit_code == 0
    assert "--headless" in captured[0]


def test_telegram_test_run_propagates_needs_login_exit7(
    runner: ClickCliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tg_mod, "_run_tester", lambda _argv: tg_mod.NEEDS_LOGIN_EXIT_CODE)
    result = runner.invoke(
        get_command(app),
        ["telegram-test", "run", "session", "--target", "local"],
    )
    assert result.exit_code == 7


def test_telegram_test_login_invokes_runner(
    runner: ClickCliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_run(argv: list[str]) -> int:
        captured.append(argv)
        return 0

    monkeypatch.setattr(tg_mod, "_run_tester", fake_run)
    result = runner.invoke(get_command(app), ["telegram-test", "login"])
    assert result.exit_code == 0
    assert captured[0][-1] == "login"


def test_telegram_test_status_empty_artifacts_exit4(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tmp_path / "artifacts"
    empty.mkdir()
    monkeypatch.setattr(tg_mod, "_artifacts_dir", lambda: empty)
    result = runner.invoke(get_command(app), ["telegram-test", "status"])
    assert result.exit_code == 4
    assert "no telegram-test runs" in result.stderr


def test_telegram_test_status_summarizes_latest_report(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    report = {
        "suite": "session",
        "target": "local",
        "deployment_id_observed": "dep-abc",
        "tests": [
            {"name": "a", "status": "passed"},
            {"name": "b", "status": "failed"},
            {"name": "c", "status": "skipped"},
        ],
    }
    (artifacts / "session-latest.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(tg_mod, "_artifacts_dir", lambda: artifacts)
    result = runner.invoke(get_command(app), ["telegram-test", "status"])
    assert result.exit_code == 0
    assert "session" in result.stdout
    assert "1 passed, 1 failed, 1 skipped" in result.stdout
    assert "dep-abc" in result.stdout


def test_telegram_test_status_json_prints_raw_report(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    payload = {"suite": "session", "target": "prod", "tests": []}
    (artifacts / "session-latest.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(tg_mod, "_artifacts_dir", lambda: artifacts)
    result = runner.invoke(get_command(app), ["telegram-test", "status", "--json"])
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["target"] == "prod"


def test_telegram_test_missing_package_exit4(
    runner: ClickCliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> None:
        typer.secho("missing", err=True)
        raise typer.Exit(4)

    monkeypatch.setattr(tg_mod, "_require_tester_package", boom)
    result = runner.invoke(get_command(app), ["telegram-test", "login"])
    assert result.exit_code == 4
