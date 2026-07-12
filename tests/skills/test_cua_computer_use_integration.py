"""Integration tests for cua computer-use skills wiring (W0.1 / W1.2)."""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.gateway.menu import _skill_enabled
from sevn.skills.computer_use import (
    COMPUTER_USE_SKILL_ID,
    CUA_DRIVER_MCP_SERVER_ID,
    merge_computer_use_mcp_server,
)
from sevn.skills.manager import SkillsManager
from sevn.tools.registry import DEFAULT_SKILL_MANIFESTS


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _minimal() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_menu_computer_use_default_false() -> None:
    """``_skill_enabled`` treats ``computer_use`` as opt-in default false."""
    assert _skill_enabled(_minimal(), "computer_use") is False


@pytest.mark.parametrize("skill_key", ["cua_agent", "lume"])
def test_menu_new_skills_default_false(skill_key: str) -> None:
    """``cua_agent`` and ``lume`` default to disabled like ``computer_use``."""
    assert _skill_enabled(_minimal(), skill_key) is False


def test_registry_computer_use_manifest_present() -> None:
    """``DEFAULT_SKILL_MANIFESTS`` includes the ``computer-use`` row."""
    assert "computer-use" in DEFAULT_SKILL_MANIFESTS
    assert "computer" in DEFAULT_SKILL_MANIFESTS["computer-use"].lower()


@pytest.mark.parametrize("skill_id", ["cua-agent", "lume"])
def test_registry_manifest_rows_present(skill_id: str) -> None:
    assert skill_id in DEFAULT_SKILL_MANIFESTS


def test_registry_computer_use_manifest_mentions_sandbox() -> None:
    desc = DEFAULT_SKILL_MANIFESTS["computer-use"].lower()
    assert "sandbox" in desc or "cua do" in desc


def test_graphify_merge_injects_cua_driver_only_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Central MCP merge registers ``cua-driver`` only when computer-use is enabled+valid."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only MCP merge")

    disabled = build_effective_mcp_servers(_minimal(), tmp_path)
    assert CUA_DRIVER_MCP_SERVER_ID not in disabled

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "cua-driver"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    enabled_cfg = WorkspaceConfig(
        schema_version=1,
        skills={"computer_use": {"enabled": True, "target": "host"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    doc: dict[str, object] = {}
    merge_computer_use_mcp_server(doc, workspace=enabled_cfg)
    servers = doc.get("mcp_servers")
    assert isinstance(servers, dict)
    assert CUA_DRIVER_MCP_SERVER_ID in servers

    effective = build_effective_mcp_servers(enabled_cfg, tmp_path)
    assert CUA_DRIVER_MCP_SERVER_ID in effective


def test_graphify_merge_skips_mcp_for_sandbox_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only MCP merge")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cua",):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"computer_use": {"enabled": True, "target": "docker"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    effective = build_effective_mcp_servers(cfg, tmp_path)
    assert CUA_DRIVER_MCP_SERVER_ID not in effective


def test_manager_skips_computer_use_when_disabled(tmp_path: Path) -> None:
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert COMPUTER_USE_SKILL_ID not in mgr._records
