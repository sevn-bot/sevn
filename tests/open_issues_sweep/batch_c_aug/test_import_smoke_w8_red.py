"""W8.1 - import smoke for ``social_media_manager`` scripts + ``x_ops`` (no ``social_browser``)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.open_issues_sweep.batch_c_aug.conftest import (
    BUNDLED_SCRIPT_NAMES,
    SCRIPTS_DIR,
    load_smm_script,
)

_FORBIDDEN_IMPORT = "sevn.skills.social_browser"


def test_bundled_scripts_never_import_social_browser_module() -> None:
    """D7: bundled skill scripts must not reference the deleted ``social_browser`` module."""
    hits: list[str] = []
    for name in BUNDLED_SCRIPT_NAMES:
        text = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
        if _FORBIDDEN_IMPORT in text:
            hits.append(name)
    assert hits == []


@pytest.mark.parametrize("script_name", BUNDLED_SCRIPT_NAMES)
def test_social_media_manager_script_imports_without_error(script_name: str) -> None:
    """Every bundled script collects/imports cleanly (no ``social_browser`` dependency)."""
    mod = load_smm_script(script_name)
    assert mod is not None


def test_x_ops_facade_and_dispatch_import_cleanly() -> None:
    """Integration facade + dispatch table import without deleted skill modules."""
    from sevn.integrations.social_media import x_ops
    from sevn.integrations.social_media.x_ops_dispatch import FACADE_OPS, envelope

    assert callable(x_ops.home_timeline_collect)
    assert "session_status" in FACADE_OPS
    sample = envelope(ok=True, medium="browser", op="session_status", data={})
    assert sample["ok"] is True
    assert set(sample) >= {"ok", "medium", "op", "data"}


def test_social_browser_module_is_not_restored_on_trunk() -> None:
    """#128: deleted module stays absent — migration uses integrations stack (D7)."""
    spec = importlib.util.find_spec(_FORBIDDEN_IMPORT)
    assert spec is None


@pytest.mark.xfail(reason="green after W9: legacy x-use import migration (#128)", strict=False)
def test_legacy_x_use_import_migration_helper_exists() -> None:
    """Operator workspaces with old ``x-use`` imports get a documented migration seam."""
    from sevn.skills import social_browser_migration as migration

    assert callable(getattr(migration, "rewrite_legacy_imports", None))


@pytest.mark.xfail(
    reason="green after W9: operator x-use stub → social_media_manager (#128)", strict=False
)
def test_operator_x_use_stub_skill_manifest_points_at_social_stack(tmp_path: Path) -> None:
    """Thin operator ``skills/x-use/`` stub (if present) references ``social_media_manager``."""
    stub_root = tmp_path / "skills" / "user" / "x-use"
    stub_root.mkdir(parents=True)
    skill_md = stub_root / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: x-use\n"
        "description: legacy alias\n"
        "version: 0.0.0\n"
        "see_also:\n"
        "  - social_media_manager\n"
        "---\n"
        "Use social_media_manager + browser action=social.\n",
        encoding="utf-8",
    )
    from sevn.skills.x_use_migration import validate_operator_stub

    report = validate_operator_stub(stub_root)
    assert report["ok"] is True
    assert report["target_skill"] == "social_media_manager"


@pytest.mark.xfail(
    reason="green after W9: readiness drops social_browser-only SSOT (#128)", strict=False
)
def test_readiness_profile_resolution_prefers_social_media_manager_config() -> None:
    """Readiness/browser profile must not require ``skills.social_browser`` alone."""
    from sevn.integrations.social_media.readiness import social_browser_config_deprecated

    assert social_browser_config_deprecated() is True
