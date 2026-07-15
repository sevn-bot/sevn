"""Tests for ``social_media_manager`` specialist + TwexAPI medium."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.social_media_worker import (
    DEFAULT_SOCIAL_MEDIA_MANAGER_SKILLS,
    DEFAULT_SOCIAL_MEDIA_MANAGER_TOOLS,
    SocialMediaManagerError,
    assigned_skills_for,
    assigned_tools_for,
    execute_social_media_manager_task,
    parse_social_media_task,
    require_social_media_manager,
)
from sevn.agent.subagents.specialists import merge_specialist_grants
from sevn.agent.subagents.supervisor import SubAgentSupervisor
from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path
from sevn.tools.context import ToolContext
from sevn.tools.subagent_spawn import spawn_subagent_tool

_SMM_CFG = SubAgentsWorkspaceConfig(
    specialists={
        "social_media_manager": SpecialistConfig(
            model="gpt-4o-mini",
            provider="openai",
            assigned_to=["tier_b"],
            requestable_by=["triager", "tier_b"],
            max_concurrent=2,
            skill="social_media_manager",
            skills=list(DEFAULT_SOCIAL_MEDIA_MANAGER_SKILLS),
            tools=list(DEFAULT_SOCIAL_MEDIA_MANAGER_TOOLS),
        ),
    },
)


@pytest.fixture
def smm_workspace(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """Minimal workspace with migrated DB and sevn.json stub."""
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True)
    conn = sqlite3.connect(str(sevn_db_path(dot_sevn)))
    apply_migrations(conn)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "test-token"},
                "skills": {
                    "social_media_manager": {
                        "twexapi": {"api_key": "sk-test-twex"},
                    },
                },
                "subagents": {
                    "specialists": {
                        "social_media_manager": {
                            "model": "gpt-4o-mini",
                            "provider": "openai",
                            "assigned_to": ["tier_b"],
                            "requestable_by": ["triager", "tier_b"],
                            "max_concurrent": 2,
                            "skill": "social_media_manager",
                            "skills": list(DEFAULT_SOCIAL_MEDIA_MANAGER_SKILLS),
                            "tools": list(DEFAULT_SOCIAL_MEDIA_MANAGER_TOOLS),
                        },
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    return tmp_path, conn


def _ctx(
    *,
    supervisor: SubAgentSupervisor | None,
    parent_id: str | None = "l1-parent",
    workspace: Path | None = None,
) -> ToolContext:
    return ToolContext(
        session_id="sess-smm",
        workspace_path=workspace or Path("/tmp/w"),
        workspace_id="w1",
        registry_version=1,
        delivery_channel="telegram",
        subagent_supervisor=supervisor,
        subagent_role="tier_b",
        subagent_parent_id=parent_id,
    )


async def _register_parent(registry: SubAgentRegistry) -> str:
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="sess-smm",
        channel="telegram",
        task_summary="parent",
    )
    await registry.mark_running(run.id)
    return run.id


class TestParseSocialMediaTask:
    """Unit tests for task parsing."""

    def test_json_capabilities(self) -> None:
        task = parse_social_media_task('{"medium":"capabilities"}')
        assert task.medium == "capabilities"

    def test_shorthand_twexapi(self) -> None:
        task = parse_social_media_task("twexapi:search")
        assert task.medium == "twexapi"
        assert task.op == "search"

    def test_browser_plan_fields(self) -> None:
        task = parse_social_media_task(
            '{"medium":"browser","op":"search","site":"x","query":"ai"}',
        )
        assert task.site == "x"
        assert task.query == "ai"


class TestToolkitAssignment:
    """Assigned skills/tools defaults and grants."""

    def test_defaults_when_skill_bound(self) -> None:
        spec = SpecialistConfig(
            model="gpt-4o-mini",
            provider="openai",
            skill="social_media_manager",
        )
        assert "browser" in assigned_tools_for(spec)
        assert "x-use" in assigned_skills_for(spec)
        assert "playwright-browser" in assigned_skills_for(spec)

    def test_merge_grants_from_skill_name(self) -> None:
        grants = merge_specialist_grants([], ["social_media_manager"], _SMM_CFG)
        assert grants == frozenset({"social_media_manager"})

    def test_require_unconfigured(self) -> None:
        with pytest.raises(SocialMediaManagerError, match="social_media_manager"):
            require_social_media_manager(None)


class TestCapabilitiesAndBrowser:
    """Capabilities listing and browser medium plan."""

    @pytest.mark.asyncio
    async def test_capabilities(self, smm_workspace: tuple[Path, sqlite3.Connection]) -> None:
        workspace, _conn = smm_workspace
        result = await execute_social_media_manager_task(
            "capabilities",
            content_root=workspace,
            subagents_cfg=_SMM_CFG,
        )
        assert result["medium"] == "capabilities"
        assert "browser" in result["tools"]
        assert "x-use" in result["skills"]
        assert "twexapi" in result["media"]
        assert result["media"]["browser"]["engine"] == "cdp"

    @pytest.mark.asyncio
    async def test_browser_plan(self, smm_workspace: tuple[Path, sqlite3.Connection]) -> None:
        workspace, _conn = smm_workspace
        result = await execute_social_media_manager_task(
            '{"medium":"browser","op":"search","site":"x","query":"bots"}',
            content_root=workspace,
            subagents_cfg=_SMM_CFG,
        )
        assert result["tool"] == "browser"
        assert result["action"] == "social"
        assert result["site"] == "x"


class TestTwexApiMedium:
    """TwexAPI execution with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_search_op(self, smm_workspace: tuple[Path, sqlite3.Connection]) -> None:
        workspace, _conn = smm_workspace

        async def _fake_call_op(
            self: Any,
            op: str,
            *,
            params: dict[str, Any] | None = None,
            body: dict[str, Any] | None = None,
            path_params: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            _ = self, params, path_params
            assert op == "search"
            assert body is not None
            assert "searchTerms" in body
            return {"tweets": [{"id": "1", "text": "hello"}]}

        with patch(
            "sevn.agent.subagents.social_media_worker.TwexApiClient.call_op",
            new=_fake_call_op,
        ):
            result = await execute_social_media_manager_task(
                '{"medium":"twexapi","op":"search","query":"hello"}',
                content_root=workspace,
                subagents_cfg=_SMM_CFG,
            )
        assert result["medium"] == "twexapi"
        assert result["data"]["tweets"][0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_unconfigured_specialist(self, tmp_path: Path) -> None:
        with pytest.raises(SocialMediaManagerError, match="social_media_manager"):
            await execute_social_media_manager_task(
                "capabilities",
                content_root=tmp_path,
                subagents_cfg=SubAgentsWorkspaceConfig(),
            )

    @pytest.mark.asyncio
    async def test_users_sends_array_body(
        self,
        smm_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = smm_workspace
        captured: dict[str, Any] = {}

        async def _fake_call_op(
            self: Any,
            op: str,
            *,
            params: dict[str, Any] | None = None,
            body: dict[str, Any] | list[Any] | None = None,
            path_params: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            _ = self, params, path_params
            captured["op"] = op
            captured["body"] = body
            return {"users": [{"username": "elonmusk"}]}

        with patch(
            "sevn.agent.subagents.social_media_worker.TwexApiClient.call_op",
            new=_fake_call_op,
        ):
            result = await execute_social_media_manager_task(
                '{"medium":"twexapi","op":"users","query":"elonmusk"}',
                content_root=workspace,
                subagents_cfg=_SMM_CFG,
            )
        assert captured["op"] == "users"
        assert captured["body"] == ["elonmusk"]
        assert result["data"]["users"][0]["username"] == "elonmusk"


class TestSpawnPath:
    """End-to-end spawn wait path."""

    @pytest.mark.asyncio
    async def test_spawn_wait_capabilities(
        self,
        smm_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = smm_workspace
        registry = SubAgentRegistry()
        supervisor = SubAgentSupervisor(registry, config=_SMM_CFG)
        parent_id = await _register_parent(registry)
        ctx = _ctx(supervisor=supervisor, parent_id=parent_id, workspace=workspace)
        raw = await spawn_subagent_tool(
            ctx,
            task='{"medium":"capabilities"}',
            specialist="social_media_manager",
            wait=True,
        )
        envelope = json.loads(raw)
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "done"
        result = json.loads(envelope["data"]["result"])
        assert result["specialist"] == "social_media_manager"
        assert "browser" in result["tools"]
