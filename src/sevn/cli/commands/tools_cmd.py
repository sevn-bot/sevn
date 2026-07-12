"""``sevn tools`` — tool health snapshots (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.tools_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.workspace

Exports:
    register — attach ``tools`` command group to the root Typer app.
"""

from __future__ import annotations

from typing import Any

import typer

from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace


def _format_tools_health(body: dict[str, Any]) -> str:
    """Render tools-health JSON as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/agent/tools-health`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> _format_tools_health({"rows": [], "count": 0})
        'tool_health_rows: 0'
    """
    rows = body.get("rows")
    count = body.get("count", len(rows) if isinstance(rows, list) else 0)
    lines = [f"tool_health_rows: {count}"]
    if isinstance(rows, list):
        for row in rows[:30]:
            if not isinstance(row, dict):
                continue
            name = row.get("tool_name") or row.get("name") or "?"
            status = row.get("status") or row.get("severity") or "?"
            lines.append(f"  {name}: {status}")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach ``sevn tools`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    tools = typer.Typer(
        help="Inspect chronic tool and skill failure health rows.",
        invoke_without_command=True,
    )
    app.add_typer(tools, name="tools")

    @tools.callback()
    def tools_root(
        ctx: typer.Context,
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        if ctx.invoked_subcommand is not None:
            return
        _tools_health(json_out=json_out)

    @tools.command("health")
    def tools_health(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show chronic tool/skill failure rows from the gateway."""
        _tools_health(json_out=json_out)


def _tools_health(*, json_out: bool) -> None:
    """Shared implementation for ``sevn tools`` and ``sevn tools health``.

    Args:
        json_out (bool): Emit JSON success envelope on stdout when True.

    Examples:
        >>> _tools_health(json_out=False)  # doctest: +SKIP
    """
    command = "sevn tools health"
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
        "/api/v1/agent/tools-health",
        command=command,
        workspace=bound.config,
        json_out=json_out,
    )
    if json_out:
        emit_json_success(command=command, data=body)
        return
    typer.echo(_format_tools_health(body))


__all__ = ["register"]
