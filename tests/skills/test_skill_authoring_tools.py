"""Wave 5 contract tests for ``skill_create`` and ``promote_generated_skill`` tools."""

from __future__ import annotations

import json
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.errors import SKILL_QUARANTINED
from sevn.skills.manager import SkillsManager
from sevn.tools.base import ToolCall
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _ctx(
    workspace: Path,
    *,
    human_acknowledged_tools: frozenset[str] = frozenset(),
) -> ToolContext:
    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=7,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        human_acknowledged_tools=human_acknowledged_tools,
    )


def _attach_runnable_script(skill_dir: Path, manager: SkillsManager) -> None:
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run.py").write_text(
        textwrap.dedent(
            """\
            import json
            print(json.dumps({"ok": True, "data": {"echo": "auth-ok"}, "message": None}), flush=True)
            """
        ),
        encoding="utf-8",
    )
    name = skill_dir.name
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: demo auth skill
            version: 0.1.0
            quarantine: true
            scripts:
              - path: scripts/run.py
                description: main
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    manager.reload()


@pytest.mark.asyncio
async def test_skill_authoring_scaffold_quarantine_promote_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    skills.mkdir()
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (skills,),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, _tool_set = build_session_registry(
        registry_version=7,
        skills_manager=manager,
    )
    ctx = _ctx(workspace)

    create_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="skill_create",
                arguments={"name": "auth_demo", "description": "demo auth skill"},
            ),
        ),
    )
    assert create_env["ok"] is True
    assert create_env["data"]["quarantine"] is True
    gen_dir = skills / "generated" / "auth_demo"
    assert gen_dir.is_dir()
    assert (gen_dir / "scripts").is_dir()

    _attach_runnable_script(gen_dir, manager)
    rv_before = manager.registry_version

    quarantine_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "auth_demo", "script": "scripts/run.py"},
            ),
        ),
    )
    assert quarantine_env["ok"] is False
    assert quarantine_env["code"] == SKILL_QUARANTINED

    blocked_promote = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(name="promote_generated_skill", arguments={"name": "auth_demo"}),
        ),
    )
    assert blocked_promote["ok"] is False
    assert blocked_promote["code"] == ToolResultCode.PLAN_HUMAN_GATE

    ctx_ack = replace(ctx, human_acknowledged_tools=frozenset({"promote_generated_skill"}))
    promote_env = json.loads(
        await executor.dispatch(
            ctx_ack,
            ToolCall(name="promote_generated_skill", arguments={"name": "auth_demo"}),
        ),
    )
    assert promote_env["ok"] is True
    assert (skills / "user" / "auth_demo").is_dir()
    assert not gen_dir.exists()
    assert int(manager.registry_version) >= int(rv_before)

    run_env = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "auth_demo", "script": "scripts/run.py"},
            ),
        ),
    )
    assert run_env["ok"] is True
    assert run_env["data"]["echo"] == "auth-ok"


@pytest.mark.asyncio
async def test_promote_blocked_on_skillspector_high_critical(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """HIGH/CRITICAL SkillSpector findings block promote unless force=true."""
    from sevn.skills.errors import QUARANTINE_SECURITY
    from sevn.skills.security_scan import ScanIssue, ScanResult

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    skills.mkdir()
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
    ctx_ack = _ctx(workspace, human_acknowledged_tools=frozenset({"promote_generated_skill"}))

    create_env = json.loads(
        await executor.dispatch(
            ctx_ack,
            ToolCall(
                name="skill_create",
                arguments={"name": "risky", "description": "risky skill"},
            ),
        ),
    )
    assert create_env["ok"] is True
    gen_dir = skills / "generated" / "risky"
    _attach_runnable_script(gen_dir, manager)

    def _fake_scan(path: Path, **kwargs: object) -> ScanResult:
        return ScanResult(
            path=path,
            issues=[ScanIssue("P1", "CRITICAL", file="SKILL.md")],
            risk_score=100,
            risk_severity="CRITICAL",
        )

    monkeypatch.setattr("sevn.tools.skills_register.scan_skill_path", _fake_scan)

    blocked = json.loads(
        await executor.dispatch(
            ctx_ack,
            ToolCall(name="promote_generated_skill", arguments={"name": "risky"}),
        ),
    )
    assert blocked["ok"] is False
    assert blocked["code"] == QUARANTINE_SECURITY

    forced = json.loads(
        await executor.dispatch(
            ctx_ack,
            ToolCall(name="promote_generated_skill", arguments={"name": "risky", "force": True}),
        ),
    )
    assert forced["ok"] is True
    assert (skills / "user" / "risky").is_dir()
