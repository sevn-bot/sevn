"""Shared fixtures for Second Brain PARA wave tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sevn.config.workspace_config import SecondBrainWorkspaceConfig, parse_workspace_config

PARA_PROFILE_DEFAULTS: dict[str, str] = {
    "inbox": "00_Inbox",
    "projects": "10_Projects",
    "areas": "20_Areas",
    "resources": "30_Resources",
    "archive": "40_Archive",
    "templates": "90_Templates",
    "sources_subdir": "_sources",
    "outputs_subdir": "_outputs",
    "index_note": "index.md",
    "log_note": "log.md",
}

GATEWAY_TOKEN = "test-token-1234567890"


def legacy_sevn_doc(**overrides: Any) -> dict[str, Any]:
    """Minimal legacy ``sevn.json`` document for config validation tests."""
    base: dict[str, Any] = {
        "schema_version": 1,
        "gateway": {"token": GATEWAY_TOKEN},
        "second_brain": {"enabled": True},
    }
    if overrides:
        sb = dict(base.get("second_brain", {}))
        for key, value in overrides.items():
            if key == "second_brain" and isinstance(value, dict):
                sb.update(value)
            else:
                base[key] = value
        base["second_brain"] = sb
    return base


def para_sevn_doc(
    *,
    vault: str = "obsidian/alex_AI",
    para: dict[str, str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Minimal PARA-layout ``sevn.json`` document for config validation tests."""
    sb: dict[str, Any] = {
        "enabled": True,
        "layout": "para",
        "paths": {"vault": vault},
        "para": dict(PARA_PROFILE_DEFAULTS if para is None else {**PARA_PROFILE_DEFAULTS, **para}),
    }
    doc = legacy_sevn_doc(second_brain=sb)
    if overrides:
        for key, value in overrides.items():
            doc[key] = value
    return doc


def sb_cfg_from_doc(doc: dict[str, Any]) -> SecondBrainWorkspaceConfig:
    parsed = parse_workspace_config(doc)
    assert parsed.second_brain is not None
    return parsed.second_brain


@pytest.fixture
def para_vault_root(tmp_path: Path) -> Path:
    """Resolved PARA vault directory under a tmp workspace."""
    root = tmp_path / "obsidian" / "alex_AI"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def legacy_sb_config() -> SecondBrainWorkspaceConfig:
    return SecondBrainWorkspaceConfig()


@pytest.fixture
def para_sb_config_doc() -> dict[str, Any]:
    return para_sevn_doc()


@pytest.fixture
def para_sb_config(para_sb_config_doc: dict[str, Any]) -> SecondBrainWorkspaceConfig:
    doc = parse_workspace_config(para_sb_config_doc)
    assert doc.second_brain is not None
    return doc.second_brain
