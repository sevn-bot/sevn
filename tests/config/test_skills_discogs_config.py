"""Config loaders and schema contracts for ``skills.discogs`` (W1.1 / D2/D4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from sevn.cli.app import app

pytestmark = pytest.mark.xfail(
    reason="green after W2: DiscogsSkillsConfig + schema",
    strict=False,
)

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "infra" / "sevn.schema.json"


def _import_config_module() -> Any:
    from sevn.config.sections import skills_discogs as mod

    return mod


def _load_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _skills_properties() -> dict[str, object]:
    schema = _load_schema()
    skills = schema.get("properties", {})
    assert isinstance(skills, dict)
    skills_obj = skills.get("skills")
    assert isinstance(skills_obj, dict)
    props = skills_obj.get("properties")
    assert isinstance(props, dict)
    return props


class TestDiscogsSkillsConfigDefaults:
    """D4 — ``DiscogsSkillsConfig`` defaults."""

    def test_enabled_defaults_false(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.DiscogsSkillsConfig.model_validate({})
        assert parsed.enabled is False

    def test_auth_method_defaults_user_token(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.DiscogsSkillsConfig.model_validate({})
        assert parsed.auth_method == "user_token"

    def test_user_agent_default(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.DiscogsSkillsConfig.model_validate({})
        assert parsed.user_agent == "sevn-discogs/1.0"

    def test_confirm_writes_defaults_true(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.DiscogsSkillsConfig.model_validate({})
        assert parsed.confirm_writes is True

    def test_per_skill_sub_flags_default_to_group_enabled(self) -> None:
        cfg_mod = _import_config_module()
        enabled = cfg_mod.DiscogsSkillsConfig.model_validate({"enabled": True})
        for domain in ("database", "marketplace", "collection", "wantlist", "identity"):
            assert getattr(enabled, f"{domain}_enabled") is True
        disabled = cfg_mod.DiscogsSkillsConfig.model_validate({"enabled": False})
        for domain in ("database", "marketplace", "collection", "wantlist", "identity"):
            assert getattr(disabled, f"{domain}_enabled") is False

    def test_invalid_auth_method_rejected(self) -> None:
        cfg_mod = _import_config_module()
        with pytest.raises(ValidationError, match="auth_method"):
            cfg_mod.DiscogsSkillsConfig.model_validate({"auth_method": "basic"})


class TestDiscogsSettingsAccessor:
    """``discogs_settings(cfg)`` reads ``skills.discogs``."""

    def test_discogs_settings_none_returns_defaults(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.discogs_settings(None)
        assert parsed.enabled is False
        assert parsed.auth_method == "user_token"

    def test_discogs_settings_from_workspace(self) -> None:
        cfg_mod = _import_config_module()
        from sevn.config.workspace_config import parse_workspace_config

        doc = {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "skills": {
                "discogs": {
                    "enabled": True,
                    "auth_method": "oauth",
                    "database.enabled": False,
                },
            },
        }
        cfg = parse_workspace_config(doc)
        parsed = cfg_mod.discogs_settings(cfg)
        assert parsed.enabled is True
        assert parsed.auth_method == "oauth"
        assert parsed.database_enabled is False


class TestDiscogsSchemaBlock:
    """``infra/sevn.schema.json`` exposes ``skills.discogs`` for menu toggles."""

    def test_schema_has_discogs_block(self) -> None:
        props = _skills_properties()
        block = props.get("discogs")
        assert isinstance(block, dict)
        inner = block.get("properties")
        assert isinstance(inner, dict)
        assert "enabled" in inner
        assert "auth_method" in inner
        assert "confirm_writes" in inner

    @pytest.mark.parametrize(
        "domain",
        [
            ("database",),
            ("marketplace",),
            ("collection",),
            ("wantlist",),
            ("identity",),
        ],
    )
    def test_schema_has_per_skill_toggle(self, domain: str) -> None:
        props = _skills_properties()
        block = props["discogs"]
        assert isinstance(block, dict)
        inner = block.get("properties", {})
        assert isinstance(inner, dict)
        assert f"{domain}.enabled" in inner

    def test_schema_enabled_default_false(self) -> None:
        props = _skills_properties()
        block = props["discogs"]
        assert isinstance(block, dict)
        enabled = block.get("properties", {}).get("enabled")
        assert isinstance(enabled, dict)
        assert enabled.get("default") is False


class TestConfigValidateCli:
    """``sevn config validate`` accepts a minimal ``skills.discogs`` fixture."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_validate_minimal_discogs_fixture(self, runner: CliRunner, tmp_path: Path) -> None:
        sevn_json = tmp_path / "sevn.json"
        sevn_json.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                    "skills": {"discogs": {"enabled": False}},
                },
            ),
            encoding="utf-8",
        )
        schema = _load_schema()
        doc = json.loads(sevn_json.read_text(encoding="utf-8"))
        jsonschema.validate(doc, schema)
        result = runner.invoke(app, ["config", "validate", "--path", str(sevn_json)])
        assert result.exit_code == 0, result.stdout + result.stderr
