"""Skill tool registration tests (`plan/tools-skills-e2e-wave-plan.md` Waves 1-6)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from sevn.agent.adapters.dspy_adapter import to_dspy_tools
from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.errors import SKILL_INVALID_JSON, SKILL_SCRIPT_ARGS, SKILL_SCRIPT_UNKNOWN
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


def _write_min_skill(skill_dir: Path, *, description: str = "demo skill") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run.py").write_text(
        textwrap.dedent(
            """\
            import json, sys
            print(json.dumps({"ok": True, "data": {"echo": "hi"}, "message": None}), flush=True)
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
            description: {description}
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
async def test_run_skill_script_dispatches_via_skills_manager(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_min_skill(skills / "user" / "min_echo")
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "min_echo", "script": "scripts/run.py"},
            ),
        ),
    )

    assert envelope["ok"] is True
    assert envelope["data"]["echo"] == "hi"


@pytest.mark.asyncio
async def test_run_skill_script_unconfigured_returns_internal_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor, _tool_set = build_session_registry(registry_version=1)

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "min_echo", "script": "scripts/run.py"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.INTERNAL_ERROR
    assert "SkillsManager not configured" in envelope["error"]


@pytest.mark.asyncio
async def test_load_skill_returns_full_payload_via_skills_manager(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_min_skill(skills / "user" / "min_echo")
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(name="load_skill", arguments={"name": "min_echo"}),
        ),
    )

    assert envelope["ok"] is True
    data = envelope["data"]
    assert "markdown" in data
    assert "min_echo" in data["markdown"]
    assert data.get("markdown_truncated") is False
    assert data["capabilities"]
    assert data["capabilities"][0]["type"] == "script"
    assert "quarantine" in data
    assert data.get("schema", {}).get("kind") != "skill_menu"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script_arg",
    ["run", "scripts/run", "scripts/run.py"],
)
async def test_run_skill_script_normalises_script_arg(
    tmp_path: Path,
    script_arg: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_min_skill(skills / "user" / "min_echo")
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "min_echo", "script": script_arg},
            ),
        ),
    )

    assert envelope["ok"] is True
    assert envelope["data"]["echo"] == "hi"


@pytest.mark.asyncio
async def test_run_skill_script_unknown_returns_skill_script_unknown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_min_skill(skills / "user" / "min_echo")
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "min_echo", "script": "missing.py"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_SCRIPT_UNKNOWN
    assert "declared scripts" in envelope["error"]


@pytest.mark.asyncio
async def test_run_skill_script_missing_argv_returns_skill_script_args(tmp_path: Path) -> None:
    """Empty argv for scripts with required args_overview fails before subprocess."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = workspace / "skills" / "user" / "capture_like"
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "capture.py").write_text("raise SystemExit(2)\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: capture_like
            description: capture demo
            version: 1.0.0
            scripts:
              - path: scripts/capture.py
                description: navigate + screenshot
                args_overview: "<url> [path] [--full-page]"
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    skills = workspace / "skills"
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={
                    "skill": "capture_like",
                    "script": "scripts/capture.py",
                    "argv": [],
                },
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_SCRIPT_ARGS
    assert "requires at least 1 positional argv" in envelope["error"]
    assert envelope["data"]["required_argv_count"] == 1


@pytest.mark.asyncio
async def test_run_skill_script_invalid_json_includes_stderr_tail(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = workspace / "skills" / "user" / "bad_json"
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text(
        textwrap.dedent(
            """\
            import sys
            print("not json", flush=True)
            print("diag line on stderr", file=sys.stderr, flush=True)
            """
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: bad_json
            description: bad json demo
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
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    skills_root = workspace / "skills"
    manager = SkillsManager.shared(
        workspace,
        (skills_root,),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, _tool_set = build_session_registry(
        registry_version=7,
        skills_manager=manager,
    )

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "bad_json", "script": "scripts/run.py"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_INVALID_JSON
    assert "diag line on stderr" in envelope["data"]["stderr_tail"]


@pytest.mark.asyncio
async def test_run_skill_script_nonzero_exit_surfaces_structured_envelope(
    tmp_path: Path,
) -> None:
    """A script that exits non-zero *and* prints a JSON failure envelope keeps it (P3).

    Regression for the live-session bug where ``pdf.py`` emitted
    ``{"ok":false,"code":"RENDER_FAILED","error":"…run sevn doctor"}`` on stdout then
    exited 1; the runner masked it as ``nonzero exit (1); stderr tail:`` (empty) and the
    agent looped blind. The structured ``error``/``code`` must survive, annotated with
    ``exit_code``.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_dir = workspace / "skills" / "user" / "structured_fail"
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text(
        textwrap.dedent(
            """\
            import json, sys
            print(json.dumps({"ok": False, "error": "boom — run sevn doctor",
                              "code": "RENDER_FAILED"}), flush=True)
            sys.exit(1)
            """
        ),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: structured_fail
            description: structured failure demo
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
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    manager = SkillsManager.shared(
        workspace,
        (workspace / "skills",),
        layout=layout,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    executor, _tool_set = build_session_registry(registry_version=7, skills_manager=manager)

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "structured_fail", "script": "scripts/run.py"},
            ),
        ),
    )

    assert envelope["ok"] is False
    # The script's own code/message survive — not the generic SKILL_SCRIPT_NONZERO mask.
    assert envelope["code"] == "RENDER_FAILED"
    assert "run sevn doctor" in envelope["error"]
    assert envelope["data"]["exit_code"] == 1


