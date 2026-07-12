"""``sevn deploy`` remote SSH commands (`specs/23-cli.md`).

Module: sevn.cli.commands.deploy_cmd
Depends: json, pathlib, typer, sevn.deploy.*

Exports:
    register — attach the ``deploy`` subtree to the root Typer app.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sevn.deploy.inventory import DeployInventoryError, load_inventory, resolve_inventory_path
from sevn.deploy.remote import DeployMode, DeployRunnerError, RemoteDeployRunner
from sevn.deploy.report import build_report_dict, write_deploy_report


def register(app: typer.Typer) -> None:
    """Attach ``sevn deploy`` subtree to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    deploy = typer.Typer(help="Remote SSH deploy from export bundles.")
    app.add_typer(deploy, name="deploy")

    @deploy.command("check")
    def deploy_check(
        host: str = typer.Option(..., "--host", help="Inventory host id under [hosts.<id>]."),
        inventory: Path | None = typer.Option(
            None,
            "--inventory",
            help="Path to deploy/inventory.toml (default: deploy/inventory.toml).",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit the deploy report JSON on stdout.",
        ),
    ) -> None:
        """Verify SSH connectivity and remote ``sevn`` without mutating the host."""
        _run_deploy_command(
            host=host,
            inventory=inventory,
            mode=DeployMode.CHECK,
            bundle=None,
            json_out=json_out,
        )

    @deploy.command("remote")
    def deploy_remote(
        host: str = typer.Option(..., "--host", help="Inventory host id under [hosts.<id>]."),
        bundle: Path | None = typer.Option(
            None,
            "--bundle",
            help="Export bundle from ``sevn export-secrets`` (.env).",
        ),
        inventory: Path | None = typer.Option(
            None,
            "--inventory",
            help="Path to deploy/inventory.toml (default: deploy/inventory.toml).",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print the planned ssh/scp commands without executing them.",
        ),
        install_sevn: bool = typer.Option(
            False,
            "--install-sevn",
            help="Run remote install.sh when sevn is missing (documented risk).",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Re-run deploy even when remote workspace already exists.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit the deploy report JSON on stdout.",
        ),
    ) -> None:
        """Deploy from an export bundle over SSH (onboard fast + units + health)."""
        mode = DeployMode.DRY_RUN if dry_run else DeployMode.DEPLOY
        _run_deploy_command(
            host=host,
            inventory=inventory,
            mode=mode,
            bundle=bundle,
            install_sevn=install_sevn,
            force=force,
            json_out=json_out,
        )


def _run_deploy_command(
    *,
    host: str,
    inventory: Path | None,
    mode: DeployMode,
    bundle: Path | None,
    install_sevn: bool = False,
    force: bool = False,
    json_out: bool = False,
) -> None:
    """Shared implementation for ``deploy check`` and ``deploy remote``.

    Args:
        host (str): Inventory host id.
        inventory (Path | None): Optional inventory override path.
        mode (DeployMode): Check, dry-run, or deploy.
        bundle (Path | None): Export bundle for deploy/dry-run modes.
        install_sevn (bool): Reserved for remote install.sh hook.
        force (bool): Reserved for redeploy override.
        json_out (bool): Emit JSON report on stdout.

    Examples:
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> import typer
        >>> from sevn.deploy.inventory import DeployInventoryError
        >>> with patch(
        ...     "sevn.cli.commands.deploy_cmd.load_inventory",
        ...     side_effect=DeployInventoryError("missing"),
        ... ):
        ...     try:
        ...         _run_deploy_command(
        ...             host="staging",
        ...             inventory=Path("/tmp/inventory.toml"),
        ...             mode=DeployMode.CHECK,
        ...             bundle=None,
        ...         )
        ...     except typer.Exit as exc:
        ...         code = exc.exit_code
        ...     else:
        ...         code = None
        >>> code
        2
    """
    inv_path = resolve_inventory_path(explicit=inventory)
    try:
        inv = load_inventory(inv_path)
    except DeployInventoryError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(2) from exc
    if mode is DeployMode.DEPLOY and bundle is None:
        typer.secho("deploy remote requires --bundle", err=True)
        raise typer.Exit(2)
    if mode is DeployMode.DRY_RUN and bundle is None:
        typer.secho("deploy remote --dry-run requires --bundle", err=True)
        raise typer.Exit(2)
    runner = RemoteDeployRunner(
        inventory=inv,
        host_id=host,
        mode=mode,
        bundle_path=bundle,
        install_sevn=install_sevn,
        force=force,
    )
    try:
        report = runner.run()
    except DeployRunnerError as exc:
        report = runner.report
        report_path = write_deploy_report(report)
        typer.secho(str(exc), err=True)
        typer.secho(f"report: {report_path}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    report_path = write_deploy_report(report)
    if json_out:
        typer.echo(json.dumps(build_report_dict(report), indent=2, sort_keys=True))
    elif mode is DeployMode.DRY_RUN:
        typer.echo("dry-run plan:")
        for cmd in runner.planned_commands:
            typer.echo("  " + " ".join(cmd))
    else:
        typer.echo(f"deploy {mode.value} ok for host {host!r}")
    typer.echo(f"report: {report_path}")
    if report.errors:
        raise typer.Exit(4)
    raise typer.Exit(0)
