"""Progressive ``load_skill`` menu payloads (`specs/12` §2.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.defaults import (
    LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES,
    TOOL_LARGE_RESULT_THRESHOLD_BYTES,
)
from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.manager import SkillsManager
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _write_skill(
    skill_dir: Path,
    *,
    body: str,
    with_contract_marker: bool = False,
) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run.py").write_text("print('{}')", encoding="utf-8")
    name = skill_dir.name
    marker = "\n\n# SKILL CONTRACT\n\nbulk\n" if with_contract_marker else ""
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: demo\n"
        f"version: 1.0.0\n"
        f"scripts:\n"
        f"  - path: scripts/run.py\n"
        f"    description: main\n"
        f"---\n"
        f"{body}{marker}",
        encoding="utf-8",
    )


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=7,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_menu_mode_small_skill_returns_full_markdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_skill(skills / "user" / "tiny", body="short intro")
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (skills,),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    payload = await manager.build_load_skill_payload("tiny")
    assert payload["ok"] is True
    data = payload["data"]
    assert data["markdown_truncated"] is False
    assert "short intro" in data["markdown"]


@pytest.mark.asyncio
async def test_menu_mode_large_skill_truncates_under_spill_threshold(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    bulk = "x" * 50_000
    _write_skill(skills / "user" / "big", body="intro\n", with_contract_marker=True)
    skill_md = skills / "user" / "big" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace("bulk", bulk), encoding="utf-8"
    )
    refs = skills / "user" / "big" / "references"
    refs.mkdir()
    (refs / "contract.md").write_text("law", encoding="utf-8")
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (skills,),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    payload = await manager.build_load_skill_payload("big")
    assert payload["ok"] is True
    data = payload["data"]
    assert data["markdown_truncated"] is True
    assert "# SKILL CONTRACT" not in data["markdown"]
    assert data["skill_md_path"] == "skills/user/big/SKILL.md"
    assert "skills/user/big/references/contract.md" in data["references"]
    assert data["load_hint"]
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    assert len(serialized.encode("utf-8")) < TOOL_LARGE_RESULT_THRESHOLD_BYTES
    assert len(data["markdown"].encode("utf-8")) <= LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES


@pytest.mark.asyncio
async def test_full_mode_returns_entire_markdown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    bulk = "y" * 50_000
    _write_skill(skills / "user" / "big", body="intro\n", with_contract_marker=True)
    skill_md = skills / "user" / "big" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace("bulk", bulk), encoding="utf-8"
    )
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (skills,),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    payload = await manager.build_load_skill_payload("big", full=True)
    data = payload["data"]
    assert data["markdown_truncated"] is False
    assert bulk in data["markdown"]


@pytest.mark.asyncio
async def test_load_skill_tool_passes_full_flag(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_skill(skills / "user" / "big", body="z" * 50_000)
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (skills,),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, _tool_set = build_session_registry(registry_version=7, skills_manager=manager)
    menu = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(name="load_skill", arguments={"name": "big"}),
        ),
    )
    full_payload = await manager.build_load_skill_payload("big", full=True)
    assert menu["data"]["markdown_truncated"] is True
    assert full_payload["data"]["markdown_truncated"] is False
    assert len(full_payload["data"]["markdown"]) > len(menu["data"]["markdown"])
