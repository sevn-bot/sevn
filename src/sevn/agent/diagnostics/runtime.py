"""Tier-B diagnostic agent runtime with a curated doctor-scoped toolset (W4).

Wraps a pydantic-ai ``Agent`` with structured ``DiagnosticPlan`` output, read-only
investigation tools, and trace emission. Mutating fixes are **not** executed here —
the CLI orchestrator applies plan steps after operator confirmation.

Module: sevn.agent.diagnostics.runtime
Depends: pydantic, pydantic_ai, sevn.agent.adapters.native_model, sevn.agent.tracing.sink,
    sevn.config.model_resolution, sevn.tools.*

Exports:
    DiagnosticStep — one proposed fix row in a plan.
    DiagnosticPlan — structured agent output.
    DiagnosticsDeps — runtime dependency bundle.
    is_readonly_sevn_command — validate read-only ``sevn`` subcommands.
    is_apply_sevn_command — validate orchestrator apply commands.
    load_sevn_diagnostics_skill_body — bundled skill instructions.
    run_diagnostics_agent — invoke tier-B diagnostic agent (inject ``model`` in tests).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from sevn.agent.adapters.native_model import (
    default_native_model_context,
    resolve_pydantic_model_for_slot,
)
from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent
from sevn.config.model_resolution import (
    ModelSlot,
    _providers_dict,
    resolve_diagnostics_model,
)
from sevn.config.settings import ProcessSettings
from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

READONLY_SEVN_COMMAND_PREFIXES: tuple[str, ...] = (
    "doctor",
    "doctor --json",
    "gateway status",
    "proxy status",
    "config show",
    "config validate",
    "secrets list",
    "secrets status",
)

APPLY_SEVN_COMMAND_PREFIXES: tuple[str, ...] = (
    "doctor --fix --yes",
    "doctor --migrate-secrets --yes",
)

GATEWAY_GET_ALLOWLIST: frozenset[str] = frozenset(
    {
        "/health",
        "/ready",
        "/api/v1/channels/status",
        "/api/v1/proxy/status",
    },
)

_DIAGNOSTICS_SESSION_ID = "cli-doctor-diagnostics"


class DiagnosticStep(BaseModel):
    """One prioritised fix step proposed by the diagnostic agent."""

    check_ids: list[str] = Field(default_factory=list)
    title: str
    action_type: Literal["auto_fix", "sevn_command", "manual"]
    command: str | None = None
    explanation: str = ""


class DiagnosticPlan(BaseModel):
    """Structured fix plan returned by the diagnostic agent."""

    summary: str
    steps: list[DiagnosticStep] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DiagnosticsDeps:
    """Dependency bundle for diagnostic agent tools."""

    workspace: WorkspaceConfig
    layout: WorkspaceLayout
    tool_executor: ToolExecutor
    tool_context: ToolContext
    catalog_json: str
    skill_body: str
    proxy_base: str


def _normalize_sevn_body(command: str) -> str:
    """Strip leading ``sevn`` and whitespace from a command string.

    Args:
        command (str): Full or partial CLI invocation.

    Returns:
        str: Subcommand tail used for allowlist checks.

    Examples:
        >>> _normalize_sevn_body("sevn doctor --json")
        'doctor --json'
    """
    text = command.strip()
    if text.startswith("sevn "):
        return text[5:].strip()
    return text


def _matches_prefix(body: str, prefixes: tuple[str, ...]) -> bool:
    """Return True when ``body`` equals or extends an allowlisted prefix.

    Args:
        body (str): Normalized subcommand tail.
        prefixes (tuple[str, ...]): Allowed prefix strings.

    Returns:
        bool: Whether ``body`` is allowlisted.

    Examples:
        >>> _matches_prefix("doctor --json", ("doctor --json",))
        True
    """
    return any(body == prefix or body.startswith(f"{prefix} ") for prefix in prefixes)


def is_readonly_sevn_command(command: str) -> bool:
    """Return True when ``command`` is an investigation-only ``sevn`` invocation.

    Args:
        command (str): Full ``sevn …`` command or subcommand tail.

    Returns:
        bool: Whether the agent may run this command read-only.

    Examples:
        >>> is_readonly_sevn_command("sevn gateway status")
        True
        >>> is_readonly_sevn_command("sevn doctor --fix --yes")
        False
    """
    if is_apply_sevn_command(command):
        return False
    body = _normalize_sevn_body(command)
    return _matches_prefix(body, READONLY_SEVN_COMMAND_PREFIXES)


def is_apply_sevn_command(command: str) -> bool:
    """Return True when the orchestrator may apply ``command`` after confirmation.

    Args:
        command (str): Full ``sevn …`` command or subcommand tail.

    Returns:
        bool: Whether the command is on the apply allowlist.

    Examples:
        >>> is_apply_sevn_command("sevn doctor --fix --yes")
        True
        >>> is_apply_sevn_command("rm -rf /")
        False
    """
    body = _normalize_sevn_body(command)
    return _matches_prefix(body, APPLY_SEVN_COMMAND_PREFIXES)


def load_sevn_diagnostics_skill_body() -> str:
    """Load bundled ``sevn-diagnostics`` skill markdown body.

    Returns:
        str: Skill instructions text, or a short fallback when missing.

    Examples:
        >>> "sevn-diagnostics" in load_sevn_diagnostics_skill_body().lower()
        True
    """
    skill_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "bundled_skills"
        / "core"
        / "sevn-diagnostics"
        / "SKILL.md"
    )
    if not skill_path.is_file():
        return "# sevn-diagnostics\n\nRepair playbooks for sevn doctor --with-agent."
    text = skill_path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def _build_tool_executor(*, layout: WorkspaceLayout) -> tuple[ToolExecutor, ToolContext]:
    """Construct a minimal executor with read + log_query tools only.

    Args:
        layout (WorkspaceLayout): Bound workspace layout.

    Returns:
        tuple[ToolExecutor, ToolContext]: Executor and template context.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> root = Path('/tmp/ws')
        >>> root.mkdir(exist_ok=True)
        >>> cfg = WorkspaceConfig.minimal()
        >>> lay = WorkspaceLayout(sevn_json_path=root / 'sevn.json', content_root=root)
        >>> exe, _ = _build_tool_executor(layout=lay)
        >>> 'read' in {d.name for d in exe.definitions()}
        True
    """
    from sevn.tools.file_ops import register_file_ops_tools
    from sevn.tools.log_query import register_log_query_tool

    exe = ToolExecutor()
    register_file_ops_tools(exe)
    register_log_query_tool(exe)
    ctx = ToolContext(
        session_id=_DIAGNOSTICS_SESSION_ID,
        workspace_path=layout.content_root,
        workspace_id="cli-doctor",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    return exe, ctx


def _build_agent(
    *,
    workspace: WorkspaceConfig,
    deps: DiagnosticsDeps,
    model: Any,
) -> Agent[DiagnosticsDeps, DiagnosticPlan]:
    """Register curated diagnostic tools on a structured-output agent.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        deps (DiagnosticsDeps): Shared runtime deps for tools.
        model (Any): pydantic-ai model instance (native or test double).

    Returns:
        Agent[DiagnosticsDeps, DiagnosticPlan]: Configured diagnostic agent.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_build_agent)
        True
    """
    system = (
        "You are the sevn.bot CLI diagnostic agent. Analyze the doctor report and "
        "solutions catalog, investigate with read-only tools when needed, and return "
        "a prioritised DiagnosticPlan. Prefer auto_fix for catalog auto_fixable checks; "
        "use sevn_command only for allowlisted remediation commands; use manual when "
        "operator action is required. Never propose shell commands outside sevn."
    )
    agent: Agent[DiagnosticsDeps, DiagnosticPlan] = Agent(
        model,
        deps_type=DiagnosticsDeps,
        output_type=DiagnosticPlan,
        instructions=system,
    )

    @agent.tool
    async def diagnostics_read_file(ctx: RunContext[DiagnosticsDeps], path: str) -> str:
        """Read a workspace file (line-numbered, read-only)."""
        return await ctx.deps.tool_executor.dispatch(
            ctx.deps.tool_context,
            ToolCall(name="read", arguments={"path": path}),
        )

    @agent.tool
    async def diagnostics_log_query(
        ctx: RunContext[DiagnosticsDeps],
        log_file: str = "gateway.log",
        lines: int = 50,
    ) -> str:
        """Read recent redacted lines from a workspace log file."""
        from sevn.tools.log_query import query_log_lines, resolve_log_path

        logs_dir = ctx.deps.layout.content_root / "logs"
        path = resolve_log_path(logs_dir, log_file)
        payload = query_log_lines(path, lines=lines)
        return json.dumps(payload, ensure_ascii=False)

    @agent.tool
    async def diagnostics_config_show(ctx: RunContext[DiagnosticsDeps]) -> str:
        """Return redacted ``sevn.json`` for the bound workspace."""
        sevn_json = ctx.deps.layout.content_root / "sevn.json"
        if not sevn_json.is_file():
            return json.dumps({"ok": False, "error": "sevn.json missing"})
        return sevn_json.read_text(encoding="utf-8")

    @agent.tool
    async def diagnostics_gateway_get(ctx: RunContext[DiagnosticsDeps], path: str) -> str:
        """GET an allowlisted gateway control-plane path (read-only)."""
        from sevn.cli.gateway_client import gateway_get

        normalized = path if path.startswith("/") else f"/{path}"
        if normalized not in GATEWAY_GET_ALLOWLIST:
            return json.dumps(
                {
                    "ok": False,
                    "error": f"path not allowlisted: {normalized}",
                    "allowlist": sorted(GATEWAY_GET_ALLOWLIST),
                },
            )
        try:
            resp = gateway_get(normalized, workspace=ctx.deps.workspace)
            return resp.text
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})

    @agent.tool
    async def diagnostics_run_sevn(ctx: RunContext[DiagnosticsDeps], command: str) -> str:
        """Run an allowlisted read-only ``sevn`` subcommand and return stdout/stderr."""
        if not is_readonly_sevn_command(command):
            return json.dumps(
                {
                    "ok": False,
                    "error": "command not on read-only allowlist",
                    "command": command,
                },
            )
        body = _normalize_sevn_body(command)

        def _run_cli() -> dict[str, object]:
            from typer.testing import CliRunner

            from sevn.cli.app import app as sevn_app

            runner = CliRunner()
            result = runner.invoke(sevn_app, body.split())
            return {
                "ok": result.exit_code == 0,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        payload = await asyncio.to_thread(_run_cli)
        return json.dumps(payload, ensure_ascii=False)

    _ = workspace
    return agent


def _format_doctor_prompt(
    *,
    doctor_report: dict[str, Any],
    catalog_json: str,
    skill_body: str,
) -> str:
    """Assemble the user prompt for the diagnostic agent.

    Args:
        doctor_report (dict[str, Any]): Serialized doctor checks + warnings.
        catalog_json (str): Full solutions catalog JSON text.
        skill_body (str): Bundled sevn-diagnostics skill body.

    Returns:
        str: User prompt passed to the agent run.

    Examples:
        >>> _format_doctor_prompt(
        ...     doctor_report={"checks": []},
        ...     catalog_json="{}",
        ...     skill_body="# skill",
        ... ).startswith("## sevn-diagnostics skill")
        True
    """
    return (
        "## sevn-diagnostics skill\n\n"
        f"{skill_body}\n\n"
        "## Doctor report (JSON)\n\n"
        f"{json.dumps(doctor_report, indent=2, sort_keys=True)}\n\n"
        "## Solutions catalog (JSON)\n\n"
        f"{catalog_json}\n\n"
        "Return a DiagnosticPlan with ordered steps for failing/warn checks."
    )


async def run_diagnostics_agent(
    *,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    doctor_report: dict[str, Any],
    catalog_json: str,
    model_override: str | None = None,
    model: Any | None = None,
    trace: TraceSink | None = None,
    plan_override: DiagnosticPlan | None = None,
    process: ProcessSettings | None = None,
) -> DiagnosticPlan:
    """Run the tier-B diagnostic agent and return a structured fix plan.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        layout (WorkspaceLayout): Resolved filesystem layout.
        doctor_report (dict[str, Any]): Doctor ``checks`` + ``warnings`` payload.
        catalog_json (str): Serialized solutions catalog for agent context.
        model_override (str | None): CLI ``--model`` override.
        model (Any | None): Inject pydantic-ai model for tests (skips live resolution).
        trace (TraceSink | None): Optional trace sink for the diagnostic run.
        plan_override (DiagnosticPlan | None): Bypass model invocation in tests.
        process (ProcessSettings | None): Process settings for proxy URL resolution.

    Returns:
        DiagnosticPlan: Prioritised fix plan from the agent.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_diagnostics_agent)
        True
    """
    if plan_override is not None:
        if trace is not None:
            span_id = uuid.uuid4().hex
            await trace.emit(
                TraceEvent(
                    kind="diagnostics.agent",
                    span_id=span_id,
                    parent_span_id=None,
                    session_id=_DIAGNOSTICS_SESSION_ID,
                    turn_id=SYSTEM_TURN_ID,
                    tier="B",
                    ts_start_ns=time_ns(),
                    ts_end_ns=time_ns(),
                    status="ok",
                    attrs={"agent": "cli_doctor_diagnostics", "plan_override": True},
                ),
            )
        return plan_override

    span_id = uuid.uuid4().hex
    turn_id = f"doctor-diagnostics-{uuid.uuid4().hex[:8]}"
    if trace is not None:
        await trace.emit(
            TraceEvent(
                kind="diagnostics.agent",
                span_id=span_id,
                parent_span_id=None,
                session_id=_DIAGNOSTICS_SESSION_ID,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=time_ns(),
                ts_end_ns=None,
                status="running",
                attrs={"agent": "cli_doctor_diagnostics"},
            ),
        )

    proc = process or ProcessSettings()
    proxy_base = (proc.proxy_url or "http://127.0.0.1:8787").rstrip("/")
    skill_body = load_sevn_diagnostics_skill_body()
    exe, tool_ctx = _build_tool_executor(layout=layout)
    deps = DiagnosticsDeps(
        workspace=workspace,
        layout=layout,
        tool_executor=exe,
        tool_context=tool_ctx,
        catalog_json=catalog_json,
        skill_body=skill_body,
        proxy_base=proxy_base,
    )

    if model is None:
        model_id = resolve_diagnostics_model(workspace, override=model_override)
        ctx = default_native_model_context(
            slot=ModelSlot.tier_b,
            model_id=model_id,
            proxy_base=proxy_base,
            session_id=_DIAGNOSTICS_SESSION_ID,
            turn_id=turn_id,
            agent="cli_doctor_diagnostics",
            trace=trace,
            content_root=layout.content_root,
            providers_obj=_providers_dict(workspace),
            tier="B",
        )
        model = resolve_pydantic_model_for_slot(workspace=workspace, ctx=ctx)

    agent = _build_agent(workspace=workspace, deps=deps, model=model)
    prompt = _format_doctor_prompt(
        doctor_report=doctor_report,
        catalog_json=catalog_json,
        skill_body=skill_body,
    )
    try:
        result = await agent.run(prompt, deps=deps)
        plan = result.output
    finally:
        if trace is not None:
            await trace.emit(
                TraceEvent(
                    kind="diagnostics.agent",
                    span_id=span_id,
                    parent_span_id=None,
                    session_id=_DIAGNOSTICS_SESSION_ID,
                    turn_id=SYSTEM_TURN_ID,
                    tier="B",
                    ts_start_ns=time_ns(),
                    ts_end_ns=time_ns(),
                    status="ok",
                    attrs={"agent": "cli_doctor_diagnostics"},
                ),
            )
    return plan


__all__ = [
    "APPLY_SEVN_COMMAND_PREFIXES",
    "GATEWAY_GET_ALLOWLIST",
    "READONLY_SEVN_COMMAND_PREFIXES",
    "DiagnosticPlan",
    "DiagnosticStep",
    "DiagnosticsDeps",
    "is_apply_sevn_command",
    "is_readonly_sevn_command",
    "load_sevn_diagnostics_skill_body",
    "run_diagnostics_agent",
]
