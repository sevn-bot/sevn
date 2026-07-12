"""Bundled ``cua-agent`` skill gates and approval contract tests (W0.2 / D5)."""

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

_SKILL_ID = "cua-agent"
_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / _SKILL_ID


def _import_cua_agent():
    spec = importlib.util.find_spec("sevn.skills.cua_agent")
    if spec is None:
        pytest.fail("sevn.skills.cua_agent not implemented (green after W3)")
    return importlib.import_module("sevn.skills.cua_agent")


def _enabled_config(*, computer_use: bool = True) -> WorkspaceConfig:
    skills: dict[str, object] = {
        "cua_agent": {"enabled": True, "require_computer_use": True, "approval": "per_run"},
    }
    if computer_use:
        skills["computer_use"] = {"enabled": True}
    return WorkspaceConfig(
        schema_version=1,
        skills=skills,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def test_bundled_skill_manifest_exists() -> None:
    """Bundled core tree ships ``cua-agent/SKILL.md``."""
    assert (_SKILL_ROOT / "SKILL.md").is_file()


def test_cua_agent_config_enabled_defaults_false() -> None:
    mod = _import_cua_agent()
    assert mod.cua_agent_config_enabled(None) is False
    assert mod.cua_agent_config_enabled(_enabled_config()) is True


def test_gate_skips_when_disabled() -> None:
    mod = _import_cua_agent()
    assert mod.gate_cua_agent_core_skill(None) == "skip"


def test_gate_loads_when_enabled_on_darwin_with_cua_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only load path")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cua-driver", "cua"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    mod = _import_cua_agent()
    assert mod.gate_cua_agent_core_skill(_enabled_config()) == "load"


def test_validate_cua_agent_host_fail_fast_non_darwin() -> None:
    if platform.system() == "Darwin":
        pytest.skip("non-Darwin fail-fast path")

    mod = _import_cua_agent()
    with pytest.raises(SkillExecutionError, match="macOS"):
        mod.validate_cua_agent_host(cfg=_enabled_config())


def test_validate_cua_agent_host_fail_fast_missing_cua(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only missing-binary path")

    monkeypatch.setenv("PATH", "")
    mod = _import_cua_agent()
    with pytest.raises(SkillExecutionError, match="`cua`"):
        mod.validate_cua_agent_host(cfg=_enabled_config())


def test_validate_cua_agent_host_requires_computer_use_enabled() -> None:
    """``cua-agent`` enabled without ``computer-use`` raises a clear validation error."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only precondition chain")

    mod = _import_cua_agent()
    with pytest.raises(SkillExecutionError, match="computer-use"):
        mod.validate_cua_agent_host(cfg=_enabled_config(computer_use=False))


def test_manager_omits_skill_when_disabled(tmp_path: Path) -> None:
    mod = _import_cua_agent()
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert mod.CUA_AGENT_SKILL_ID not in mgr._records


def test_manager_includes_skill_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Darwin":
        pytest.skip("macOS-only load path")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cua-driver", "cua"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    mod = _import_cua_agent()
    mgr = SkillsManager.shared(
        tmp_path,
        (BUNDLED_SKILLS_ROOT,),
        config=_enabled_config(),
    )
    assert mod.CUA_AGENT_SKILL_ID in mgr._records


def test_cua_agent_run_blocked_without_approval() -> None:
    """Autonomous loop requires explicit per-run operator approval (HITL)."""
    mod = _import_cua_agent()
    with pytest.raises(SkillExecutionError, match="approval"):
        mod.validate_cua_agent_run(cfg=_enabled_config(), approved=False)
