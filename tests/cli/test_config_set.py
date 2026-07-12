"""``sevn config set`` (`specs/23-cli.md` §2.4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.onboarding.draft_store import draft_path

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "onboarding" / "migrate"
_V1_SEVN_JSON = _FIXTURES / "v1_workspace" / "sevn.json"


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _install_bound_workspace(tmp_path: Path, *, src: Path) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    shutil.copy(src, ws / "sevn.json")
    return home


def test_config_set_happy_path(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(get_command(app), ["config", "set", "gateway.port", "3002"])
    assert result.exit_code == 0
    assert "set gateway.port" in result.stdout
    doc = json.loads((home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    assert doc["gateway"]["port"] == 3002
    assert not draft_path(home / "workspace" / "sevn.json").exists()


def test_config_set_agent_codemode_max_retries(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        get_command(app),
        ["config", "set", "agent.codemode.max_retries", "5"],
    )
    assert result.exit_code == 0
    doc = json.loads((home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    assert doc["agent"]["codemode"]["max_retries"] == 5


def test_config_set_rejects_unknown_schema_path(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    before = (home / "workspace" / "sevn.json").read_text(encoding="utf-8")
    result = runner.invoke(
        get_command(app),
        ["config", "set", "not.in.schema.path", "1"],
    )
    assert result.exit_code == 2
    assert (home / "workspace" / "sevn.json").read_text(encoding="utf-8") == before


def test_config_set_atomic_write_creates_backup(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    ws = home / "workspace"
    result = runner.invoke(get_command(app), ["config", "set", "gateway.host", '"127.0.0.2"'])
    assert result.exit_code == 0
    backups = list(ws.glob("sevn.json.v1*"))
    assert backups
    doc = json.loads((ws / "sevn.json").read_text(encoding="utf-8"))
    assert doc["gateway"]["host"] == "127.0.0.2"


def test_config_set_json_failure_unknown_key(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        get_command(app),
        ["config", "set", "not.in.schema.path", "1", "--json"],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is False
    assert payload["error_code"] == "USAGE"
    assert payload["exit_code"] == 2
