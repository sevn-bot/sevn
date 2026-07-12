"""``sevn providers`` — provider OAuth helpers (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.providers_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.secrets_gateway_client, sevn.cli.workspace

Exports:
    register — attach ``providers`` command group to the root Typer app.
"""

from __future__ import annotations

import sys
from typing import Any

import httpx
import typer

from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliAuthError, CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.secrets_gateway_client import http_error_detail, secrets_delete, secrets_list
from sevn.cli.workspace import BoundWorkspace, load_bound_workspace
from sevn.security.oauth.authorize import build_authorization_flow
from sevn.security.oauth.credential import oauth_openai_secret_alias
from sevn.security.oauth.login_flow import (
    complete_codex_oauth_login,
    load_codex_oauth_credential_from_workspace,
)

__all__ = ["load_codex_oauth_credential_from_workspace", "register"]


def _oauth_rows_from_health(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter provider health rows that reference OAuth CLI handoffs.

    Args:
        body (dict[str, Any]): ``GET /api/v1/providers/health`` payload.

    Returns:
        list[dict[str, Any]]: Rows with ``oauth`` in id or credential rows.

    Examples:
        >>> _oauth_rows_from_health({"providers": [{"id": "oauth.anthropic"}]})
        [{'id': 'oauth.anthropic'}]
    """
    providers = body.get("providers")
    if not isinstance(providers, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in providers:
        if not isinstance(row, dict):
            continue
        provider_id = str(row.get("id") or "")
        if "oauth" in provider_id or provider_id.startswith("credential."):
            rows.append(row)
    return rows


def _format_oauth_status(
    health_rows: list[dict[str, Any]],
    secret_aliases: list[str],
    *,
    openai_oauth: dict[str, Any] | None = None,
) -> str:
    """Render OAuth status as plain text.

    Args:
        health_rows (list[dict[str, Any]]): Filtered provider health rows.
        secret_aliases (list[str]): Logical secret aliases from gateway.
        openai_oauth (dict[str, Any] | None): Parsed ``oauth.openai`` credential summary.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> "oauth" in _format_oauth_status([], ["oauth.openai"])
        True
    """
    oauth_secrets = [a for a in secret_aliases if a.startswith("oauth.")]
    lines = [f"oauth_secrets: {len(oauth_secrets)}", f"provider_rows: {len(health_rows)}"]
    for alias in sorted(oauth_secrets):
        lines.append(f"  {alias}: configured")
    if openai_oauth:
        account_id = openai_oauth.get("account_id", "?")
        expires = openai_oauth.get("expires", "?")
        lines.append(f"  openai: account_id={account_id} expires={expires}")
    for row in health_rows[:20]:
        provider_id = row.get("id") or "?"
        detail = row.get("detail") or ""
        ok = row.get("ok")
        suffix = f" ({detail})" if detail else ""
        lines.append(f"  {provider_id}: ok={ok}{suffix}")
    return "\n".join(lines)


def _openai_oauth_handoff_message(*, authorize_url: str) -> str:
    """Return non-interactive OpenAI OAuth handoff text (D5/D6).

    Args:
        authorize_url (str): Codex authorize URL from ``build_authorization_flow``.

    Returns:
        str: Operator instructions including the authorize URL.

    Examples:
        >>> "auth.openai.com" in _openai_oauth_handoff_message(authorize_url="https://auth.openai.com/x")
        True
    """
    return (
        f"Open this URL to sign in with ChatGPT (Codex OAuth):\n{authorize_url}\n"
        "Complete authorization in your browser, then re-run with an interactive terminal "
        "or use `sevn providers oauth login --provider openai --headless` to paste the redirect URL."
    )


def _run_openai_oauth_login(
    bound: BoundWorkspace,
    *,
    headless: bool,
    json_out: bool,
    command: str,
) -> None:
    """Execute the Codex PKCE login flow for ``--provider openai`` (W4.1).

    Args:
        bound (BoundWorkspace): Bound workspace for secrets persistence.
        headless (bool): Use manual paste fallback (D5).
        json_out (bool): Emit JSON envelope on stdout.
        command (str): CLI command label for envelopes.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> _run_openai_oauth_login(MagicMock(), headless=False, json_out=True, command="c")  # doctest: +SKIP
    """
    flow = build_authorization_flow()
    handoff = _openai_oauth_handoff_message(authorize_url=flow.authorize_url)
    interactive = sys.stdin.isatty()

    if not interactive and not headless:
        if json_out:
            emit_json_success(
                command=command,
                data={
                    "provider": "openai",
                    "authorize_url": flow.authorize_url,
                    "message": handoff,
                },
            )
            return
        typer.echo(handoff)
        return

    if not json_out:
        typer.echo(flow.authorize_url)
        if headless or not interactive:
            typer.echo("Paste the redirect URL or authorization code when prompted.")

    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.factory import secrets_chain_from_workspace
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    key_source = effective_encrypted_file_key_source(bound.config.secrets_backend)
    run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))
    chain = secrets_chain_from_workspace(bound.layout.content_root, bound.config.secrets_backend)
    try:
        credential = run_sync_coro(
            complete_codex_oauth_login(flow, chain, headless=headless or not interactive),
        )
    except ValueError as exc:
        if json_out:
            emit_json_failure(
                command=command,
                error_code="OAUTH_LOGIN_FAILED",
                message=str(exc),
                exit_code=4,
            )
        else:
            typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc

    data = {
        "provider": "openai",
        "logical_key": oauth_openai_secret_alias(),
        "account_id": credential.account_id,
        "expires": credential.expires,
    }
    if json_out:
        emit_json_success(command=command, data=data)
        return
    typer.echo(
        f"stored {oauth_openai_secret_alias()} for account_id={credential.account_id} "
        f"(expires={credential.expires})",
    )


def register(app: typer.Typer) -> None:
    """Attach ``sevn providers`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    prov = typer.Typer(help="Configure provider OAuth credentials for LLM transports.")
    app.add_typer(prov, name="providers")

    oauth = typer.Typer(help="Pair or revoke OAuth tokens for a provider.")
    prov.add_typer(oauth, name="oauth")

    @oauth.command("status")
    def oauth_status(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show OAuth secret aliases and provider health probes."""
        command = "sevn providers oauth status"
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
            "/api/v1/providers/health",
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        rows = _oauth_rows_from_health(body)
        try:
            entries = secrets_list(bound)
            aliases = [str(e.get("alias", "")) for e in entries]
        except Exception as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="GATEWAY_SECRETS_ERROR",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        oauth_aliases = sorted(a for a in aliases if a)
        openai_cred: dict[str, Any] | None = None
        if oauth_openai_secret_alias() in oauth_aliases:
            openai_cred = load_codex_oauth_credential_from_workspace(bound)
        data: dict[str, Any] = {
            "providers": rows,
            "oauth_secret_aliases": oauth_aliases,
        }
        if openai_cred:
            data["openai"] = openai_cred
        if json_out:
            emit_json_success(command=command, data=data)
            return
        typer.echo(_format_oauth_status(rows, oauth_aliases, openai_oauth=openai_cred))

    @oauth.command("login")
    def oauth_login(
        provider: str = typer.Option(..., "--provider", help="Provider id (e.g. anthropic)."),
        headless: bool = typer.Option(
            False,
            "--headless",
            help="Print authorize URL and accept a pasted redirect URL/code (D5).",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Start provider OAuth pairing (Codex PKCE for OpenAI)."""
        command = "sevn providers oauth login"
        provider_id = provider.strip().lower()
        if provider_id == "openai":
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
            _run_openai_oauth_login(bound, headless=headless, json_out=json_out, command=command)
            return

        alias = f"oauth.{provider.strip()}"
        msg = (
            f"Store an OAuth token at logical secret {alias!r} via your provider's OAuth flow. "
            f"Use `sevn secrets put {alias}` after obtaining a token, or complete pairing in "
            "Mission Control → System → Providers. "
            f"Dashboard reauth handoff: POST /api/v1/providers/{provider}/oauth/reauth"
        )
        if json_out:
            emit_json_success(
                command=command,
                data={"provider": provider, "logical_key": alias, "message": msg},
            )
            return
        typer.echo(msg)

    @oauth.command("logout")
    def oauth_logout(
        provider: str = typer.Option(..., "--provider", help="Provider id (e.g. anthropic)."),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    ) -> None:
        """Delete the ``oauth.<provider>`` logical secret via the gateway."""
        command = "sevn providers oauth logout"
        provider_id = provider.strip()
        alias = f"oauth.{provider_id}"
        if not yes and not json_out:
            typer.confirm(f"Delete logical secret {alias!r}?", abort=True)
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
        fingerprint = ""
        for entry in secrets_list(bound):
            if entry.get("alias") == alias:
                fingerprint = str(entry.get("fingerprint_sha256_hex") or "")
                break
        if not fingerprint:
            msg = f"logical secret {alias!r} not found"
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="SECRET_NOT_FOUND",
                    message=msg,
                    exit_code=4,
                )
            else:
                typer.secho(msg, err=True)
            raise typer.Exit(4)
        try:
            secrets_delete(
                bound,
                alias=alias,
                confirm_alias=alias,
                confirm_fingerprint=fingerprint,
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
        except httpx.HTTPStatusError as exc:
            detail = http_error_detail(exc.response)
            code = str(detail.get("error_code", "GATEWAY_SECRETS_ERROR"))
            message = str(detail.get("message", exc.response.text or code))
            if json_out:
                emit_json_failure(command=command, error_code=code, message=message, exit_code=4)
            else:
                typer.secho(message, err=True)
            raise typer.Exit(4) from exc
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
            emit_json_success(
                command=command,
                data={"alias": alias, "deleted": True, "provider": provider_id},
            )
            return
        typer.echo(f"deleted {alias}")
