"""``sevn dashboard set-login-password`` — local bootstrap and rotation.

Module: sevn.cli.commands.dashboard_set_login_password
Depends: sys, getpass, typer, sevn.cli.dashboard_login_password_store

Exports:
    register_set_login_password — attach command to the dashboard Typer group.
"""

from __future__ import annotations

import getpass
import sys

import typer

from sevn.cli.dashboard_login_password_store import (
    load_bootstrap_workspace,
    store_dashboard_login_password_local,
)
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.ui.dashboard.dashboard_password import (
    DASHBOARD_LOGIN_PASSWORD_CONFIG_REF,
    DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY,
    DASHBOARD_LOGIN_PASSWORD_MIN_CHARS,
    generate_dashboard_login_password,
    validate_dashboard_login_password_plaintext,
)

_SET_LOGIN_PASSWORD_HELP: str = (
    "Generate or set the Mission Control owner login password locally "
    "(gateway need not be running).\n\n"
    "By default sevn generates a random password, prints it once, stores it in the "
    "workspace secrets chain as ``sevn.dashboard.password``, and stamps "
    "``dashboard.login_password`` in ``sevn.json`` with a ``${SECRET:…}`` reference only.\n\n"
    f"Minimum length: {DASHBOARD_LOGIN_PASSWORD_MIN_CHARS} characters.\n\n"
    "Input modes: ``--set-value <password>`` (visible in argv/ps), ``--stdin`` "
    "(read one line from standard input — preferred for scripts), or neither "
    "(auto-generate).\n\n"
    "Required before exposing Mission Control on the public internet (tunnel mode). "
    "Distinct from ``gateway.token`` — use this password at ``/mission/`` owner login."
)


def register_set_login_password(dash: typer.Typer) -> None:
    """Attach ``set-login-password`` to the ``dashboard`` Typer group.

    Args:
        dash (typer.Typer): ``sevn dashboard`` sub-app.

    Examples:
        >>> register_set_login_password(typer.Typer()) is None
        True
    """

    @dash.command(
        "set-login-password",
        help=_SET_LOGIN_PASSWORD_HELP,
    )
    def set_login_password_cmd(
        set_value: str | None = typer.Option(
            None,
            "--set-value",
            help=(
                "Use an operator-supplied password instead of auto-generate. "
                "Visible in argv/ps — prefer --stdin."
            ),
        ),
        stdin: bool = typer.Option(
            False,
            "--stdin",
            help="Read the password as a single line from standard input.",
        ),
        confirm_fingerprint: str | None = typer.Option(
            None,
            "--confirm-fingerprint",
            help="Required when overwriting a different value: SHA-256 hex of the existing value.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="JSON envelope with fingerprint and ref only (never plaintext).",
        ),
    ) -> None:
        """Bootstrap or rotate ``dashboard.login_password`` without a running gateway."""
        command = "sevn dashboard set-login-password"
        if set_value is not None and stdin:
            msg = "pass at most one of --set-value or --stdin"
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="INVALID_USAGE",
                    message=msg,
                    exit_code=4,
                )
            else:
                typer.secho(msg, err=True)
            raise typer.Exit(4)

        supplied: str | None = set_value
        if stdin:
            if sys.stdin.isatty():
                supplied = getpass.getpass("Mission Control owner password: ")
            else:
                line = sys.stdin.read()
                supplied = line.splitlines()[0] if line.splitlines() else ""
        generated = supplied is None
        plaintext: str
        if generated:
            plaintext = generate_dashboard_login_password()
        else:
            try:
                plaintext = validate_dashboard_login_password_plaintext(supplied or "")
            except ValueError as exc:
                if json_out:
                    emit_json_failure(
                        command=command,
                        error_code="INVALID_PASSWORD",
                        message=str(exc),
                        exit_code=4,
                    )
                else:
                    typer.secho(str(exc), err=True)
                raise typer.Exit(4) from exc

        try:
            bootstrap = load_bootstrap_workspace()
            result = store_dashboard_login_password_local(
                bootstrap,
                plaintext=plaintext,
                confirm_fingerprint=confirm_fingerprint,
            )
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="WORKSPACE_PRECONDITION",
                    message=str(exc),
                    exit_code=exc.exit_code,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(exc.exit_code) from exc
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="STORE_FAILED",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc

        data = {
            "fingerprint_sha256_hex": result.fingerprint_sha256_hex,
            "generated": generated,
            "login_password_ref": result.login_password_ref or DASHBOARD_LOGIN_PASSWORD_CONFIG_REF,
            "logical_key": DASHBOARD_LOGIN_PASSWORD_LOGICAL_KEY,
            "overwritten": result.overwritten,
        }
        if json_out:
            emit_json_success(command=command, data=data)
        else:
            typer.echo(
                f"stored sevn.dashboard.password fingerprint={result.fingerprint_sha256_hex}",
            )
            if generated:
                typer.echo("")
                typer.echo("Mission Control owner password (copy now — not shown again):")
                typer.echo(plaintext)
                typer.echo("")
            typer.echo("Hint: sevn gateway restart")
        raise typer.Exit(0)


__all__ = ["register_set_login_password"]
