"""``sevn gateway set-gateway-token`` — local bootstrap and rotation.

Module: sevn.cli.commands.gateway_set_token
Depends: sys, typer, sevn.cli.gateway_token_store, sevn.gateway.runtime.gateway_token

Exports:
    register_set_gateway_token — attach command to the gateway Typer group.
"""

from __future__ import annotations

import sys

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_token_store import (
    load_bootstrap_workspace,
    store_gateway_token_local,
)
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.gateway.runtime.gateway_token import (
    GATEWAY_TOKEN_CONFIG_REF,
    GATEWAY_TOKEN_LOGICAL_KEY,
    generate_gateway_token,
    validate_gateway_token_plaintext,
)

_SET_GATEWAY_TOKEN_HELP: str = (
    "Generate or set the gateway bearer token locally (gateway need not be running).\n\n"
    "By default sevn generates a 256-bit token (64 lowercase hex characters), prints it "
    "once, stores it in the workspace secrets chain as ``sevn.gateway.token``, and stamps "
    "``gateway.token`` in ``sevn.json`` with a ``${SECRET:…}`` reference only.\n\n"
    "External generation: ``openssl rand -hex 32`` (64 hex chars, no ``0x`` prefix).\n"
    "Minimum length: 32 printable ASCII characters (64 hex recommended).\n\n"
    "Input modes: ``--set-value <token>`` (visible in argv/ps), ``--stdin`` (read one line "
    "from standard input — preferred for scripts so the plaintext never reaches argv), or "
    "neither (auto-generate).\n\n"
    "Retrieving the token later: in ``--json`` mode the plaintext is never emitted (the "
    "envelope is fingerprint-only). Read it back from the secrets chain with "
    "``sevn secrets get sevn.gateway.token`` (logical key ``"
    + GATEWAY_TOKEN_LOGICAL_KEY
    + "``).\n\n"
    "With ``sevn shell-history install``, successful secret-setting ``sevn`` commands are "
    "removed from the interactive shell history automatically."
)


def register_set_gateway_token(gw: typer.Typer) -> None:
    """Attach ``set-gateway-token`` to the ``gateway`` Typer group.

    Args:
        gw (typer.Typer): ``sevn gateway`` sub-app.

    Examples:
        >>> register_set_gateway_token(typer.Typer()) is None
        True
    """

    @gw.command(
        "set-gateway-token",
        help=_SET_GATEWAY_TOKEN_HELP,
    )
    def set_gateway_token_cmd(
        set_value: str | None = typer.Option(
            None,
            "--set-value",
            help=(
                "Use an operator-supplied token instead of auto-generate "
                "(rotation or external generator). Visible in argv/ps — prefer --stdin."
            ),
        ),
        stdin: bool = typer.Option(
            False,
            "--stdin",
            help="Read the token as a single line from standard input (keeps it out of argv).",
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
        """Bootstrap or rotate ``gateway.token`` without a running gateway."""
        command = "sevn gateway set-gateway-token"
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
            supplied = sys.stdin.readline().strip()
        generated = supplied is None
        plaintext: str
        if generated:
            plaintext = generate_gateway_token()
        else:
            try:
                plaintext = validate_gateway_token_plaintext(supplied or "")
            except ValueError as exc:
                if json_out:
                    emit_json_failure(
                        command=command,
                        error_code="INVALID_TOKEN",
                        message=str(exc),
                        exit_code=4,
                    )
                else:
                    typer.secho(str(exc), err=True)
                raise typer.Exit(4) from exc

        try:
            bootstrap = load_bootstrap_workspace()
            result = store_gateway_token_local(
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
            "gateway_token_ref": result.gateway_token_ref or GATEWAY_TOKEN_CONFIG_REF,
            "overwritten": result.overwritten,
        }
        if json_out:
            emit_json_success(command=command, data=data)
        else:
            typer.echo(
                f"stored sevn.gateway.token fingerprint={result.fingerprint_sha256_hex}",
            )
            if generated:
                typer.echo("")
                typer.echo("Gateway token (copy now — not shown again):")
                typer.echo(plaintext)
                typer.echo("")
            typer.echo("Hint: sevn gateway restart")
        raise typer.Exit(0)


__all__ = ["register_set_gateway_token"]
