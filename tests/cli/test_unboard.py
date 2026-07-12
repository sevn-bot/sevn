"""``sevn unboard`` operator teardown (`specs/23-cli.md` §2.5.1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.commands.unboard import discover_operator_home_paths, resolve_source_root, run_unboard
from sevn.cli.operator_lock import OperatorLockHeld

_ALIAS_NOTICE = "use sevn unboard"


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _install_operator_home(base: Path, *, name: str = ".sevn") -> Path:
    home = base / name
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
        encoding="utf-8",
    )
    return home


@pytest.fixture(autouse=True)
def _reset_cli_log_sink() -> None:
    from sevn.cli.cli_activity_log import shutdown_cli_activity_log

    shutdown_cli_activity_log()
    yield
    shutdown_cli_activity_log()


def test_unboard_yes_removes_operator_home(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_operator_home(tmp_path)
    monkeypatch.setenv("SEVN_HOME", str(home))
    with (
        patch("sevn.cli.commands.unboard.stop_all_gateway_instances"),
    ):
        result = runner.invoke(get_command(app), ["unboard", "--yes", "--home", str(home)])
    assert result.exit_code == 0
    assert not home.exists()
    assert "removed operator home" in result.stdout


def test_uninstall_alias_prints_notice_and_removes_home(
    runner: ClickCliRunner,
    tmp_path: Path,
) -> None:
    home = _install_operator_home(tmp_path)
    with (
        patch("sevn.cli.commands.unboard.stop_all_gateway_instances"),
    ):
        result = runner.invoke(get_command(app), ["uninstall", "--yes", "--home", str(home)])
    assert result.exit_code == 0
    assert _ALIAS_NOTICE in result.stderr
    assert not home.exists()


def test_remove_alias_prints_notice_and_removes_home(
    runner: ClickCliRunner,
    tmp_path: Path,
) -> None:
    home = _install_operator_home(tmp_path)
    with (
        patch("sevn.cli.commands.unboard.stop_all_gateway_instances"),
    ):
        result = runner.invoke(get_command(app), ["remove", "--yes", "--home", str(home)])
    assert result.exit_code == 0
    assert _ALIAS_NOTICE in result.stderr
    assert not home.exists()


def test_with_source_requires_resolvable_root(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_operator_home(tmp_path)
    monkeypatch.delenv("SEVN_SOURCE_ROOT", raising=False)
    with patch("sevn.cli.commands.unboard.resolve_source_root", return_value=None):
        result = runner.invoke(
            get_command(app),
            ["unboard", "--yes", "--with-source", "--home", str(home)],
        )
    assert result.exit_code == 4
    assert home.exists()


def test_with_source_removes_checkout_when_env_set(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_operator_home(tmp_path)
    source = tmp_path / "sevn.bot"
    source.mkdir()
    monkeypatch.setenv("SEVN_SOURCE_ROOT", str(source))
    with (
        patch("sevn.cli.commands.unboard.stop_all_gateway_instances"),
    ):
        result = runner.invoke(
            get_command(app),
            ["unboard", "--yes", "--with-source", "--home", str(home)],
        )
    assert result.exit_code == 0
    assert not home.exists()
    assert not source.exists()
    assert "removed source checkout" in result.stdout


def test_unboard_missing_home_exit4(runner: ClickCliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "empty"
    missing.mkdir()
    with patch("sevn.cli.commands.unboard.stop_all_gateway_instances") as stop_mock:
        result = runner.invoke(get_command(app), ["unboard", "--yes", "--home", str(missing)])
    stop_mock.assert_called_once()
    assert result.exit_code == 4
    assert "stopped gateway and proxy services" in result.stdout


def test_unboard_no_install_still_stops_gateway(
    runner: ClickCliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    monkeypatch.setattr("sevn.cli.commands.unboard.Path.home", lambda: fake_home)
    monkeypatch.setattr("sevn.cli.install_discovery.Path.home", lambda: fake_home)
    monkeypatch.delenv("SEVN_HOME", raising=False)
    with patch("sevn.cli.commands.unboard.stop_all_gateway_instances") as stop_mock:
        result = runner.invoke(get_command(app), ["unboard", "--yes"])
    stop_mock.assert_called_once()
    assert result.exit_code == 0
    assert "stopped gateway and proxy services" in result.stdout
    assert "no operator install found" in result.stderr


def test_discover_operator_homes_finds_sevn_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    _install_operator_home(fake_home, name=".sevn2")
    monkeypatch.setattr("sevn.cli.commands.unboard.Path.home", lambda: fake_home)
    monkeypatch.setattr("sevn.cli.install_discovery.Path.home", lambda: fake_home)
    found = discover_operator_home_paths()
    assert len(found) == 1
    assert found[0].name == ".sevn2"


def test_resolve_source_root_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setenv("SEVN_SOURCE_ROOT", str(checkout))
    assert resolve_source_root() == checkout.resolve()


def test_unboard_stops_gateway_before_operator_lock(tmp_path: Path) -> None:
    from click.exceptions import Exit

    home = _install_operator_home(tmp_path)
    call_order: list[str] = []

    def _track_stop(**_kwargs: object) -> None:
        call_order.append("stop")

    class _FakeLock:
        def __enter__(self) -> None:
            call_order.append("lock")
            raise OperatorLockHeld(home / "run" / "sevn-cli.lock")

        def __exit__(self, *_args: object) -> None:
            return None

    with (
        patch("sevn.cli.commands.unboard.stop_all_gateway_instances", side_effect=_track_stop),
        patch("sevn.cli.commands.unboard.operator_lock", return_value=_FakeLock()),
        pytest.raises(Exit) as exc,
    ):
        run_unboard(yes=True, home=home)
    assert exc.value.exit_code == 4
    assert call_order == ["stop", "lock"]
    assert home.is_dir()


def test_run_unboard_dry_run_leaves_tree(tmp_path: Path) -> None:
    from click.exceptions import Exit

    home = _install_operator_home(tmp_path)
    with pytest.raises(Exit) as exc:
        run_unboard(yes=True, home=home, dry_run=True)
    assert exc.value.exit_code == 0
    assert home.is_dir()
