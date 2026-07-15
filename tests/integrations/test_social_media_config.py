"""Config loaders and schema contracts for ``skills.social_media_manager`` (W1.4/W1.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from sevn.browser.recipes.social import _SUPPORTED_SITES
from sevn.cli.app import app

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "infra" / "sevn.schema.json"


def _import_config_module() -> Any:
    from sevn.config.sections import skills_social_media as mod

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


def _minimal_sevn_json(**skills_extra: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "skills": {
            "social_media_manager": skills_extra,
        },
    }


class TestSocialMediaManagerConfigLoaders:
    """W1.4 — parse defaults and platform blocks (D1/D6/D13)."""

    def test_default_medium_defaults_browser(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.SocialMediaManagerSkillConfig.model_validate({})
        assert parsed.default_medium == "browser"

    def test_twexapi_enabled_defaults_false(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.SocialMediaManagerSkillConfig.model_validate({})
        assert parsed.twexapi.enabled is False

    def test_platform_medium_parsed(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.SocialMediaManagerSkillConfig.model_validate(
            {
                "default_medium": "browser",
                "platforms": {"x": {"medium": "twexapi"}},
            },
        )
        assert parsed.platforms["x"].medium == "twexapi"

    def test_invalid_medium_rejected(self) -> None:
        cfg_mod = _import_config_module()
        with pytest.raises(ValidationError, match="medium"):
            cfg_mod.SocialMediaManagerSkillConfig.model_validate(
                {"default_medium": "rest_api"},
            )

    def test_invalid_site_key_rejected(self) -> None:
        cfg_mod = _import_config_module()
        with pytest.raises(ValidationError, match=r"site|platform|unknown"):
            cfg_mod.SocialMediaManagerSkillConfig.model_validate(
                {"platforms": {"mastodon": {"medium": "browser"}}},
            )

    def test_site_key_enum_matches_supported_sites(self) -> None:
        cfg_mod = _import_config_module()
        assert frozenset(cfg_mod.SUPPORTED_SITE_KEYS) == _SUPPORTED_SITES

    def test_parse_via_workspace_config(self) -> None:
        cfg_mod = _import_config_module()
        from sevn.config.workspace_config import parse_workspace_config

        cfg = parse_workspace_config(
            _minimal_sevn_json(
                default_medium="browser",
                platforms={"facebook": {"medium": "browser"}},
                twexapi={"enabled": False},
            ),
        )
        parsed = cfg_mod.social_media_manager_settings(cfg)
        assert parsed.default_medium == "browser"
        assert parsed.platforms["facebook"].medium == "browser"


class TestTwexApiLoaderAlignment:
    """W1.4 / D13 — TwexAPI loader reads enabled default false."""

    def test_twexapi_loader_enabled_defaults_false(self, tmp_path: Path) -> None:
        from sevn.integrations.twexapi.config import load_twexapi_settings

        root = tmp_path / "ws"
        root.mkdir()
        (root / "sevn.json").write_text(
            json.dumps(_minimal_sevn_json()),
            encoding="utf-8",
        )
        settings, _cfg = load_twexapi_settings(root)
        assert settings.enabled is False


class TestSocialMediaManagerSchema:
    """W1.5 — generated schema includes ``skills.social_media_manager`` (D1/D6)."""

    def test_schema_has_social_media_manager_block(self) -> None:
        props = _skills_properties()
        block = props.get("social_media_manager")
        assert isinstance(block, dict)
        inner = block.get("properties")
        assert isinstance(inner, dict)
        assert "default_medium" in inner
        assert "twexapi" in inner
        assert "platforms" in inner

    def test_schema_default_medium_browser(self) -> None:
        props = _skills_properties()
        block = props["social_media_manager"]
        assert isinstance(block, dict)
        default_medium = block.get("properties", {}).get("default_medium")
        assert isinstance(default_medium, dict)
        assert default_medium.get("default") == "browser"

    def test_schema_twexapi_enabled_default_false(self) -> None:
        props = _skills_properties()
        block = props["social_media_manager"]
        assert isinstance(block, dict)
        twexapi = block.get("properties", {}).get("twexapi")
        assert isinstance(twexapi, dict)
        enabled = twexapi.get("properties", {}).get("enabled")
        assert isinstance(enabled, dict)
        assert enabled.get("default") is False

    def test_schema_platforms_keys_match_sites(self) -> None:
        props = _skills_properties()
        block = props["social_media_manager"]
        assert isinstance(block, dict)
        platforms = block.get("properties", {}).get("platforms")
        assert isinstance(platforms, dict)
        pattern_props = platforms.get("patternProperties") or platforms.get("additionalProperties")
        assert pattern_props is not None
        if isinstance(pattern_props, dict) and "enum" in platforms.get("propertyNames", {}):
            site_enum = set(platforms["propertyNames"]["enum"])
            assert site_enum == set(_SUPPORTED_SITES)


class TestConfigValidateCli:
    """W1.5 — ``sevn config validate`` accepts minimal + full fixtures."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_validate_minimal_fixture(self, runner: CliRunner, tmp_path: Path) -> None:
        sevn_json = tmp_path / "sevn.json"
        sevn_json.write_text(json.dumps(_minimal_sevn_json()), encoding="utf-8")
        schema = _load_schema()
        doc = json.loads(sevn_json.read_text(encoding="utf-8"))
        jsonschema.validate(doc, schema)
        result = runner.invoke(app, ["config", "validate", "--path", str(sevn_json)])
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_validate_full_fixture(self, runner: CliRunner, tmp_path: Path) -> None:
        sevn_json = tmp_path / "sevn.json"
        sevn_json.write_text(
            json.dumps(
                _minimal_sevn_json(
                    default_medium="browser",
                    twexapi={
                        "enabled": True,
                        "api_key": "${SECRET:keychain:sevn.twexapi}",
                        "base_url": "https://api.twexapi.io",
                    },
                    platforms={
                        site: {"medium": "twexapi" if site == "x" else "browser"}
                        for site in sorted(_SUPPORTED_SITES)
                    },
                ),
            ),
            encoding="utf-8",
        )
        schema = _load_schema()
        doc = json.loads(sevn_json.read_text(encoding="utf-8"))
        jsonschema.validate(doc, schema)
        result = runner.invoke(app, ["config", "validate", "--path", str(sevn_json)])
        assert result.exit_code == 0, result.stdout + result.stderr


class TestOnboardingCapability:
    """W1.8 — onboarding capability default false (D12)."""

    def test_onboarding_default_false(self) -> None:
        from sevn.onboarding.capabilities_manifest import load_capabilities_manifest

        manifest = load_capabilities_manifest()
        cap = next(c for c in manifest.capabilities if c.id == "skill.social_media_manager")
        assert cap.default is False
