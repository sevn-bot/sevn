"""Tests for ``social_media_manager`` specialist, skill scripts, and spawn path."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path

_DEFAULT_SKILLS = (
    "social_media_manager",
    "browser-harness",
    "last30days",
    "yt-dlp",
    "media_generation",
    "scheduling",
)
_DEFAULT_TOOLS = (
    "browser",
    "get_page_content",
    "web_fetch",
    "web_search",
    "serp",
    "load_skill",
    "run_skill_script",
    "send_file",
    "message",
)


def _import_worker() -> Any:
    from sevn.agent.subagents import social_media_worker as mod

    return mod


def _smm_subagents_cfg() -> Any:
    from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig

    return SubAgentsWorkspaceConfig(
        specialists={
            "social_media_manager": SpecialistConfig(
                model="gpt-4o-mini",
                provider="openai",
                assigned_to=["tier_b"],
                requestable_by=["triager", "tier_b"],
                max_concurrent=2,
                skill="social_media_manager",
                skills=list(_DEFAULT_SKILLS),
                tools=list(_DEFAULT_TOOLS),
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
                        "default_medium": "browser",
                        "twexapi": {"enabled": True, "api_key": "sk-test-twex"},
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
                            "skills": list(_DEFAULT_SKILLS),
                            "tools": list(_DEFAULT_TOOLS),
                        },
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    return tmp_path, conn


class TestParseSocialMediaTask:
    """Unit tests for task parsing (PR #22 baseline + D2 default browser)."""

    def test_json_capabilities(self) -> None:
        worker = _import_worker()
        task = worker.parse_social_media_task('{"medium":"capabilities"}')
        assert task.medium == "capabilities"

    def test_shorthand_twexapi(self) -> None:
        worker = _import_worker()
        task = worker.parse_social_media_task("twexapi:search")
        assert task.medium == "twexapi"
        assert task.op == "search"

    def test_browser_plan_fields(self) -> None:
        worker = _import_worker()
        task = worker.parse_social_media_task(
            '{"medium":"browser","op":"search","site":"x","query":"ai"}',
        )
        assert task.site == "x"
        assert task.query == "ai"

    def test_omitted_medium_leaves_resolution_to_config(self) -> None:
        """Omitted JSON medium is unset so D2 config defaults apply (thermos i4 M2)."""
        worker = _import_worker()
        task = worker.parse_social_media_task('{"op":"search","site":"x","query":"ai"}')
        assert task.medium is None
        task_dict = worker._task_dict_for_resolution(
            '{"op":"search","site":"x","query":"ai"}',
            task,
        )
        assert "medium" not in task_dict


class TestToolkitAssignment:
    """Assigned skills/tools defaults and grants."""

    def test_defaults_when_skill_bound(self) -> None:
        worker = _import_worker()
        from sevn.config.sections.subagents import SpecialistConfig

        spec = SpecialistConfig(
            model="gpt-4o-mini",
            provider="openai",
            skill="social_media_manager",
        )
        assert "browser" in worker.assigned_tools_for(spec)
        assert "social_media_manager" in worker.assigned_skills_for(spec)
        assert "browser-harness" in worker.assigned_skills_for(spec)

    def test_merge_grants_from_skill_name(self) -> None:
        from sevn.agent.subagents.specialists import merge_specialist_grants

        grants = merge_specialist_grants([], ["social_media_manager"], _smm_subagents_cfg())
        assert grants == frozenset({"social_media_manager"})

    def test_require_unconfigured(self) -> None:
        worker = _import_worker()
        with pytest.raises(worker.SocialMediaManagerError, match="social_media_manager"):
            worker.require_social_media_manager(None)


class TestCapabilitiesAndBrowser:
    """Capabilities listing and browser medium plan."""

    @pytest.mark.asyncio
    async def test_capabilities(self, smm_workspace: tuple[Path, sqlite3.Connection]) -> None:
        worker = _import_worker()
        workspace, _conn = smm_workspace
        result = await worker.execute_social_media_manager_task(
            "capabilities",
            content_root=workspace,
            subagents_cfg=_smm_subagents_cfg(),
        )
        assert result["medium"] == "capabilities"
        assert "browser" in result["tools"]
        assert "social_media_manager" in result["skills"]

    @pytest.mark.asyncio
    async def test_browser_plan(self, smm_workspace: tuple[Path, sqlite3.Connection]) -> None:
        worker = _import_worker()
        workspace, _conn = smm_workspace
        result = await worker.execute_social_media_manager_task(
            '{"medium":"browser","op":"search","site":"x","query":"bots"}',
            content_root=workspace,
            subagents_cfg=_smm_subagents_cfg(),
        )
        assert result["tool"] == "browser"
        assert result["action"] == "social"
        assert result["site"] == "x"


class TestTwexApiMedium:
    """TwexAPI execution with mocked HTTP (X-only after W1b)."""

    @pytest.mark.asyncio
    async def test_search_op(self, smm_workspace: tuple[Path, sqlite3.Connection]) -> None:
        worker = _import_worker()
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

        with patch.object(worker.TwexApiClient, "call_op", _fake_call_op):
            result = await worker.execute_social_media_manager_task(
                '{"medium":"twexapi","op":"search","site":"x","query":"hello"}',
                content_root=workspace,
                subagents_cfg=_smm_subagents_cfg(),
            )
        assert result["medium"] == "twexapi"
        assert result["data"]["tweets"][0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_unconfigured_specialist(self, tmp_path: Path) -> None:
        worker = _import_worker()
        from sevn.config.sections.subagents import SubAgentsWorkspaceConfig

        with pytest.raises(worker.SocialMediaManagerError, match="social_media_manager"):
            await worker.execute_social_media_manager_task(
                "capabilities",
                content_root=tmp_path,
                subagents_cfg=SubAgentsWorkspaceConfig(),
            )


class TestSpawnPath:
    """End-to-end spawn wait path."""

    @pytest.mark.asyncio
    async def test_spawn_wait_capabilities(
        self,
        smm_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        from sevn.agent.subagents.registry import SubAgentRegistry
        from sevn.agent.subagents.supervisor import SubAgentSupervisor
        from sevn.tools.context import ToolContext
        from sevn.tools.subagent_spawn import spawn_subagent_tool

        workspace, _conn = smm_workspace
        registry = SubAgentRegistry()
        supervisor = SubAgentSupervisor(registry, config=_smm_subagents_cfg())
        run = await registry.register(
            level=1,
            role="tier_b",
            session_id="sess-smm",
            channel="telegram",
            task_summary="parent",
        )
        await registry.mark_running(run.id)
        ctx = ToolContext(
            session_id="sess-smm",
            workspace_path=workspace,
            workspace_id="w1",
            registry_version=1,
            delivery_channel="telegram",
            subagent_supervisor=supervisor,
            subagent_role="tier_b",
            subagent_parent_id=run.id,
        )
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


class TestSessionStatusScript:
    """W1.7 — session_status.py readiness without secret leakage (D10)."""

    def test_session_status_no_secret_values(
        self,
        smm_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = smm_workspace
        script = (
            Path(__file__).resolve().parents[2]
            / "src/sevn/data/bundled_skills/core/social_media_manager/scripts/session_status.py"
        )
        assert script.is_file(), "session_status.py missing until bundled skill lands"
        env = {**dict(os.environ), "SEVN_WORKSPACE": str(workspace)}
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=workspace,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload.get("ok") is True
        data = payload["data"]
        assert "twexapi" in data
        assert "browser" in data
        twex = data["twexapi"]
        assert "api_key" not in twex
        assert "sk-test" not in proc.stdout
        assert twex.get("api_key_ref_configured") in (True, False)
        assert "secret_alias" in twex
        browser = data["browser"]
        assert browser.get("engine") == "cdp"
        assert "cdp_reachable" in browser
