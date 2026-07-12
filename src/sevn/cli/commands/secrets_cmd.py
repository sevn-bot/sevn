"""``sevn secrets`` via gateway admin API (`specs/06-secrets.md`, `specs/23-cli.md` §8).

Module: sevn.cli.commands.secrets_cmd
Depends: sys, typer, httpx, sevn.cli.*, sevn.cli.secrets_gateway_client

Exports:
    register — attach ``secrets`` command group to the root Typer app.
    execute_secrets_put — store one logical secret via the gateway admin API.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from typing import Any, NoReturn

import httpx
import typer

from sevn.cli.errors import CliAuthError, CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.secrets_gateway_client import (
    http_error_detail,
    secrets_delete,
    secrets_list,
    secrets_put,
)
from sevn.cli.workspace import load_bound_workspace


def _emit_http_failure(
    *,
    command: str,
    response: httpx.Response,
    json_out: bool,
    default_code: str = "GATEWAY_SECRETS_ERROR",
) -> NoReturn:
    """Map gateway HTTP errors to CLI exit ``4`` envelopes or stderr.

    Args:
        command (str): Command label for envelopes.
        response (httpx.Response): Non-success gateway response.
        json_out (bool): Whether to emit JSON failure envelope.
        default_code (str): Fallback ``error_code`` when detail omits one.

    Returns:
        NoReturn: Always raises ``typer.Exit(4)``.

    Examples:
        >>> import typer
        >>> try:
        ...     _emit_http_failure(
        ...         command="t",
        ...         response=httpx.Response(400, json={"detail": "x"}),
        ...         json_out=False,
        ...     )
        ... except typer.Exit as exc:
        ...     exc.exit_code == 4
        ... else:
        ...     False
        True
    """
    detail = http_error_detail(response)
    code = str(detail.get("error_code", default_code))
    message = str(detail.get("message", response.text or code))
    extra_details = {k: v for k, v in detail.items() if k not in ("error_code", "message")}
    if json_out:
        emit_json_failure(
            command=command,
            error_code=code,
            message=message,
            exit_code=4,
            details=extra_details or None,
        )
    else:
        typer.secho(message, err=True)
    raise typer.Exit(4)


def execute_secrets_put(
    *,
    alias: str,
    command: str,
    value: str | None,
    stdin: bool,
    confirm_fingerprint: str | None,
    json_out: bool,
    stdin_prompt: str | None = None,
) -> None:
    """Store one logical secret through the gateway admin API.

    Args:
        alias (str): Logical secret id (for example ``integration.github.token``).
        command (str): Command label for JSON envelopes and success messages.
        value (str | None): Plaintext from ``--value`` when set.
        stdin (bool): When True, read from stdin or prompt on a TTY.
        confirm_fingerprint (str | None): Required SHA-256 hex when overwriting.
        json_out (bool): Emit JSON success/failure envelopes.
        stdin_prompt (str | None): ``getpass`` prompt when ``--stdin`` on a TTY.

    Examples:
        >>> import typer
        >>> try:
        ...     execute_secrets_put(
        ...         alias="integration.github.token",
        ...         command="sevn gh add-github-token",
        ...         value=None,
        ...         stdin=False,
        ...         confirm_fingerprint=None,
        ...         json_out=False,
        ...     )
        ... except typer.Exit as exc:
        ...     exc.exit_code == 4
        ... else:
        ...     False
        True
    """

    def read_plain() -> str:
        if stdin:
            if sys.stdin.isatty():
                prompt = stdin_prompt or "Secret value: "
                s = getpass.getpass(prompt)
            else:
                line = sys.stdin.read()
                s = line.splitlines()[0] if line.splitlines() else ""
            if not s.strip():
                typer.secho(
                    f"{command}: no value provided (pipe a line or enter at the prompt)",
                    err=True,
                )
                raise typer.Exit(4)
            return s
        if value is None:
            typer.secho(
                f"{command}: provide --value, pass --stdin, or pipe one line into stdin",
                err=True,
            )
            raise typer.Exit(4)
        if not value.strip():
            typer.secho(f"{command}: value must be non-empty", err=True)
            raise typer.Exit(4)
        return value

    try:
        plaintext = read_plain()
    except typer.Exit:
        raise

    try:
        bw = load_bound_workspace()
        payload = secrets_put(
            bw,
            alias=alias,
            plaintext=plaintext,
            confirm_fingerprint=confirm_fingerprint,
        )
    except CliAuthError as exc:
        if json_out:
            emit_json_failure(
                command=command,
                error_code="AUTH",
                message=str(exc),
                exit_code=3,
            )
        else:
            typer.secho(str(exc), err=True)
        raise typer.Exit(3) from exc
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
    except httpx.HTTPStatusError as exc:
        _emit_http_failure(command=command, response=exc.response, json_out=json_out)
    except Exception as exc:
        if json_out:
            emit_json_failure(
                command=command,
                error_code="INTERNAL",
                message=str(exc),
                exit_code=4,
            )
        else:
            typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc

    data: dict[str, Any] = {
        "alias": payload.get("alias", alias),
        "fingerprint_sha256_hex": payload.get("fingerprint_sha256_hex", ""),
        "overwritten": bool(payload.get("overwritten", False)),
    }
    if json_out:
        emit_json_success(command=command, data=data)
    else:
        typer.echo(
            f"stored alias={data['alias']!r} fingerprint_sha256_hex={data['fingerprint_sha256_hex']}",
        )
    raise typer.Exit(0)


def register(app: typer.Typer) -> None:
    """Attach ``secrets`` commands (gateway-delegated admin API).

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    secrets = typer.Typer(
        help=(
            "Manage logical secrets through the gateway admin API at "
            "``/api/v1/admin/secrets`` (requires ``SEVN_GATEWAY_TOKEN`` or "
            "``gateway.token`` in ``sevn.json``)."
        ),
    )
    app.add_typer(secrets, name="secrets")

    @secrets.command("put")
    def secrets_put_cmd(
        alias: str = typer.Argument(..., help="Logical secret id (e.g. providers.openai.api_key)."),
        value: str | None = typer.Option(
            None,
            "--value",
            help="Supply the secret plaintext on the command line (prefer --stdin for safety).",
        ),
        stdin: bool = typer.Option(False, "--stdin", help="Read one line of plaintext from stdin."),
        confirm_fingerprint: str | None = typer.Option(
            None,
            "--confirm-fingerprint",
            help="Required when overwriting: SHA-256 hex of the existing value.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Store or replace one logical secret (gateway-delegated)."""
        execute_secrets_put(
            alias=alias,
            command="sevn secrets put",
            value=value,
            stdin=stdin,
            confirm_fingerprint=confirm_fingerprint,
            json_out=json_out,
        )

    @secrets.command("rm")
    def secrets_rm(
        alias: str = typer.Argument(..., help="Logical secret id to delete."),
        confirm_alias: str = typer.Option(
            ...,
            "--confirm-alias",
            help="Must exactly repeat ``alias`` (anti-fat-finger).",
        ),
        confirm_fingerprint: str = typer.Option(
            ...,
            "--confirm-fingerprint",
            help="SHA-256 hex of the stored plaintext (see ``secrets list``).",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Delete one logical secret after alias+fingerprint confirmation."""
        command = "sevn secrets rm"
        if confirm_alias.strip() != alias.strip():
            msg = "--confirm-alias must exactly match the alias argument"
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="CONFIRM_ALIAS_MISMATCH",
                    message=msg,
                    exit_code=4,
                )
            else:
                typer.secho(msg, err=True)
            raise typer.Exit(4)

        try:
            bw = load_bound_workspace()
            secrets_delete(
                bw,
                alias=alias,
                confirm_alias=confirm_alias,
                confirm_fingerprint=confirm_fingerprint,
            )
        except CliAuthError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="AUTH",
                    message=str(exc),
                    exit_code=3,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(3) from exc
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
        except httpx.HTTPStatusError as exc:
            _emit_http_failure(command=command, response=exc.response, json_out=json_out)
        except Exception as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="INTERNAL",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc

        if json_out:
            emit_json_success(command=command, data={"alias": alias, "deleted": True})
        else:
            typer.echo(f"deleted alias={alias!r}")
        raise typer.Exit(0)

    @secrets.command("list")
    def secrets_list_cmd(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """List logical aliases with fingerprints (never values)."""
        command = "sevn secrets list"
        try:
            bw = load_bound_workspace()
            rows = secrets_list(bw)
        except CliAuthError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="AUTH",
                    message=str(exc),
                    exit_code=3,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(3) from exc
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
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                _emit_http_failure(
                    command=command,
                    response=exc.response,
                    json_out=json_out,
                    default_code="SECRETS_STORE_CORRUPT",
                )
            _emit_http_failure(command=command, response=exc.response, json_out=json_out)
        except Exception as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="INTERNAL",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc

        if json_out:
            emit_json_success(command=command, data={"entries": rows})
        else:
            for row in rows:
                typer.echo(f"{row['alias']}\t{row['fingerprint_sha256_hex']}")
        raise typer.Exit(0)

    @secrets.command("store-passphrase")
    def secrets_store_passphrase(
        passphrase: str | None = typer.Option(
            None,
            "--passphrase",
            help="Passphrase plaintext (prefer --stdin or the SEVN_SECRETS_PASSPHRASE env var).",
        ),
        stdin: bool = typer.Option(
            False,
            "--stdin",
            help="Read the passphrase from stdin, or prompt securely on a TTY.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Store SEVN_SECRETS_PASSPHRASE in the macOS Keychain so daemons self-unlock at login.

        Writes a generic-password item (``-A``, readable without a GUI prompt) under the sevn
        Keychain service. The per-user LaunchAgent then opens the encrypted store at every login
        without ``launchctl setenv`` (which is wiped on logout). macOS only.
        """
        command = "sevn secrets store-passphrase"
        if sys.platform != "darwin":
            msg = (
                "store-passphrase is macOS-only (it writes to the login Keychain). On Linux, export "
                "SEVN_SECRETS_PASSPHRASE in the systemd unit or before `sevn gateway start`."
            )
            if json_out:
                emit_json_failure(
                    command=command, error_code="UNSUPPORTED_PLATFORM", message=msg, exit_code=4
                )
            else:
                typer.secho(msg, err=True)
            raise typer.Exit(4)

        value = passphrase
        if stdin:
            if sys.stdin.isatty():
                value = getpass.getpass("Keystore passphrase: ")
            else:
                line = sys.stdin.read()
                value = line.splitlines()[0] if line.splitlines() else ""
        if value is None:
            import os

            value = os.environ.get("SEVN_SECRETS_PASSPHRASE")
        if (value is None or not str(value).strip()) and sys.stdin.isatty():
            value = getpass.getpass("Keystore passphrase: ")
        if value is None or not str(value).strip():
            msg = "no passphrase: pass --passphrase, --stdin, or set SEVN_SECRETS_PASSPHRASE"
            if json_out:
                emit_json_failure(
                    command=command, error_code="EMPTY_PASSPHRASE", message=msg, exit_code=4
                )
            else:
                typer.secho(msg, err=True)
            raise typer.Exit(4)

        from sevn.cli.asyncio_util import run_sync_coro
        from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend

        try:
            run_sync_coro(
                MacOSKeychainBackend().set(
                    "SEVN_SECRETS_PASSPHRASE", value.strip(), allow_any_app=True
                )
            )
        except Exception as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="KEYCHAIN_WRITE_FAILED",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc

        if json_out:
            emit_json_success(
                command=command, data={"var": "SEVN_SECRETS_PASSPHRASE", "stored": True}
            )
        else:
            typer.echo(
                "stored SEVN_SECRETS_PASSPHRASE in macOS Keychain; restart the gateway once "
                "(`sevn gateway restart`) — it self-unlocks on every login thereafter"
            )
        raise typer.Exit(0)

    @secrets.command("check-unlock")
    def secrets_check_unlock(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Report whether the encrypted-store unlock key is reachable (env and/or Keychain)."""
        command = "sevn secrets check-unlock"
        from sevn.config.workspace_config import effective_encrypted_file_key_source
        from sevn.security.secrets.passphrase_prime import (
            keychain_has_unlock_secret,
            unlock_env_var_for,
        )

        key_source = "passphrase"
        try:
            bw = load_bound_workspace()
            key_source = effective_encrypted_file_key_source(bw.config.secrets_backend)
        except CliPreconditionError:
            pass

        import os

        var = unlock_env_var_for(key_source)
        in_env = bool(os.environ.get(var, "").strip())
        in_keychain = bool(asyncio.run(keychain_has_unlock_secret(key_source=key_source)))
        reachable = in_env or in_keychain
        data = {
            "key_source": key_source,
            "var": var,
            "in_env": in_env,
            "in_keychain": in_keychain,
            "reachable": reachable,
        }
        if json_out:
            if reachable:
                emit_json_success(command=command, data=data)
            else:
                emit_json_failure(
                    command=command,
                    error_code="UNLOCK_KEY_UNREACHABLE",
                    message=f"{var} is not in env or Keychain — store cannot be opened by daemons",
                    exit_code=4,
                    details=data,
                )
                raise typer.Exit(4)
        else:
            typer.echo(
                f"key_source={key_source} var={var} in_env={in_env} "
                f"in_keychain={in_keychain} reachable={reachable}"
            )
            if not reachable:
                typer.secho(
                    "unlock key unreachable — run `sevn secrets store-passphrase` (macOS) or "
                    f"export {var} before `sevn gateway start`",
                    err=True,
                )
                raise typer.Exit(4)
        raise typer.Exit(0)
