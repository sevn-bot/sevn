"""Bundled ``computer-use`` skill gates and Cua Driver MCP passthrough tests."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import pytest

from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.computer_use import (
    COMPUTER_USE_SKILL_ID,
    CUA_DRIVER_MCP_SERVER_ID,
    computer_use_config_enabled,
    gate_computer_use_core_skill,
    mcp_stdio_entry,
    merge_computer_use_mcp_server,
    resolve_cua_driver_command,
)
from sevn.skills.errors import SkillExecutionError
from sevn.skills.manager import SkillsManager

_SKILL_MD = BUNDLED_SKILLS_ROOT / "core" / COMPUTER_USE_SKILL_ID / "SKILL.md"


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    """Clear ``SkillsManager`` singletons between tests."""
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _enabled_config() -> WorkspaceConfig:
    """Return a workspace config with computer-use opt-in enabled."""
    return WorkspaceConfig(
        schema_version=1,
        skills={"computer_use": {"enabled": True}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def test_bundled_skill_manifest_exists() -> None:
    """Bundled core tree ships ``computer-use/SKILL.md``."""
    assert _SKILL_MD.is_file()
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "mcp_passthrough:" in text
    assert "skills.computer_use.enabled" in text
    assert not (BUNDLED_SKILLS_ROOT / "core" / COMPUTER_USE_SKILL_ID / "scripts").exists()


def test_computer_use_hidden_when_disabled(tmp_path: Path) -> None:
    """Default config keeps ``computer-use`` out of the skills index."""
    man = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert COMPUTER_USE_SKILL_ID not in man._records


def test_computer_use_loads_when_enabled_on_darwin_with_stub_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled gate loads the skill when Darwin + ``cua-driver`` preconditions pass."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only load path")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "cua-driver"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    man = SkillsManager.shared(
        tmp_path,
        (BUNDLED_SKILLS_ROOT,),
        config=_enabled_config(),
    )
    rec = man.get_record(COMPUTER_USE_SKILL_ID)
    assert rec.manifest.name == COMPUTER_USE_SKILL_ID
    assert rec.manifest.scripts == ()


def test_computer_use_fail_fast_non_darwin_when_enabled(tmp_path: Path) -> None:
    """Opt-in on non-Darwin hosts fails fast during core skill scan."""
    if platform.system() == "Darwin":
        pytest.skip("non-Darwin fail-fast path")

    with pytest.raises(SkillExecutionError, match="requires macOS"):
        SkillsManager.shared(
            tmp_path,
            (BUNDLED_SKILLS_ROOT,),
            config=_enabled_config(),
        )


def test_computer_use_fail_fast_missing_binary_on_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in on Darwin without ``cua-driver`` fails fast during core skill scan."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only missing-binary path")

    monkeypatch.setenv("PATH", "")
    with pytest.raises(SkillExecutionError, match="requires `cua-driver`"):
        SkillsManager.shared(
            tmp_path,
            (BUNDLED_SKILLS_ROOT,),
            config=_enabled_config(),
        )


def test_mcp_not_registered_when_disabled(tmp_path: Path) -> None:
    """Cua Driver MCP row is absent when the workspace flag is false."""
    servers = build_effective_mcp_servers(
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        tmp_path,
    )
    assert CUA_DRIVER_MCP_SERVER_ID not in servers


def test_mcp_registered_when_enabled_on_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled Darwin workspaces register ``cua-driver`` stdio MCP args."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only MCP registration path")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "cua-driver"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    doc: dict[str, object] = {}
    merge_computer_use_mcp_server(doc, workspace=_enabled_config())
    servers = doc.get("mcp_servers")
    assert isinstance(servers, dict)
    entry = servers.get(CUA_DRIVER_MCP_SERVER_ID)
    assert isinstance(entry, dict)
    assert entry.get("command") == "cua-driver"
    assert entry.get("args") == ["mcp"]

    effective = build_effective_mcp_servers(_enabled_config(), tmp_path)
    assert effective[CUA_DRIVER_MCP_SERVER_ID]["args"] == ["mcp"]


def test_resolve_cua_driver_command_honors_override() -> None:
    """Optional ``skills.computer_use.command`` overrides the default binary name."""
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"computer_use": {"enabled": True, "command": "/opt/cua/bin/driver"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert resolve_cua_driver_command(cfg) == "/opt/cua/bin/driver"


def test_gate_helpers() -> None:
    """Config gate helpers match the workspace flag semantics."""
    assert computer_use_config_enabled(None) is False
    assert gate_computer_use_core_skill(None) == "skip"
    assert (
        mcp_stdio_entry(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            )
        )
        is None
    )


@pytest.mark.integration
@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only integration")
def test_cua_driver_mcp_live() -> None:
    """Optional live smoke when ``SEVN_COMPUTER_USE_LIVE=1`` and ``cua-driver`` is installed."""
    if os.environ.get("SEVN_COMPUTER_USE_LIVE", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set SEVN_COMPUTER_USE_LIVE=1 to run live Cua Driver MCP smoke")

    entry = mcp_stdio_entry(_enabled_config())
    if entry is None:
        pytest.skip("computer-use MCP gated off")

    command = str(entry["command"])
    args = [str(a) for a in entry.get("args", [])]
    import shutil

    if shutil.which(command) is None:
        pytest.skip("cua-driver not installed on PATH")

    proc = subprocess.run(
        [command, *args],
        input=(
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
            '{"protocolVersion":"2024-11-05","capabilities":{},'
            '"clientInfo":{"name":"sevn-test","version":"0"}}}\n'
        ),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0 or "jsonrpc" in proc.stdout.lower() or proc.stdout.strip()


def _config_with_target(target: str) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={"computer_use": {"enabled": True, "target": target}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.mark.parametrize("target", ["host", "docker", "cloud", "lume"])
def test_resolve_computer_use_target_defaults_and_reads_config(target: str) -> None:
    """``skills.computer_use.target`` resolves to host by default or configured value."""
    from sevn.skills.computer_use import resolve_computer_use_target

    assert resolve_computer_use_target(None) == "host"
    assert resolve_computer_use_target(_config_with_target(target)) == target


def test_validate_computer_use_host_sandbox_target_requires_cua(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-host targets require ``cua`` on PATH instead of ``cua-driver``."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only host validation")

    monkeypatch.setenv("PATH", "")
    from sevn.skills.computer_use import validate_computer_use_host

    with pytest.raises(SkillExecutionError, match="`cua`"):
        validate_computer_use_host(cfg=_config_with_target("docker"))


@pytest.mark.parametrize("target", ["docker", "cloud", "lume"])
def test_mcp_merge_skipped_for_sandbox_targets(
    target: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``merge_computer_use_mcp_server`` injects ``cua-driver`` only for host target."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only MCP merge")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("cua-driver", "cua"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    doc: dict[str, object] = {}
    merge_computer_use_mcp_server(doc, workspace=_config_with_target(target))
    servers = doc.get("mcp_servers")
    if target == "host":
        assert isinstance(servers, dict)
        assert CUA_DRIVER_MCP_SERVER_ID in servers
    else:
        assert servers is None or CUA_DRIVER_MCP_SERVER_ID not in servers


def test_computer_use_snapshot_and_trajectory_readers() -> None:
    """Snapshot annotate and trajectory knobs expose W0.3 defaults."""
    from sevn.skills.computer_use import (
        computer_use_snapshot_annotate_enabled,
        computer_use_trajectory_export_dir,
        computer_use_trajectory_share_enabled,
    )

    cfg = WorkspaceConfig(
        schema_version=1,
        skills={
            "computer_use": {
                "enabled": True,
                "snapshot": {"annotate": True},
                "trajectory": {"share": False, "export_dir": "/tmp/traj"},
            }
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert computer_use_snapshot_annotate_enabled(None) is False
    assert computer_use_snapshot_annotate_enabled(cfg) is True
    assert computer_use_trajectory_share_enabled(cfg) is False
    assert computer_use_trajectory_export_dir(cfg) == "/tmp/traj"
