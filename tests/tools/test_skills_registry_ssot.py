"""RED suite for skill-registry SSOT (D14; green after W7)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

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


def _write_broken_skill(skill_dir: Path) -> None:
    """Write a skill directory whose manifest cannot be loaded as a valid skill."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    # Invalid frontmatter / missing required fields → load_skill fails.
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: broken_unloadable
            description:
            version: not-a-semver
            ---
            broken body
            """
        ),
        encoding="utf-8",
    )


def _write_ok_skill(skill_dir: Path) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run.py").write_text(
        'print(\'{"ok": true, "data": {}, "message": null}\')\n',
        encoding="utf-8",
    )
    name = skill_dir.name
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: loadable skill
            version: 1.0.0
            scripts:
              - path: scripts/run.py
                description: main
            ---
            body
            """
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_d14_unloadable_skill_absent_or_quarantined(tmp_path: Path) -> None:
    """D14: a skill whose manifest fails to load is absent or ``quarantine:true``."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_ok_skill(skills / "user" / "ok_skill")
    _write_broken_skill(skills / "user" / "broken_unloadable")

    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(layout)
    inventory = manager.inventory_for_triager()

    broken = inventory.get("broken_unloadable")
    if broken is None:
        # Absent from advertised inventory — OK.
        pass
    else:
        assert broken.get("quarantine") is True, broken

    exe, tool_set = build_session_registry(
        registry_version=7,
        workspace_root=workspace,
        skills_manager=manager,
    )
    ctx = ToolContext(
        session_id="reg-d14",
        workspace_path=workspace,
        workspace_id="reg-d14-wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    raw = await exe.dispatch(ctx, ToolCall(name="list_registry", arguments={}))
    env = json.loads(raw)
    assert env["ok"] is True
    skills_listed = env["data"]["skills"]
    # Skills may be list[str] or list[dict].
    names: list[str] = []
    quarantined: dict[str, bool] = {}
    for item in skills_listed:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("id") or "")
            names.append(name)
            quarantined[name] = bool(item.get("quarantine"))
    if "broken_unloadable" in names:
        assert quarantined.get("broken_unloadable") is True


@pytest.mark.asyncio
async def test_d14_load_skill_on_listed_never_skill_not_found(tmp_path: Path) -> None:
    """D14: ``load_skill`` on any advertised skill never returns ``SKILL_NOT_FOUND``."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_ok_skill(workspace / "skills" / "user" / "ok_skill")
    _write_broken_skill(workspace / "skills" / "user" / "broken_unloadable")

    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(layout)
    exe, tool_set = build_session_registry(
        registry_version=7,
        workspace_root=workspace,
        skills_manager=manager,
    )
    ctx = ToolContext(
        session_id="reg-d14b",
        workspace_path=workspace,
        workspace_id="reg-d14b-wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    listed_raw = await exe.dispatch(ctx, ToolCall(name="list_registry", arguments={}))
    listed = json.loads(listed_raw)["data"]["skills"]
    names: list[str] = []
    for item in listed:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and not item.get("quarantine"):
            names.append(str(item.get("name") or item.get("id") or ""))

    assert names, "expected at least one advertised non-quarantined skill"
    for name in names:
        raw = await exe.dispatch(ctx, ToolCall(name="load_skill", arguments={"name": name}))
        env = json.loads(raw)
        assert env.get("code") != ToolResultCode.SKILL_NOT_FOUND, (name, env)
        assert env.get("ok") is True or env.get("code") != ToolResultCode.SKILL_NOT_FOUND
