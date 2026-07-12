"""Shared Typer handlers for ``sevn gateway`` / ``sevn proxy`` (`specs/23-cli.md` §4.2).

Exports:
    register_daemon_subcommands — attach start/stop/restart/status to a Typer group.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

import typer

from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.operator_lock import OperatorLockHeld, operator_lock
from sevn.cli.service_manager import (
    ServiceManagerError,
    control_unit,
    propagate_daemon_proxy_env,
    propagate_daemon_secret_env,
    unit_file_exists,
)
from sevn.cli.workspace import sevn_home_dir

ServiceName = Literal["gateway", "proxy"]
MutatingAction = Literal["start", "stop", "restart"]
_STOP_PAIR: tuple[ServiceName, ServiceName] = ("gateway", "proxy")


def _control_paired_proxy(
    *,
    home: Path,
    action: MutatingAction,
    dry_run: bool = False,
) -> str | None:
    """Start/stop/restart the proxy unit when installed (paired with gateway).

    Args:
        home (Path): Operator home directory.
        action (MutatingAction): Service manager verb for the proxy unit.
        dry_run (bool, optional): Print planned command only.

    Returns:
        str | None: Status line when the proxy unit exists; ``None`` when absent.

    Raises:
        ServiceManagerError: When the proxy command fails on start or restart.

    Examples:
        >>> _control_paired_proxy(
        ...     home=Path("/tmp/h"),
        ...     action="start",
        ...     dry_run=True,
        ... ) is None
        True
    """
    if not unit_file_exists(home=home, service="proxy"):
        return None
    try:
        return control_unit(home=home, service="proxy", action=action, dry_run=dry_run)
    except ServiceManagerError as exc:
        typer.secho(f"proxy {action} failed: {exc}", err=True, fg=typer.colors.RED)
        if action in ("start", "restart"):
            raise
        return None


def _mutate_gateway_with_proxy(
    *,
    home: Path,
    action: MutatingAction,
    dry_run: bool = False,
) -> list[str]:
    """Run gateway + proxy service actions in safe order.

    When the proxy user unit is installed, ``start`` and ``restart`` bring up proxy
    before gateway; ``stop`` stops gateway and proxy concurrently.

    Args:
        home (Path): Operator home directory.
        action (MutatingAction): Service manager verb.
        dry_run (bool, optional): Print planned commands only.

    Returns:
        list[str]: Human-readable status lines in execution order.

    Raises:
        ServiceManagerError: When a required step fails (proxy start/restart or gateway).

    Examples:
        >>> lines = _mutate_gateway_with_proxy(
        ...     home=Path("/tmp/h"),
        ...     action="start",
        ...     dry_run=True,
        ... )
        >>> len(lines) >= 1
        True
    """
    lines: list[str] = []
    if action == "start":
        proxy_line = _control_paired_proxy(home=home, action="start", dry_run=dry_run)
        if proxy_line is not None:
            lines.append(proxy_line)
        lines.append(control_unit(home=home, service="gateway", action="start", dry_run=dry_run))
        return lines
    if action == "restart":
        proxy_line = _control_paired_proxy(home=home, action="restart", dry_run=dry_run)
        if proxy_line is not None:
            lines.append(proxy_line)
        lines.append(control_unit(home=home, service="gateway", action="restart", dry_run=dry_run))
        return lines
    if dry_run or not unit_file_exists(home=home, service="proxy"):
        lines.append(control_unit(home=home, service="gateway", action="stop", dry_run=dry_run))
        if unit_file_exists(home=home, service="proxy"):
            proxy_line = _control_paired_proxy(home=home, action="stop", dry_run=dry_run)
            if proxy_line is not None:
                lines.append(proxy_line)
        return lines

    stop_errors: list[str] = []

    def _stop_one(service: ServiceName) -> tuple[ServiceName, str | None, str | None]:
        try:
            line = control_unit(home=home, service=service, action="stop")
        except ServiceManagerError as exc:
            return service, None, str(exc)
        return service, line, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(_stop_one, svc): svc for svc in _STOP_PAIR}
        results: dict[ServiceName, tuple[str | None, str | None]] = {}
        for future in as_completed(futures):
            svc, line, err = future.result()
            results[svc] = (line, err)
    for svc in _STOP_PAIR:
        line, err = results[svc]
        if line is not None:
            lines.append(line)
        elif err is not None:
            stop_errors.append(f"{svc} stop failed: {err}")
            typer.secho(stop_errors[-1], err=True, fg=typer.colors.RED)
    if stop_errors:
        msg = "; ".join(stop_errors)
        raise ServiceManagerError(msg)
    return lines


def register_daemon_subcommands(group: typer.Typer, *, service: ServiceName) -> None:
    """Attach daemon control commands to ``group``.

    Args:
        group (typer.Typer): ``gateway`` or ``proxy`` Typer subgroup.
        service (ServiceName): Which unit to control.

    Examples:
        >>> register_daemon_subcommands(typer.Typer(), service="gateway") is None
        True
    """

    @group.command("status")
    def status_cmd(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Print user service unit status."""
        try:
            line = control_unit(home=Path.home(), service=service, action="status")
        except ServiceManagerError as exc:
            if json_out:
                emit_json_failure(
                    command=f"sevn {service} status",
                    error_code="SERVICE_MANAGER",
                    message=str(exc),
                    exit_code=4,
                )
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        if json_out:
            emit_json_success(command=f"sevn {service} status", data={"status": line})
        else:
            typer.echo(line)

    def _mutating(action: MutatingAction, dry_run: bool) -> None:
        if not dry_run and service == "gateway" and action in ("start", "restart"):
            from sevn.branding import maybe_play_logo_splash

            maybe_play_logo_splash()
        unit_home = Path.home()
        if dry_run:
            if service == "gateway":
                for line in _mutate_gateway_with_proxy(
                    home=unit_home,
                    action=action,
                    dry_run=True,
                ):
                    typer.echo(line)
            else:
                typer.echo(
                    control_unit(home=unit_home, service=service, action=action, dry_run=True)
                )
            raise typer.Exit(0)
        home = sevn_home_dir()
        try:
            with operator_lock(home):
                if action in ("start", "restart"):
                    propagate_daemon_secret_env()
                    propagate_daemon_proxy_env()
                if service == "gateway":
                    lines = _mutate_gateway_with_proxy(home=unit_home, action=action)
                else:
                    lines = [control_unit(home=unit_home, service=service, action=action)]
        except OperatorLockHeld as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        except ServiceManagerError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        for line in lines:
            typer.echo(line)

    @group.command("start")
    def start_cmd(
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print the service manager command without executing it.",
        ),
    ) -> None:
        """Start the user service unit."""
        _mutating("start", dry_run)

    @group.command("stop")
    def stop_cmd(
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print the service manager command without executing it.",
        ),
    ) -> None:
        """Stop the user service unit."""
        _mutating("stop", dry_run)

    @group.command("restart")
    def restart_cmd(
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print the service manager command without executing it.",
        ),
    ) -> None:
        """Restart the user service unit."""
        _mutating("restart", dry_run)


__all__ = ["register_daemon_subcommands"]
