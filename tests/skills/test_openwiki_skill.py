"""Bundled ``openwiki`` skill script subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager
from sevn.skills.openwiki import OPENWIKI_SKILL_ID, gate_openwiki_core_skill

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "openwiki"
)
_GENERATE_SCRIPT = _SKILL_ROOT / "scripts" / "generate.py"
_STATUS_SCRIPT = _SKILL_ROOT / "scripts" / "status.py"


def _enabled_config() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={"openwiki": {"enabled": True}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _install_fake_openwiki(tmp_path: Path, *, stdout: bytes = b"openwiki run complete") -> Path:
    """Write a stub ``openwiki`` executable under ``tmp_path/bin`` for subprocess tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    openwiki = bin_dir / "openwiki"
    openwiki.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.buffer.write({stdout!r})\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    openwiki.chmod(0o755)
    return bin_dir


def _run_generate(
    workspace: Path,
    cli_args: list[str],
    *,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run ``generate.py`` and parse its JSON stdout envelope."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    env.pop("SEVN_OPENWIKI_DRY_RUN", None)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(_GENERATE_SCRIPT), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def _run_status(
    workspace: Path,
    cli_args: list[str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run ``status.py`` and parse its JSON stdout envelope."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(_STATUS_SCRIPT), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_gate_skips_when_disabled() -> None:
    """Opt-in gate returns skip when config is absent."""
    assert gate_openwiki_core_skill(None) == "skip"


def test_gate_loads_when_enabled() -> None:
    """Opt-in gate returns load when ``skills.openwiki.enabled`` is true."""
    assert gate_openwiki_core_skill(_enabled_config()) == "load"


def test_manager_omits_skill_when_disabled(tmp_path: Path) -> None:
    """SkillsManager excludes openwiki when not enabled in workspace config."""
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert OPENWIKI_SKILL_ID not in mgr._records


def test_manager_includes_skill_when_enabled(tmp_path: Path) -> None:
    """SkillsManager includes openwiki when enabled in workspace config."""
    mgr = SkillsManager.shared(
        tmp_path,
        (BUNDLED_SKILLS_ROOT,),
        config=_enabled_config(),
    )
    assert OPENWIKI_SKILL_ID in mgr._records


def test_generate_dry_run_uses_content_root_over_shadow_workspace(tmp_path: Path) -> None:
    """Dry-run resolves repo root from ``SEVN_CONTENT_ROOT``, not shadow ``SEVN_WORKSPACE``."""
    content_root = tmp_path / "content"
    source_code = content_root / "source_code"
    source_code.mkdir(parents=True)
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(shadow)
    env["SEVN_CONTENT_ROOT"] = str(content_root)
    proc = subprocess.run(
        [sys.executable, str(_GENERATE_SCRIPT), "--dry-run", "--mode", "init"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    assert proc.returncode == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("root") == str(source_code.resolve())


def test_generate_dry_run_init_argv(tmp_path: Path) -> None:
    """``generate.py --dry-run`` returns argv plan without invoking openwiki."""
    code, payload = _run_generate(tmp_path, ["--dry-run", "--mode", "init"])
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("argv") == ["openwiki", "--init", "-p"]


def test_generate_dry_run_update_with_message(tmp_path: Path) -> None:
    """Dry-run update mode includes the user message in argv."""
    code, payload = _run_generate(
        tmp_path,
        ["--dry-run", "--mode", "update", "--message", "refresh docs"],
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("argv") == ["openwiki", "--update", "-p", "refresh docs"]


def test_generate_missing_openwiki_returns_dependency_envelope(tmp_path: Path) -> None:
    """Live mode without ``openwiki`` on PATH returns ``DEPENDENCY_MISSING``."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    env["PATH"] = ""
    proc = subprocess.run(
        [sys.executable, str(_GENERATE_SCRIPT), "--mode", "init", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    assert proc.returncode == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "DEPENDENCY_MISSING"
    assert "openwiki" in str(payload.get("error", ""))


def test_generate_live_with_fake_openwiki(tmp_path: Path) -> None:
    """Live mode runs stub ``openwiki`` when present on PATH."""
    fake_bin = _install_fake_openwiki(tmp_path)
    code, payload = _run_generate(
        tmp_path,
        ["--mode", "chat", "--message", "hello", "--root", str(tmp_path)],
        path_prefix=fake_bin,
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "live"
    assert data.get("run_mode") == "chat"
    assert "openwiki run complete" in str(data.get("stdout", ""))


def test_status_absent_wiki(tmp_path: Path) -> None:
    """``status.py`` reports missing wiki directory."""
    code, payload = _run_status(tmp_path, ["--root", str(tmp_path)])
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("exists") is False


def test_status_present_wiki(tmp_path: Path) -> None:
    """``status.py`` detects an existing ``openwiki/`` tree."""
    wiki = tmp_path / "openwiki"
    wiki.mkdir()
    (wiki / "page.md").write_text("# Page\n", encoding="utf-8")
    code, payload = _run_status(tmp_path, ["--root", str(tmp_path)])
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("exists") is True
    assert data.get("page_count") == 1


@pytest.mark.skipif(
    os.environ.get("SEVN_OPENWIKI_LIVE") != "1",
    reason="set SEVN_OPENWIKI_LIVE=1 to run real openwiki smoke",
)
def test_generate_live_real_openwiki(tmp_path: Path) -> None:
    """Optional live smoke against a real ``openwiki`` CLI when installed."""
    from shutil import which

    if which("openwiki") is None:
        pytest.skip("openwiki CLI not installed")
    code, payload = _run_generate(
        tmp_path,
        ["--mode", "chat", "--message", "Summarize what OpenWiki can do", "--root", str(tmp_path)],
    )
    assert code == 0
    assert payload.get("ok") is True
