"""``sevn doctor --with-agent`` orchestrator (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.agent
Depends: subprocess, dataclasses, typing, typer, sevn.agent.diagnostics.runtime,
    sevn.cli.doctor.fix, sevn.cli.doctor.probes

Exports:
    AgentStepResult — one applied/skipped/manual step row.
    AgentRunReport — plan + step outcomes for human/JSON output.
    run_doctor_with_agent — confirm-gated plan execution after diagnostic agent run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import typer

from sevn.agent.diagnostics.runtime import (
    DiagnosticPlan,
    DiagnosticStep,
    is_apply_sevn_command,
    run_diagnostics_agent,
)
from sevn.agent.tracing.sink import TraceSink
from sevn.cli.asyncio_util import run_sync_coro
from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.fix import FixContext, FixReport, apply_safe_fixes
from sevn.cli.doctor.probes import DoctorRunOptions, run_doctor_probes
from sevn.cli.doctor.solutions import SolutionsCatalog, load_solutions_catalog
from sevn.cli.render import plain_echo
from sevn.config.model_resolution import diagnostics_agent_enabled


@dataclass(frozen=True, slots=True)
class AgentStepResult:
    """Outcome for one diagnostic plan step."""

    index: int
    title: str
    status: Literal["applied", "skipped", "manual", "rejected"]
    detail: str


@dataclass
class AgentRunReport:
    """Aggregated ``--with-agent`` run for rendering and ``--json``."""

    plan: DiagnosticPlan
    steps: list[AgentStepResult] = field(default_factory=list)
    fix_report: FixReport | None = None

    def to_json(self) -> dict[str, Any]:
        """Serialize plan + step outcomes for ``--json`` envelopes.

        Returns:
            dict[str, Any]: Additive ``agent_plan`` / ``agent_steps`` keys.

        Examples:
            >>> AgentRunReport(
            ...     plan=DiagnosticPlan(summary="ok", steps=[]),
            ... ).to_json()["agent_plan"]["summary"]
            'ok'
        """
        return {
            "agent_plan": {
                "summary": self.plan.summary,
                "steps": [step.model_dump() for step in self.plan.steps],
            },
            "agent_steps": [
                {
                    "index": row.index,
                    "title": row.title,
                    "status": row.status,
                    "detail": row.detail,
                }
                for row in self.steps
            ],
            "fixed": self.fix_report.fixed if self.fix_report else [],
            "manual": self.fix_report.manual if self.fix_report else [],
        }


def _actionable_checks(result: CheckResult) -> list[DoctorCheck]:
    """Return failing or warn checks from a probe pass.

    Args:
        result (CheckResult): Current doctor results.

    Returns:
        list[DoctorCheck]: Checks eligible for remediation.

    Examples:
        >>> _actionable_checks(CheckResult())
        []
    """
    return [c for c in result.checks if not c.ok or c.severity == "warn"]


def _needs_confirm(*, yes: bool, interactive: bool, prompt: str) -> bool:
    """Return True when a mutating step may proceed.

    Args:
        yes (bool): ``--yes`` flag (auto-apply all).
        interactive (bool): TTY / human mode.
        prompt (str): Confirm message.

    Returns:
        bool: Whether to apply the step.

    Examples:
        >>> _needs_confirm(yes=True, interactive=False, prompt="apply?")
        True
    """
    if yes:
        return True
    if interactive:
        return typer.confirm(prompt, default=False)
    return False


def _run_apply_sevn_command(command: str, *, cwd: str) -> tuple[int, str]:
    """Execute an allowlisted mutating ``sevn`` command in-process.

    Args:
        command (str): Full ``sevn …`` command string.
        cwd (str): Working directory for the CLI invocation.

    Returns:
        tuple[int, str]: Exit code and combined output summary.

    Raises:
        ValueError: When ``command`` is not on the apply allowlist.

    Examples:
        >>> _run_apply_sevn_command("sevn doctor --fix --yes", cwd="/tmp")  # doctest: +SKIP
    """
    if not is_apply_sevn_command(command):
        msg = f"command not on apply allowlist: {command!r}"
        raise ValueError(msg)
    body = command.strip()
    if body.startswith("sevn "):
        body = body[5:].strip()
    import os

    from typer.testing import CliRunner

    from sevn.cli.app import app as sevn_app

    runner = CliRunner()
    prev = os.getcwd()
    try:
        os.chdir(cwd)
        result = runner.invoke(sevn_app, body.split())
    finally:
        os.chdir(prev)
    detail = result.stdout.strip() or result.stderr.strip() or f"exit {result.exit_code}"
    return result.exit_code, detail


def _apply_auto_fix_step(
    *,
    bw: Any,
    result: CheckResult,
    step: DiagnosticStep,
    yes: bool,
    interactive: bool,
    catalog: SolutionsCatalog,
) -> tuple[AgentStepResult, FixReport | None, bool]:
    """Apply whitelisted auto-fixes relevant to ``step.check_ids``.

    Args:
        bw (Any): Bound workspace bundle from ``load_doctor_workspace``.
        result (CheckResult): Current probe results.
        step (DiagnosticStep): Plan step metadata.
        yes (bool): Non-interactive consent flag.
        interactive (bool): Whether confirm prompts are allowed.
        catalog (SolutionsCatalog): Solutions catalog for fix handlers.

    Returns:
        tuple[AgentStepResult, FixReport | None, bool]: Step row, fix report, whether mutated.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.diagnostics.runtime import DiagnosticStep
        >>> from sevn.cli.doctor.checks import CheckResult
        >>> from sevn.cli.doctor.solutions import SolutionsCatalog
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> class _Bw:
        ...     layout = type("L", (), {"content_root": Path("/tmp")})()
        ...     config = WorkspaceConfig.minimal()
        >>> row, _, _ = _apply_auto_fix_step(
        ...     bw=_Bw(),
        ...     result=CheckResult(),
        ...     step=DiagnosticStep(
        ...         check_ids=["llmignore"],
        ...         title="layout",
        ...         action_type="auto_fix",
        ...     ),
        ...     yes=False,
        ...     interactive=False,
        ...     catalog=SolutionsCatalog(schema_version=1, by_id={}),
        ... )
        >>> row.status
        'skipped'
    """
    if not _needs_confirm(
        yes=yes,
        interactive=interactive,
        prompt=f"Apply auto-fix: {step.title}?",
    ):
        return (
            AgentStepResult(
                index=0,
                title=step.title,
                status="skipped",
                detail="operator declined (re-run with --yes to auto-apply all)",
            ),
            None,
            False,
        )
    narrowed = CheckResult()
    wanted = set(step.check_ids)
    for check in result.checks:
        if check.id in wanted:
            narrowed.add(check)
    fix_report = apply_safe_fixes(
        FixContext(bw=bw, yes=yes, interactive=interactive),
        narrowed,
        catalog=catalog,
    )
    if fix_report.fixed:
        status: Literal["applied", "manual"] = "applied"
        detail = "; ".join(row["detail"] for row in fix_report.fixed)
    elif fix_report.manual:
        status = "manual"
        detail = "; ".join(row["detail"] for row in fix_report.manual)
    else:
        status = "manual"
        detail = "no whitelisted auto-fix applied for this step"
    return (
        AgentStepResult(index=0, title=step.title, status=status, detail=detail),
        fix_report,
        bool(fix_report.fixed),
    )


def _apply_plan_step(
    *,
    bw: Any,
    result: CheckResult,
    step: DiagnosticStep,
    index: int,
    yes: bool,
    interactive: bool,
    catalog: SolutionsCatalog,
) -> tuple[AgentStepResult, FixReport | None, bool]:
    """Apply one diagnostic plan step when confirmed.

    Args:
        bw (Any): Bound workspace bundle.
        result (CheckResult): Current doctor results.
        step (DiagnosticStep): Plan step to apply.
        index (int): 1-based step index for display.
        yes (bool): ``--yes`` auto-apply flag.
        interactive (bool): Whether prompts are allowed.
        catalog (SolutionsCatalog): Solutions catalog.

    Returns:
        tuple[AgentStepResult, FixReport | None, bool]: Step row, optional fix report, mutated.

    Examples:
        >>> from sevn.agent.diagnostics.runtime import DiagnosticStep
        >>> from sevn.cli.doctor.checks import CheckResult
        >>> from sevn.cli.doctor.solutions import SolutionsCatalog
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from pathlib import Path
        >>> class _Bw:
        ...     layout = type("L", (), {"content_root": Path("/tmp")})()
        ...     config = WorkspaceConfig.minimal()
        >>> row, _, _ = _apply_plan_step(
        ...     bw=_Bw(),
        ...     result=CheckResult(),
        ...     step=DiagnosticStep(
        ...         check_ids=["gateway_health"],
        ...         title="review",
        ...         action_type="manual",
        ...         explanation="start gateway",
        ...     ),
        ...     index=1,
        ...     yes=False,
        ...     interactive=False,
        ...     catalog=SolutionsCatalog(schema_version=1, by_id={}),
        ... )
        >>> row.status
        'manual'
    """
    if step.action_type == "manual":
        return (
            AgentStepResult(
                index=index,
                title=step.title,
                status="manual",
                detail=step.explanation or "manual operator action required",
            ),
            None,
            False,
        )
    if step.action_type == "auto_fix":
        row, fix_report, mutated = _apply_auto_fix_step(
            bw=bw,
            result=result,
            step=step,
            yes=yes,
            interactive=interactive,
            catalog=catalog,
        )
        return (
            AgentStepResult(index=index, title=row.title, status=row.status, detail=row.detail),
            fix_report,
            mutated,
        )
    if step.action_type == "sevn_command":
        command = (step.command or "").strip()
        if not command:
            return (
                AgentStepResult(
                    index=index,
                    title=step.title,
                    status="manual",
                    detail="missing sevn_command",
                ),
                None,
                False,
            )
        if not is_apply_sevn_command(command):
            return (
                AgentStepResult(
                    index=index,
                    title=step.title,
                    status="rejected",
                    detail=f"command not allowlisted: {command}",
                ),
                None,
                False,
            )
        if not _needs_confirm(
            yes=yes,
            interactive=interactive,
            prompt=f"Run `{command}`?",
        ):
            return (
                AgentStepResult(
                    index=index,
                    title=step.title,
                    status="skipped",
                    detail="operator declined (re-run with --yes to auto-apply all)",
                ),
                None,
                False,
            )
        try:
            code, detail = _run_apply_sevn_command(
                command,
                cwd=str(bw.layout.content_root),
            )
        except ValueError as exc:
            return (
                AgentStepResult(
                    index=index,
                    title=step.title,
                    status="rejected",
                    detail=str(exc),
                ),
                None,
                False,
            )
        status: Literal["applied", "manual"] = "applied" if code == 0 else "manual"
        return (
            AgentStepResult(index=index, title=step.title, status=status, detail=detail),
            None,
            code == 0,
        )
    return (
        AgentStepResult(
            index=index,
            title=step.title,
            status="manual",
            detail=f"unknown action_type: {step.action_type}",
        ),
        None,
        False,
    )


def run_doctor_with_agent(
    *,
    bw: Any,
    result: CheckResult,
    catalog: SolutionsCatalog | None = None,
    model_override: str | None = None,
    yes: bool,
    interactive: bool,
    probe_options: DoctorRunOptions,
    trace: TraceSink | None = None,
    plan_override: DiagnosticPlan | None = None,
) -> tuple[CheckResult, AgentRunReport]:
    """Run diagnostic agent + confirm-gated plan application.

    Args:
        bw (Any): Bound workspace from ``load_doctor_workspace``.
        result (CheckResult): Initial doctor probe results.
        catalog (SolutionsCatalog | None): Optional pre-loaded catalog.
        model_override (str | None): CLI ``--model`` override.
        yes (bool): Auto-apply all plan steps without prompts.
        interactive (bool): Allow Typer confirm prompts.
        probe_options (DoctorRunOptions): Flags forwarded to ``run_doctor_probes``.
        trace (TraceSink | None): Optional trace sink for the agent run.
        plan_override (DiagnosticPlan | None): Inject plan for tests (skips model).

    Returns:
        tuple[CheckResult, AgentRunReport]: Refreshed checks after fixes + run report.

    Raises:
        typer.Exit: When diagnostics slot disabled and no ``--model`` override.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.diagnostics.runtime import DiagnosticPlan
        >>> from sevn.cli.doctor.checks import CheckResult, DoctorCheck
        >>> from sevn.cli.doctor.probes import DoctorRunOptions
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> class _Bw:
        ...     layout = type("L", (), {"content_root": Path("/tmp")})()
        ...     config = WorkspaceConfig.minimal()
        >>> result = CheckResult()
        >>> result.add(
        ...     DoctorCheck("llmignore", "Security", ".llmignore", False, severity="warn", detail="x"),
        ... )
        >>> run_doctor_with_agent(
        ...     bw=_Bw(),
        ...     result=result,
        ...     yes=False,
        ...     interactive=False,
        ...     probe_options=DoctorRunOptions(),
        ...     plan_override=DiagnosticPlan(summary="ok", steps=[]),
        ... )[1].plan.summary
        'ok'
    """
    doc = catalog or load_solutions_catalog()
    if not diagnostics_agent_enabled(bw.config) and not (
        isinstance(model_override, str) and model_override.strip()
    ):
        typer.secho(
            "agent.diagnostics.enabled is false — set agent.diagnostics.enabled or pass --model",
            err=True,
        )
        raise typer.Exit(4)

    actionable = _actionable_checks(result)
    if not actionable:
        plan = DiagnosticPlan(summary="All checks passed — no remediation plan.", steps=[])
        return result, AgentRunReport(plan=plan)

    catalog_json = "{}"
    from importlib import resources

    try:
        catalog_json = (
            resources.files("sevn.data")
            .joinpath("doctor_solutions.json")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError, TypeError):
        catalog_json = "{}"

    doctor_report = {
        "checks": result.to_json_checks(include_solutions=True, catalog=doc),
        "warnings": list(result.warnings),
    }

    plan = run_sync_coro(
        run_diagnostics_agent(
            workspace=bw.config,
            layout=bw.layout,
            doctor_report=doctor_report,
            catalog_json=catalog_json,
            model_override=model_override,
            trace=trace,
            plan_override=plan_override,
        ),
    )

    if interactive:
        plain_echo(f"Diagnostic plan: {plan.summary}")
        for idx, step in enumerate(plan.steps, start=1):
            cmd = f" → `{step.command}`" if step.command else ""
            plain_echo(f"  {idx}. [{step.action_type}] {step.title}{cmd}")

    report = AgentRunReport(plan=plan)
    current = result
    aggregate_fix = FixReport()

    for idx, step in enumerate(plan.steps, start=1):
        step_row, fix_report, mutated = _apply_plan_step(
            bw=bw,
            result=current,
            step=step,
            index=idx,
            yes=yes,
            interactive=interactive,
            catalog=doc,
        )
        report.steps.append(step_row)
        if fix_report is not None:
            aggregate_fix.fixed.extend(fix_report.fixed)
            aggregate_fix.manual.extend(fix_report.manual)
        if mutated:
            current = CheckResult()
            run_doctor_probes(bw, current, options=probe_options)

    report.fix_report = aggregate_fix if (aggregate_fix.fixed or aggregate_fix.manual) else None
    return current, report


__all__ = ["AgentRunReport", "AgentStepResult", "run_doctor_with_agent"]
