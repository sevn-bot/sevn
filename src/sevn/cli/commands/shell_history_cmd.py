"""``sevn shell-history`` — install session history hooks for sensitive commands.

Module: sevn.cli.commands.shell_history_cmd
Depends: sys, typer, sevn.cli.shell_history_hooks

Exports:
    register — attach ``shell-history`` command group to the root Typer app.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.shell_history_hooks import (
    install_shell_history_hook,
    shell_history_hook_installed,
    uninstall_shell_history_hook,
)


def _normalize_shell(shell: str | None) -> str:
    """Return ``bash`` or ``zsh`` from ``shell`` or ``$SHELL``.

    Args:
        shell (str | None): Explicit shell name; defaults to ``$SHELL`` basename.

    Returns:
        str: Normalized shell name.

    Raises:
        ValueError: When the shell is not ``bash`` or ``zsh``.

    Examples:
        >>> _normalize_shell("zsh")
        'zsh'
    """
    name = (shell or Path(os.environ.get("SHELL", "")).name).strip().lower()
    if name not in {"bash", "zsh"}:
        msg = f"shell-history hooks support bash and zsh only (got {name!r})"
        raise ValueError(msg)
    return name


def register(app: typer.Typer) -> None:
    """Attach ``shell-history`` commands to the root Typer app.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    hist = typer.Typer(
        help=(
            "Shell history hook: drop successful secret-setting sevn commands from interactive "
            "history (store-passphrase, secrets put, add-github-token, set-gateway-token)."
        ),
    )
    app.add_typer(hist, name="shell-history")

    @hist.command("install")
    def shell_history_install(
        shell: str | None = typer.Argument(
            None,
            help="Target shell (bash or zsh). Defaults to $SHELL.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout.",
        ),
    ) -> None:
        """Install a precmd/PROMPT_COMMAND hook that scrubs sensitive commands from memory."""
        command = "sevn shell-history install"
        try:
            shell_name = _normalize_shell(shell)
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="UNSUPPORTED_SHELL",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        rc = install_shell_history_hook(shell=shell_name)  # nosec B604
        if json_out:
            emit_json_success(
                command=command,
                data={"shell": shell_name, "rc_file": str(rc), "installed": True},
            )
        else:
            typer.echo(f"installed {shell_name} shell-history hook in {rc}")
            typer.echo("restart the terminal or run: source " + str(rc))
        raise typer.Exit(0)

    @hist.command("status")
    def shell_history_status(
        shell: str | None = typer.Argument(
            None,
            help="Target shell (bash or zsh). Defaults to $SHELL.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success envelope to stdout.",
        ),
    ) -> None:
        """Report whether the managed shell-history hook is installed."""
        command = "sevn shell-history status"
        try:
            shell_name = _normalize_shell(shell)
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="UNSUPPORTED_SHELL",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        installed = shell_history_hook_installed(shell=shell_name)  # nosec B604
        if json_out:
            emit_json_success(
                command=command,
                data={"shell": shell_name, "installed": installed},
            )
        else:
            state = "installed" if installed else "not installed"
            typer.echo(f"{shell_name} shell-history hook: {state}")
        raise typer.Exit(0)

    @hist.command("uninstall")
    def shell_history_uninstall(
        shell: str | None = typer.Argument(
            None,
            help="Target shell (bash or zsh). Defaults to $SHELL.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout.",
        ),
    ) -> None:
        """Remove the managed shell-history hook from the operator rc file."""
        command = "sevn shell-history uninstall"
        try:
            shell_name = _normalize_shell(shell)
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="UNSUPPORTED_SHELL",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        removed = uninstall_shell_history_hook(shell=shell_name)  # nosec B604
        if json_out:
            emit_json_success(
                command=command,
                data={"shell": shell_name, "removed": removed},
            )
        else:
            if removed:
                typer.echo(f"removed {shell_name} shell-history hook")
            else:
                typer.echo(f"{shell_name} shell-history hook was not installed")
        raise typer.Exit(0)
