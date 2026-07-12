"""Bundled ``lume`` VM lifecycle skill gate tests (W0.2 / D6)."""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.errors import SkillExecutionError
from sevn.skills.manager import SkillsManager

_SKILL_ID = "lume"
_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / _SKILL_ID


def _import_lume():
    spec = importlib.util.find_spec("sevn.skills.lume")
    if spec is None:
        pytest.fail("sevn.skills.lume not implemented (green after W4)")
    return importlib.import_module("sevn.skills.lume")


def _enabled_config() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={"lume": {"enabled": True}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def test_bundled_skill_manifest_exists() -> None:
    """Bundled core tree ships ``lume/SKILL.md``."""
    assert (_SKILL_ROOT / "SKILL.md").is_file()


def test_lume_config_enabled_defaults_false() -> None:
    mod = _import_lume()
    assert mod.lume_config_enabled(None) is False
    assert mod.lume_config_enabled(_enabled_config()) is True


def test_gate_skips_when_disabled() -> None:
    mod = _import_lume()
    assert mod.gate_lume_core_skill(None) == "skip"


def test_gate_loads_when_enabled_on_apple_silicon_with_lume_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only load path")
    if platform.machine() not in {"arm64", "aarch64"}:
        pytest.skip("Apple-Silicon-only load path")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "lume"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    mod = _import_lume()
    assert mod.gate_lume_core_skill(_enabled_config()) == "load"


def test_validate_lume_host_fail_fast_non_darwin() -> None:
    """``lume`` on non-Darwin hosts fails fast at load."""
    if platform.system() == "Darwin":
        pytest.skip("non-Darwin fail-fast path")

    mod = _import_lume()
    with pytest.raises(SkillExecutionError, match="macOS"):
        mod.validate_lume_host(cfg=_enabled_config())


def test_validate_lume_host_fail_fast_non_apple_silicon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("Darwin-only ARM gate")
    if platform.machine() in {"arm64", "aarch64"}:
        pytest.skip("need non-Apple-Silicon machine() for this path")

    mod = _import_lume()
    with pytest.raises(SkillExecutionError, match="Apple Silicon"):
        mod.validate_lume_host(cfg=_enabled_config())


def test_validate_lume_host_fail_fast_missing_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only missing-binary path")
    if platform.machine() not in {"arm64", "aarch64"}:
        pytest.skip("Apple-Silicon-only missing-binary path")

    monkeypatch.setenv("PATH", "")
    mod = _import_lume()
    with pytest.raises(SkillExecutionError, match="`lume`"):
        mod.validate_lume_host(cfg=_enabled_config())


def test_manager_omits_skill_when_disabled(tmp_path: Path) -> None:
    mod = _import_lume()
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert mod.LUME_SKILL_ID not in mgr._records


def test_manager_includes_skill_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only load path")
    if platform.machine() not in {"arm64", "aarch64"}:
        pytest.skip("Apple-Silicon-only load path")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "lume"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    mod = _import_lume()
    mgr = SkillsManager.shared(
        tmp_path,
        (BUNDLED_SKILLS_ROOT,),
        config=_enabled_config(),
    )
    assert mod.LUME_SKILL_ID in mgr._records
