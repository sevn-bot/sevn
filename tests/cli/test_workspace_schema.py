"""``sevn.cli.workspace_schema`` — config-set allowlist helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.workspace_schema import dotted_path_in_schema, load_workspace_json_schema
from sevn.onboarding.draft_store import draft_path

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "onboarding" / "migrate"
_V1_SEVN_JSON = _FIXTURES / "v1_workspace" / "sevn.json"


def test_dotted_path_in_schema_follows_provider_registry_ref() -> None:
    schema = load_workspace_json_schema()
    assert dotted_path_in_schema(schema, "providers.openai.auth_mode")
    assert dotted_path_in_schema(schema, "providers.openai.api_key")
    assert dotted_path_in_schema(schema, "providers.tier_default.B")
    assert dotted_path_in_schema(schema, "providers.tier_default.triager")
    assert not dotted_path_in_schema(schema, "providers.openai.not_a_field")


def test_config_set_tier_default_b(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    shutil.copy(_V1_SEVN_JSON, ws / "sevn.json")
    monkeypatch.setenv("SEVN_HOME", str(home))
    runner = ClickCliRunner()
    result = runner.invoke(
        get_command(app),
        ["config", "set", "providers.tier_default.B", '"openai/gpt-5.5"'],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    doc = json.loads((ws / "sevn.json").read_text(encoding="utf-8"))
    assert doc["providers"]["tier_default"]["B"] == "openai/gpt-5.5"


def test_config_set_tier_default_b_splits_unified_model(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    base = json.loads(_V1_SEVN_JSON.read_text(encoding="utf-8"))
    base["providers"] = {
        "use_main_model_for_all": True,
        "tier_default": {"triager": "minimax/MiniMax-M3"},
        "minimax": {"api_key": "${SECRET:SEVN_SECRET_MINIMAX}"},
        "openai": {"auth_mode": "oauth"},
    }
    (ws / "sevn.json").write_text(json.dumps(base, indent=2), encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    runner = ClickCliRunner()
    result = runner.invoke(
        get_command(app),
        ["config", "set", "providers.tier_default.B", '"openai/gpt-5.5"'],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    doc = json.loads((ws / "sevn.json").read_text(encoding="utf-8"))
    providers = doc["providers"]
    assert providers["use_main_model_for_all"] is False
    tier = providers["tier_default"]
    assert tier["triager"] == "minimax/MiniMax-M3"
    assert tier["B"] == "openai/gpt-5.5"
    assert tier["C"] == "minimax/MiniMax-M3"
    assert tier["D"] == "minimax/MiniMax-M3"


def test_config_set_openai_auth_mode(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    shutil.copy(_V1_SEVN_JSON, ws / "sevn.json")
    monkeypatch.setenv("SEVN_HOME", str(home))
    runner = ClickCliRunner()
    result = runner.invoke(
        get_command(app),
        ["config", "set", "providers.openai.auth_mode", "oauth"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    doc = json.loads((ws / "sevn.json").read_text(encoding="utf-8"))
    assert doc["providers"]["openai"]["auth_mode"] == "oauth"
    assert not draft_path(ws / "sevn.json").exists()
