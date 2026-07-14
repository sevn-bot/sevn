"""``sevn dashboard`` Mission Control URL (`specs/23-cli.md` §2.4.2).

Module: sevn.cli.commands.dashboard_cmd
Depends: webbrowser, typer, sevn.cli.gateway_client, sevn.cli.json_util, sevn.cli.workspace

Exports:
    register — attach ``dashboard`` command.
"""

from __future__ import annotations

import webbrowser

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_client import gateway_get
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.config.workspace_config import WorkspaceConfig
from sevn.onboarding.dashboard_url import mission_control_entry_url
from sevn.ui.dashboard.services.auth import (
    dashboard_local_open_configured,
    tunnel_active,
)


def _dashboard_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether Mission Control is enabled in workspace config.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        bool: ``True`` when ``dashboard.enabled`` is set.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _dashboard_enabled(WorkspaceConfig.minimal())
        False
    """
    dash = workspace.dashboard
    return dash is not None and bool(dash.enabled)


def _dashboard_login_password_configured(workspace: WorkspaceConfig) -> bool:
    """Return whether an owner login password is configured (value not printed).

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        bool: ``True`` when ``dashboard.login_password`` is non-empty.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     DashboardWorkspaceConfig,
        ...     WorkspaceConfig,
        ... )
        >>> ws = WorkspaceConfig.minimal(
        ...     dashboard=DashboardWorkspaceConfig(
        ...         enabled=True,
        ...         login_password="${SECRET:keychain:sevn.dashboard.password}",
        ...     ),
        ... )
        >>> _dashboard_login_password_configured(ws)
        True
    """
    dash = workspace.dashboard
    if dash is None or not dash.login_password:
        return False
    return bool(str(dash.login_password).strip())


def register(app: typer.Typer) -> None:
    """Attach ``sevn dashboard`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    dash = typer.Typer(
        help="Print or open the Mission Control dashboard URL for this workspace.",
        invoke_without_command=True,
    )
    app.add_typer(dash, name="dashboard")

    from sevn.cli.commands.dashboard_set_login_password import register_set_login_password

    register_set_login_password(dash)

    @dash.callback()
    def dashboard_root(
        ctx: typer.Context,
        open_browser: bool = typer.Option(
            False,
            "--open",
            help="Open the Mission Control URL in the default browser.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit url, local_open, auth_required, and tunnel_active as JSON.",
        ),
    ) -> None:
        """Print Mission Control URL and access hints for the bound workspace."""
        if ctx.invoked_subcommand is not None:
            return
        command = "sevn dashboard"
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

        workspace = bound.config
        if not _dashboard_enabled(workspace):
            msg = (
                "Mission Control is disabled (set dashboard.enabled to true in sevn.json, "
                "then restart the gateway)"
            )
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="PRECONDITION",
                    message=msg,
                    exit_code=4,
                )
            else:
                typer.secho(msg, err=True)
            raise typer.Exit(4)

        try:
            gateway_get(
                "/health",
                workspace=workspace,
                liveness=True,
            )
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="PRECONDITION",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc

        url = mission_control_entry_url(workspace)
        local_open = dashboard_local_open_configured(workspace)
        tunnel = tunnel_active(workspace)
        auth_required = not local_open

        if json_out:
            emit_json_success(
                command=command,
                data={
                    "url": url,
                    "local_open": local_open,
                    "auth_required": auth_required,
                    "tunnel_active": tunnel,
                },
            )
            raise typer.Exit(0)

        typer.echo(url)
        if local_open:
            typer.echo("loopback access — no login required")
        elif tunnel and _dashboard_login_password_configured(workspace):
            typer.echo(
                "Tunnel is active: open the URL above and sign in at /mission/ with your "
                "owner password (API clients may use a Bearer token after login)."
            )
        elif tunnel:
            typer.echo(
                "Tunnel is active: run `sevn dashboard set-login-password` before "
                "exposing Mission Control on the public internet."
            )
        else:
            typer.echo(
                "Remote access: sign in at /mission/ with your owner password "
                "(API clients may use a Bearer token after login)."
            )

        if open_browser:
            webbrowser.open(url)

        raise typer.Exit(0)
