"""CLI service manager install (`specs/23-cli.md` §4.2)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sevn.cli.service_manager import (
    _gateway_daemon_env,
    _render_launchd_plist,
    install_paired_units,
    propagate_daemon_secret_env,
)
from sevn.cli.uvicorn_argv import uvicorn_program_argv

if TYPE_CHECKING:
    import pytest


def test_propagate_daemon_secret_env_passphrase_mode_clears_master_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passphrase mode mirrors the passphrase and always unsets the stray master_key.

    Regression: leaving a stale ``SEVN_SECRETS_MASTER_KEY`` in the session shadowed the
    passphrase and silently broke decryption of a passphrase-sealed store on every boot.
    """
    import sevn.cli.service_manager as sm

    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "pp")
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "deadbeef")  # stray; must be cleared
    monkeypatch.setattr(sm, "_daemon_encrypted_file_key_source", lambda: "passphrase")
    monkeypatch.setattr(sm, "plan_install", lambda _home: sm._launchd_paths(Path.home()))
    monkeypatch.setattr(
        sm,
        "_active_unlock_secret_for_launchctl",
        lambda *, key_source: "pp" if key_source == "passphrase" else "",
    )

    calls: list[list[str]] = []
    monkeypatch.setattr(sm, "_run", lambda argv: calls.append(list(argv)))

    propagate_daemon_secret_env()

    assert ["launchctl", "setenv", "SEVN_SECRETS_PASSPHRASE", "pp"] in calls
    assert ["launchctl", "unsetenv", "SEVN_SECRETS_MASTER_KEY"] in calls


def test_propagate_daemon_secret_env_master_key_mode_clears_passphrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """master_key mode mirrors the master key and always unsets a stray passphrase."""
    import sevn.cli.service_manager as sm

    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "ab" * 32)
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "stray-pp")  # inactive; must be cleared
    monkeypatch.setattr(sm, "_daemon_encrypted_file_key_source", lambda: "master_key")
    monkeypatch.setattr(sm, "plan_install", lambda _home: sm._launchd_paths(Path.home()))

    calls: list[list[str]] = []
    monkeypatch.setattr(sm, "_run", lambda argv: calls.append(list(argv)))

    propagate_daemon_secret_env()

    assert ["launchctl", "setenv", "SEVN_SECRETS_MASTER_KEY", "ab" * 32] in calls
    assert ["launchctl", "unsetenv", "SEVN_SECRETS_PASSPHRASE"] in calls


def test_uvicorn_program_argv_skips_uv_run() -> None:
    argv = uvicorn_program_argv(
        module="sevn.gateway.http_server:create_app",
        port=3001,
        factory=True,
    )
    assert "run" not in argv
    assert argv[-1] == "3001"


def test_launchd_plist_uses_tool_uvicorn_not_uv_run() -> None:
    home = Path("/tmp/sevn-test-home")
    xml = _render_launchd_plist(
        label="ai.sevn.gateway",
        module="sevn.gateway.http_server:create_app",
        port=3001,
        operator_home=home,
        log_basename="gateway.log",
    )
    assert "uv run" not in xml
    assert "uvicorn" in xml
    assert str(home) in xml
    assert "gateway.log" in xml
    assert "SEVN_SERVICE_LOG" in xml


def test_gateway_daemon_env_prepends_operator_path(tmp_path: Path) -> None:
    user_home = tmp_path / "user"
    user_home.mkdir()
    local_bin = user_home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    operator_home = user_home / ".sevn"
    operator_home.mkdir()
    env = _gateway_daemon_env(operator_home)
    path_parts = env["PATH"].split(":")
    assert str(local_bin) in path_parts
    assert "/usr/bin" in path_parts


def test_launchd_gateway_plist_includes_proxy_url() -> None:
    home = Path("/tmp/sevn-test-home")
    xml = _render_launchd_plist(
        label="ai.sevn.gateway",
        module="sevn.gateway.http_server:create_app",
        port=3001,
        operator_home=home,
        log_basename="gateway.log",
        extra_env={"SEVN_PROXY_URL": "http://127.0.0.1:8787"},
    )
    assert "SEVN_PROXY_URL" in xml
    assert "8787" in xml


def test_launchd_proxy_plist_redirects_proxy_log() -> None:
    home = Path("/tmp/sevn-test-home")
    xml = _render_launchd_plist(
        label="ai.sevn.proxy",
        module="sevn.proxy.app:create_app",
        port=8787,
        operator_home=home,
        working_directory=home,
        log_basename="proxy.log",
    )
    assert "proxy.log" in xml
    assert "<string>proxy</string>" in xml


def test_install_paired_units_dry_run() -> None:
    plan = install_paired_units(home=Path("/tmp/sevn-test-home"), dry_run=True)
    assert plan.gateway_unit_path.parent == plan.proxy_unit_path.parent
    assert plan.platform in ("launchd", "systemd")


def test_control_unit_dry_run() -> None:
    from sevn.cli.service_manager import control_unit

    line = control_unit(
        home=Path("/tmp/sevn-test-home"),
        service="gateway",
        action="start",
        dry_run=True,
    )
    assert line.startswith("dry-run:")


def test_stop_paired_units_dry_run() -> None:
    from sevn.cli.service_manager import stop_paired_units

    stop_paired_units(home=Path("/tmp/sevn-test-home"), dry_run=True)


def test_remove_paired_unit_files_dry_run() -> None:
    from sevn.cli.service_manager import remove_paired_unit_files

    plan = remove_paired_unit_files(home=Path("/tmp/sevn-test-home"), dry_run=True)
    assert plan.gateway_unit_path.name.endswith((".plist", ".service"))


def test_control_unit_status_requires_unit_file(tmp_path: Path) -> None:
    import pytest

    from sevn.cli.service_manager import ServiceManagerError, control_unit

    with pytest.raises(ServiceManagerError, match="unit not installed"):
        control_unit(home=tmp_path, service="gateway", action="status")
