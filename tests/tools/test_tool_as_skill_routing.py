"""Tools-vs-skills routing (live-session W3): SKILL_IS_ACTUALLY_TOOL + optional auto-route."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.errors import SKILL_IS_ACTUALLY_TOOL
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


def _ctx(workspace: Path, *, known_tools: frozenset[str]) -> ToolContext:
    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=7,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        known_tool_names=known_tools,
    )


@pytest.mark.asyncio
async def test_run_skill_runnable_serp_returns_skill_is_actually_tool(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills").mkdir()
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (workspace / "skills",),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, tool_set = build_session_registry(
        registry_version=7,
        skills_manager=manager,
    )
    known = frozenset(td.name for td in (*tool_set.native, *tool_set.mcp))
    assert "serp" in known

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace, known_tools=known),
            ToolCall(
                name="run_skill_runnable",
                arguments={"skill": "serp", "runnable": "search", "payload": {"query": "test"}},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_IS_ACTUALLY_TOOL
    assert envelope["did_you_mean_tool"] == "serp"
    assert "call `serp" in envelope["error"]
    assert "run_skill" in envelope["error"]


@pytest.mark.asyncio
async def test_run_skill_script_serp_returns_skill_is_actually_tool(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills").mkdir()
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (workspace / "skills",),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, tool_set = build_session_registry(
        registry_version=7,
        skills_manager=manager,
    )
    known = frozenset(td.name for td in (*tool_set.native, *tool_set.mcp))

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace, known_tools=known),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "serp", "script": "noop.py"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_IS_ACTUALLY_TOOL
    assert envelope["did_you_mean_tool"] == "serp"


@pytest.mark.asyncio
async def test_run_skill_runnable_auto_route_when_flag_on(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills").mkdir()
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "tool_as_skill_auto_route": True,
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    manager = SkillsManager.shared(
        workspace,
        (workspace / "skills",),
        layout=layout,
        config=cfg,
    )
    executor, tool_set = build_session_registry(
        registry_version=7,
        skills_manager=manager,
        workspace_config=cfg,
    )
    known = frozenset(td.name for td in (*tool_set.native, *tool_set.mcp))
    fake_rows = [{"title": "Hit", "href": "https://example.com", "body": "snippet"}]

    with (
        patch("sevn.tools.web._HAS_DDGS", True),
        patch("sevn.tools.web._serp_search_sync", return_value=fake_rows),
    ):
        envelope = json.loads(
            await executor.dispatch(
                _ctx(workspace, known_tools=known),
                ToolCall(
                    name="run_skill_runnable",
                    arguments={
                        "skill": "serp",
                        "runnable": "ignored",
                        "payload": {"query": "hello", "count": 1},
                    },
                ),
            ),
        )

    assert envelope["ok"] is True
    assert envelope["data"]["count"] == 1
    assert "Auto-routed" in str(envelope.get("message", ""))


@pytest.mark.asyncio
async def test_scheduling_empty_runnables_hint_uses_run_skill_script(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, _tool_set = build_session_registry(
        registry_version=7,
        skills_manager=manager,
        workspace_root=workspace,
        layout=layout,
        workspace_config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace, known_tools=frozenset()),
            ToolCall(
                name="run_skill_runnable",
                arguments={"skill": "scheduling", "runnable": "cron_status"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert "run_skill_script" in envelope["error"]
    assert "[]" in envelope["error"]


def test_tier_b_tools_vs_skills_prompt_names_web_tools() -> None:
    from sevn.prompts.tier_b import tier_b_tools_vs_skills_prompt

    block = tier_b_tools_vs_skills_prompt()
    for name in ("serp", "web_search", "get_page_content", "web_fetch"):
        assert name in block
    assert "SKILL_IS_ACTUALLY_TOOL" in block
    assert "run_skill_runnable" in block
