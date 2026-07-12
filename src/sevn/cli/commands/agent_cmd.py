"""``sevn agent`` — active runs and model-slot status (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.agent_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.workspace

Exports:
    register — attach ``agent`` command group to the root Typer app.
"""

from __future__ import annotations

from typing import Any

import typer

from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace


def _format_agent_config(body: dict[str, Any]) -> str:
    """Render agent model panel JSON as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/agent/config`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> "main_model" in _format_agent_config({"main_model": "m", "slots": [], "use_main_model_for_all": True})
        True
    """
    lines = [
        f"main_model: {body.get('main_model', '—')}",
        f"use_main_model_for_all: {body.get('use_main_model_for_all', False)}",
    ]
    slots = body.get("slots")
    if isinstance(slots, list) and slots:
        lines.append("slots:")
        for row in slots:
            if not isinstance(row, dict):
                continue
            slot = row.get("slot", "?")
            resolved = row.get("resolved", "—")
            editable = row.get("editable", False)
            flag = " (editable)" if editable else ""
            lines.append(f"  {slot}: {resolved}{flag}")
    warnings = body.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("warnings:")
        for item in warnings:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def _format_run_snapshots(body: dict[str, Any]) -> str:
    """Render active run snapshots as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/runs/snapshots`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> _format_run_snapshots({"items": []})
        'active_runs: 0'
    """
    items = body.get("items")
    if not isinstance(items, list):
        return "active_runs: 0"
    lines = [f"active_runs: {len(items)}"]
    for row in items[:20]:
        if not isinstance(row, dict):
            continue
        run_id = row.get("run_id") or row.get("id") or "?"
        tier = row.get("tier") or row.get("executor_tier") or "?"
        state = row.get("state") or row.get("status") or "?"
        lines.append(f"  {run_id} tier={tier} state={state}")
    if len(items) > 20:
        lines.append(f"  … and {len(items) - 20} more")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach ``sevn agent`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    agent = typer.Typer(
        help="Inspect agent runs and resolved model-slot configuration.",
        invoke_without_command=True,
    )
    app.add_typer(agent, name="agent")

    @agent.callback()
    def agent_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())

    @agent.command("status")
    def agent_status(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
        limit: int = typer.Option(50, "--limit", help="Maximum active runs to return."),
    ) -> None:
        """List active gateway run snapshots."""
        command = "sevn agent status"
        try:
            bound = load_bound_workspace()
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="PRECONDITION",
                    message=str(exc),
                    exit_code=exc.exit_code,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(exc.exit_code) from exc
        path = f"/api/v1/runs/snapshots?limit={max(1, limit)}"
        body = dashboard_api_get(
            path,
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        typer.echo(_format_run_snapshots(body))

    @agent.command("config")
    def agent_config(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show resolved agent model slots (Mission Control agent panel)."""
        command = "sevn agent config"
        try:
            bound = load_bound_workspace()
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="PRECONDITION",
                    message=str(exc),
                    exit_code=exc.exit_code,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(exc.exit_code) from exc
        body = dashboard_api_get(
            "/api/v1/agent/config",
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        typer.echo(_format_agent_config(body))


__all__ = ["register"]
