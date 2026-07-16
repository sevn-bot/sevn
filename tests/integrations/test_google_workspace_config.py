"""Config loaders and schema contracts for ``skills.google_workspace``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "infra" / "sevn.schema.json"


def _import_config_module() -> Any:
    from sevn.config.sections import skills_google_workspace as mod

    return mod


def _load_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _skills_properties() -> dict[str, object]:
    schema = _load_schema()
    props = schema.get("properties")
    assert isinstance(props, dict)
    skills = props.get("skills")
    assert isinstance(skills, dict)
    skill_props = skills.get("properties")
    assert isinstance(skill_props, dict)
    return skill_props


def _minimal_sevn_json(**skills_extra: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "skills": {"google_workspace": skills_extra},
    }


class TestGoogleWorkspaceConfigLoaders:
    """Defaults and parsing for ``skills.google_workspace``."""

    def test_defaults_match_phase_one_contract(self) -> None:
        cfg_mod = _import_config_module()
        parsed = cfg_mod.GoogleWorkspaceSkillConfig.model_validate({})
        assert parsed.enabled is True
        assert parsed.prefer_gws is True
        assert parsed.default_services == "all"
        assert parsed.account_label == "Primary Google"
        assert parsed.dry_run is False

    def test_parse_via_workspace_config(self) -> None:
        cfg_mod = _import_config_module()
        from sevn.config.workspace_config import parse_workspace_config

        cfg = parse_workspace_config(
            _minimal_sevn_json(
                enabled=False,
                prefer_gws=False,
                default_services="calendar",
                account_label="Work Google",
                dry_run=True,
            ),
        )
        parsed = cfg_mod.google_workspace_settings(cfg)
        assert parsed.enabled is False
        assert parsed.prefer_gws is False
        assert parsed.default_services == "calendar"
        assert parsed.account_label == "Work Google"
        assert parsed.dry_run is True


class TestGoogleWorkspaceSchema:
    """Generated schema includes ``skills.google_workspace`` defaults."""

    def test_schema_has_google_workspace_block(self) -> None:
        props = _skills_properties()
        block = props.get("google_workspace")
        assert isinstance(block, dict)
        inner = block.get("properties")
        assert isinstance(inner, dict)
        assert "enabled" in inner
        assert "prefer_gws" in inner
        assert "default_services" in inner
        assert "account_label" in inner
        assert "dry_run" in inner

    def test_schema_defaults_match_phase_one_contract(self) -> None:
        props = _skills_properties()
        block = props["google_workspace"]
        assert isinstance(block, dict)
        inner = block.get("properties")
        assert isinstance(inner, dict)
        assert inner["enabled"]["default"] is True
        assert inner["prefer_gws"]["default"] is True
        assert inner["default_services"]["default"] == "all"
        assert inner["account_label"]["default"] == "Primary Google"
        assert inner["dry_run"]["default"] is False
