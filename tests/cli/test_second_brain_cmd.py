"""CLI tests for ``sevn second-brain`` and ``sevn config second-brain``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _install_home(tmp_path: Path, doc: dict[str, object]) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    return home


def test_second_brain_setup_creates_custom_vault(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {"schema_version": 1, "gateway": {"token": "test-token-1234567890"}},
    )
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(
        get_command(app),
        ["second-brain", "setup", "--vault", "obsidian/test", "--no-model"],
    )
    assert result.exit_code == 0, result.stdout
    sj = home / "workspace" / "sevn.json"
    doc = json.loads(sj.read_text(encoding="utf-8"))
    assert doc["second_brain"]["enabled"] is True
    assert doc["second_brain"]["paths"]["vault"] == "obsidian/test"
    assert (home / "workspace" / "obsidian" / "test" / "wiki" / "index.md").is_file()


def test_config_second_brain_shows_vault_line(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_home(
        tmp_path,
        {
            "schema_version": 1,
            "gateway": {"token": "test-token-1234567890"},
            "second_brain": {
                "enabled": True,
                "paths": {"vault": "obsidian/alex_AI"},
            },
        },
    )
    ws = home / "workspace"
    (ws / "obsidian" / "alex_AI" / "wiki").mkdir(parents=True)
    (ws / "obsidian" / "alex_AI" / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(get_command(app), ["config", "second-brain"])
    assert result.exit_code == 0, result.stdout
    assert "obsidian/alex_AI" in result.stdout
