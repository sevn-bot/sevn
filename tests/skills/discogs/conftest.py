"""Shared fixtures and helpers for Discogs skills RED suite (W1)."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT

REPO_ROOT = Path(__file__).resolve().parents[3]

DISCOGS_SKILL_IDS: tuple[str, ...] = (
    "discogs-database",
    "discogs-marketplace",
    "discogs-collection",
    "discogs-wantlist",
    "discogs-identity",
)

DISCOGS_DOMAINS: tuple[str, ...] = (
    "database",
    "marketplace",
    "collection",
    "wantlist",
    "identity",
)

DISCOGS_SECRET_ALIASES: tuple[str, ...] = (
    "discogs.user_token",
    "discogs.consumer_key",
    "discogs.consumer_secret",
    "discogs.oauth_token",
    "discogs.oauth_token_secret",
)


def import_discogs_module(module_name: str) -> Any:
    """Import a ``sevn.skills.discogs*`` module or fail with a clear message."""
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        pytest.fail(f"{module_name} not implemented")
    return importlib.import_module(module_name)


def skill_root(skill_id: str) -> Path:
    """Return bundled core skill directory for one Discogs skill id."""
    return BUNDLED_SKILLS_ROOT / "core" / skill_id


def common_script_path(skill_id: str = "discogs-database") -> Path:
    """Return ``_discogs_common.py`` path inside a bundled skill tree."""
    return skill_root(skill_id) / "scripts" / "_discogs_common.py"


def load_skill_script(skill_id: str, script_name: str) -> Any:
    """Load one bundled skill script module by file path."""
    path = skill_root(skill_id) / "scripts" / script_name
    if not path.is_file():
        pytest.fail(f"missing script {path}")
    spec = importlib.util.spec_from_file_location(
        f"discogs_{skill_id}_{script_name.replace('.py', '')}",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    for shared_name in ("_helpers", "_discogs_common"):
        sys.modules.pop(shared_name, None)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_discogs_common(skill_id: str = "discogs-database") -> Any:
    """Load ``_discogs_common.py`` from a bundled skill directory."""
    return load_skill_script(skill_id, "_discogs_common.py")


def enabled_discogs_config(
    *,
    group_enabled: bool = True,
    auth_method: str = "user_token",
    confirm_writes: bool = True,
    sub_flags: dict[str, bool] | None = None,
) -> WorkspaceConfig:
    """Build workspace config with ``skills.discogs`` block."""
    block: dict[str, Any] = {
        "enabled": group_enabled,
        "auth_method": auth_method,
        "user_agent": "sevn-discogs/1.0",
        "confirm_writes": confirm_writes,
    }
    for domain in DISCOGS_DOMAINS:
        key = f"{domain}.enabled"
        if sub_flags and domain in sub_flags:
            block[key] = sub_flags[domain]
        elif group_enabled:
            block[key] = True
    return WorkspaceConfig(
        schema_version=1,
        skills={"discogs": block},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def minimal_sevn_json(**discogs_extra: object) -> dict[str, object]:
    """Minimal ``sevn.json`` document with optional ``skills.discogs`` keys."""
    discogs_block: dict[str, object] = {"enabled": False}
    discogs_block.update(discogs_extra)
    return {
        "schema_version": 1,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "skills": {"discogs": discogs_block},
    }


def run_skill_script(
    skill_id: str,
    script_name: str,
    cli_args: list[str],
    *,
    env: dict[str, str] | None = None,
    workspace: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run a bundled skill script in-process and parse its JSON stdout envelope."""
    proc_env = os.environ.copy()
    if workspace is not None:
        proc_env["SEVN_WORKSPACE"] = str(workspace)
    if env:
        proc_env.update(env)
    mod = load_skill_script(skill_id, script_name)
    old_env = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(proc_env)
        code, payload = mod.main(cli_args)
    finally:
        os.environ.clear()
        os.environ.update(old_env)
    return code, payload


def mock_discogs_client() -> MagicMock:
    """Return a stub ``discogs_client.Client`` with chainable search/list APIs."""
    client = MagicMock(name="discogs_client.Client")
    client.search.return_value = MagicMock(pages=1, page=1, per_page=50, count=0)
    client.identity.return_value = MagicMock(username="test-operator")
    return client


@pytest.fixture(autouse=True)
def _reset_skills_manager_singletons() -> Any:
    """Isolate SkillsManager singleton state across Discogs gate tests."""
    from sevn.skills.manager import SkillsManager

    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()
