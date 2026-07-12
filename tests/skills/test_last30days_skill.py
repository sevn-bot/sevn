"""Bundled ``last30days`` skill tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sevn.config.defaults import (
    LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES,
    TOOL_LARGE_RESULT_THRESHOLD_BYTES,
)
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager
from sevn.skills.manifest import parse_skill_markdown
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "last30days"
)
_RESEARCH_SCRIPT = _SKILL_ROOT / "scripts" / "research.py"
_ENGINE_SCRIPT = _SKILL_ROOT / "scripts" / "last30days.py"

_EXPECTED_EGRESS = (
    "reddit.com",
    "redd.it",
    "old.reddit.com",
    "news.ycombinator.com",
    "polymarket.com",
    "github.com",
    "api.github.com",
    "x.com",
    "twitter.com",
    "twimg.com",
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "tiktok.com",
    "tiktokcdn.com",
    "instagram.com",
    "cdninstagram.com",
    "threads.net",
    "bsky.app",
    "api.scrapecreators.com",
    "openrouter.ai",
    "search.brave.com",
    "api.search.brave.com",
)


def _run_research(
    workspace: Path,
    cli_args: list[str],
    *,
    skill_dir: Path | None = None,
) -> tuple[int, dict[str, object]]:
    """Run ``research.py`` and parse its JSON stdout envelope."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    env["SEVN_SKILL_DIR"] = str(skill_dir or _SKILL_ROOT)
    env.pop("SEVN_LAST30DAYS_DRY_RUN", None)
    proc = subprocess.run(
        [sys.executable, str(_RESEARCH_SCRIPT), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_manifest_parses_with_research_script() -> None:
    """Bundled SKILL.md validates and declares the research wrapper."""
    manifest = parse_skill_markdown(
        (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"),
        provenance="core",
    )
    assert manifest.name == "last30days"
    assert manifest.version == "3.3.2"
    assert manifest.max_wall_seconds == 900
    script_paths = [s.path for s in manifest.scripts]
    assert "scripts/research.py" in script_paths
    assert len(script_paths) >= 1


def test_engine_help_exits_zero() -> None:
    """Vendored ``last30days.py`` is present and exposes CLI help."""
    proc = subprocess.run(
        [sys.executable, str(_ENGINE_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--emit" in proc.stdout


def test_research_dry_run_returns_json_plan(tmp_path: Path) -> None:
    """``research.py --dry-run`` emits a sevn tool envelope with argv plan."""
    code, payload = _run_research(
        tmp_path,
        ["--dry-run", "--topic", "sevn.bot", "--emit", "compact"],
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("topic") == "sevn.bot"
    argv = data.get("argv")
    assert isinstance(argv, list)
    assert str(_ENGINE_SCRIPT) in argv[1]
    assert argv[-1] == "sevn.bot"
    memory_dir = data.get("memory_dir")
    assert isinstance(memory_dir, str)
    assert memory_dir.endswith("out/last30days")


def test_egress_domains_match_skill_frontmatter() -> None:
    """Frontmatter ``egress:`` rows match the bundled allowlist snapshot."""
    skill_md = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill_md.split("---", 2)[1]
    parsed = yaml.safe_load(frontmatter) or {}
    yaml_domains = parsed.get("egress") or []
    assert tuple(yaml_domains) == _EXPECTED_EGRESS


def test_upstream_version_file_present() -> None:
    """Vendored tree records upstream sync metadata."""
    version_file = _SKILL_ROOT / "UPSTREAM_VERSION"
    assert version_file.is_file()
    text = version_file.read_text(encoding="utf-8")
    assert "version=3.3.2" in text or "version=" in text


def test_skill_md_fits_inline_load_budget() -> None:
    """Bundled ``SKILL.md`` stays under the menu ``load_skill`` inline byte budget."""
    skill_md = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert len(skill_md.encode("utf-8")) < LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES
    assert len(skill_md.encode("utf-8")) < 8_192


def test_contract_reference_present() -> None:
    """Research LAWs live in ``references/contract.md``, not the menu ``SKILL.md``."""
    contract = (_SKILL_ROOT / "references" / "contract.md").read_text(encoding="utf-8")
    assert "SKILL CONTRACT" in contract
    assert "BADGE" in contract
    skill_md = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "SKILL CONTRACT — READ BEFORE ANY TOOL CALL" not in skill_md


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


@pytest.mark.asyncio
async def test_load_skill_menu_inline_without_spill(tmp_path: Path) -> None:
    """``load_skill(last30days)`` returns full menu inline (no spill envelope)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = SkillsManager.shared(workspace, (BUNDLED_SKILLS_ROOT,))
    executor, _tool_set = build_session_registry(registry_version=7, skills_manager=manager)
    ctx = ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=7,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(name="load_skill", arguments={"name": "last30days"}),
        ),
    )
    assert envelope["ok"] is True
    data = envelope["data"]
    assert "spill_path" not in data
    assert data.get("markdown_truncated") is False
    assert "references/contract.md" in data["markdown"]
    serialized = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
    assert len(serialized.encode("utf-8")) < TOOL_LARGE_RESULT_THRESHOLD_BYTES