@pytest.mark.asyncio
async def test_load_skill_not_found_via_skills_manager(tmp_path: Path) -> None:
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(name="load_skill", arguments={"name": "missing_skill"}),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.SKILL_NOT_FOUND


@pytest.mark.asyncio
async def test_load_skill_bundled_canvas_when_default_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills").mkdir()
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
    )

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(name="load_skill", arguments={"name": "canvas"}),
        ),
    )

    assert envelope["ok"] is True
    data = envelope["data"]
    spill_ref = data.get("spill_path") or data.get("path")
    if spill_ref:
        payload = json.loads((workspace / spill_ref).read_text(encoding="utf-8"))
        markdown = str(payload.get("markdown", ""))
        schema = payload.get("schema", {})
    else:
        markdown = str(data.get("markdown", ""))
        schema = data.get("schema", {})
    assert markdown
    assert "canvas" in markdown.lower()
    assert schema.get("kind") != "skill_menu"


@pytest.mark.asyncio
async def test_to_dspy_tools_run_skill_script_same_executor_backing(tmp_path: Path) -> None:
    """Tier C/D ``to_dspy_tools`` exposes ``run_skill_script`` backed by the session executor."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_min_skill(skills / "user" / "min_echo")
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
    direct = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "min_echo", "script": "scripts/run.py"},
            ),
        ),
    )
    shimmed = to_dspy_tools(executor, ctx)
    assert "run_skill_script" in shimmed
    via_dspy = json.loads(
        await shimmed["run_skill_script"](skill="min_echo", script="scripts/run.py"),
    )
    assert via_dspy == direct
    assert via_dspy["ok"] is True
    assert via_dspy["data"]["echo"] == "hi"


def _seed_second_brain_wiki(workspace: Path, *, scope: str = "owner") -> None:
    wiki = workspace / "second_brain" / "users" / scope / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "index.md").write_text("# index\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_bundled_second_brain_lint_script_smoke(tmp_path: Path) -> None:
    """Dispatch bundled ``second_brain`` ``scripts/lint.py`` via ``run_skill_script`` (Wave 6)."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "skills").mkdir()
    _seed_second_brain_wiki(workspace)
    layout = WorkspaceLayout(sevn_json_path=workspace / "sevn.json", content_root=workspace)
    executor, _tool_set = build_session_registry(
        workspace_root=workspace,
        layout=layout,
        workspace_config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    ctx = ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=_tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    envelope = json.loads(
        await executor.dispatch(
            ctx,
            ToolCall(
                name="run_skill_script",
                arguments={
                    "skill": "second_brain",
                    "script": "scripts/lint.py",
                    "argv": ["--scope", "owner"],
                },
            ),
        ),
    )
    assert envelope["ok"] is True
    assert "report_path" in envelope["data"]
    assert envelope["data"]["issue_count"] == 0


# Mission Control / dashboard skill lists (specs/24-dashboard.md) are not wired to
# ``SkillsManager.index`` yet — gateway menus use ``ToolSet.skill_descriptions`` from
# ``build_session_registry``; no ``mission_api`` skills endpoint reads the manager today.


# ---------------------------------------------------------------------------
# W1.2 — runnable=<tool> guard in _run_skill_runnable (2026-06-04)
# ---------------------------------------------------------------------------


def _ctx_with_known_tools(workspace: Path, *, known: frozenset[str]) -> ToolContext:
    return ToolContext(
        session_id="sess",
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=7,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        known_tool_names=known,
    )


@pytest.mark.asyncio
async def test_run_skill_runnable_runnable_is_tool_returns_skill_is_actually_tool(
    tmp_path: Path,
) -> None:
    """``run_skill_runnable(skill="browser-harness", runnable="serp")`` with
    ``serp ∈ known_tool_names`` must return ``SKILL_IS_ACTUALLY_TOOL`` with
    ``did_you_mean_tool="serp"`` — even though ``browser-harness`` is a real skill name.

    This is the W1.2 guard: the *runnable* slot is checked before ``_maybe_route_tool_as_skill``
    so the misroute is caught even when ``skill`` is legitimate.
    """
    from sevn.skills.errors import SKILL_IS_ACTUALLY_TOOL

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
            _ctx_with_known_tools(workspace, known=known),
            ToolCall(
                name="run_skill_runnable",
                arguments={
                    "skill": "browser-harness",  # a valid skill name, not a tool
                    "runnable": "serp",  # a registered tool name → guard fires
                    "payload": {"query": "test"},
                },
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_IS_ACTUALLY_TOOL
    assert envelope["did_you_mean_tool"] == "serp"


@pytest.mark.asyncio
async def test_run_skill_runnable_web_search_skill_serp_runnable_returns_skill_is_actually_tool(
    tmp_path: Path,
) -> None:
    """``run_skill_runnable(skill="web-search", runnable="serp")`` must also return
    ``SKILL_IS_ACTUALLY_TOOL`` — not ``SKILL_NOT_FOUND`` for the ``skill`` argument.

    The W1.2 guard fires on ``runnable`` first; the ``skill="web-search"`` is never reached.
    """
    from sevn.skills.errors import SKILL_IS_ACTUALLY_TOOL

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
            _ctx_with_known_tools(workspace, known=known),
            ToolCall(
                name="run_skill_runnable",
                arguments={
                    "skill": "web-search",  # not a real skill; runnable guard fires first
                    "runnable": "serp",
                    "payload": {"query": "test"},
                },
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == SKILL_IS_ACTUALLY_TOOL
    assert envelope["did_you_mean_tool"] == "serp"
    # Must NOT be SKILL_NOT_FOUND — the guard fires before skill lookup.
    assert envelope["code"] != ToolResultCode.SKILL_NOT_FOUND


# CodeMode kwarg coercion — mirror the log_query string-kwarg tolerance fix (#58).
# MiniMax-class models call skill runners through run_code where array/object kwargs arrive
# as JSON strings; the schema validator would reject them pre-dispatch and the call would
# vanish in the sandbox, burning the run_code retry budget instead of running the skill.


def _write_argv_echo_skill(skill_dir: Path) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "echo.py").write_text(
        textwrap.dedent(
            """\
            import json, sys
            print(json.dumps({"ok": True, "data": {"argv": sys.argv[1:]}, "message": None}), flush=True)
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
            description: argv echo
            version: 1.0.0
            scripts:
              - path: scripts/echo.py
                description: echo argv
                args_overview: "<a> <b>"
            ---
            body
            """
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_run_skill_script_coerces_json_string_argv(tmp_path: Path) -> None:
    """A CodeMode JSON-string ``argv='["alpha", "beta"]'`` dispatches as a real list."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skills = workspace / "skills"
    _write_argv_echo_skill(skills / "user" / "argv_echo")
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

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={
                    "skill": "argv_echo",
                    "script": "scripts/echo.py",
                    "argv": '["alpha", "beta"]',
                },
            ),
        ),
    )

    assert envelope["ok"] is True
    assert envelope["data"]["argv"] == ["alpha", "beta"]


def _configured_skill_executor(workspace: Path):
    skills = workspace / "skills"
    _write_argv_echo_skill(skills / "user" / "argv_echo")
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
    return executor


@pytest.mark.asyncio
async def test_run_skill_script_invalid_argv_returns_validation_error(tmp_path: Path) -> None:
    """A schema-valid argv string that is malformed JSON returns a readable ``ok=false`` envelope."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = _configured_skill_executor(workspace)

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_script",
                arguments={"skill": "argv_echo", "script": "scripts/echo.py", "argv": "[unclosed"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR
    assert "argv" in envelope["error"]


@pytest.mark.asyncio
async def test_run_skill_runnable_invalid_payload_returns_validation_error(tmp_path: Path) -> None:
    """A non-JSON ``payload`` string returns a readable ``ok=false`` envelope, not a raised error."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = _configured_skill_executor(workspace)

    envelope = json.loads(
        await executor.dispatch(
            _ctx(workspace),
            ToolCall(
                name="run_skill_runnable",
                arguments={"skill": "argv_echo", "runnable": "do", "payload": "not json"},
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.VALIDATION_ERROR
    assert "payload" in envelope["error"]
