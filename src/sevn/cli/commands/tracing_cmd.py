"""``sevn tracing`` and ``sevn config tracing`` helpers (`specs/23-cli.md`).

Module: sevn.cli.commands.tracing_cmd
Depends: asyncio, typer, sevn.agent.tracing.logfire_config, sevn.cli.workspace,
    sevn.gateway.config_io.workspace_config_io, sevn.security.secrets.factory

Exports:
    register — attach ``tracing`` Typer subapp to the root CLI.
    show_tracing_config — print Logfire export status for ``sevn config tracing``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer

from sevn.agent.tracing.logfire_config import (
    DEFAULT_LOGFIRE_TOKEN_REF,
    LOGFIRE_SECRET_LOGICAL_KEY,
    LogfireExportStatus,
    apply_logfire_export_to_sevn_doc,
    logfire_export_status,
)
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json, mutate_sevn_json
from sevn.security.secrets.factory import secrets_chain_from_workspace


def _status_payload(status: LogfireExportStatus) -> dict[str, Any]:
    """Serialize :class:`LogfireExportStatus` for CLI JSON output.

    Args:
        status (LogfireExportStatus): Resolved export posture.

    Returns:
        dict[str, Any]: JSON-safe status payload.

    Examples:
        >>> _status_payload(LogfireExportStatus(False, None, None, ()))["logfire_enabled"]
        False
    """
    return {
        "logfire_enabled": status.enabled,
        "logfire_token_ref": status.token_ref,
        "logfire_project": status.project,
        "local_sinks": list(status.local_sinks),
    }


def show_tracing_config(*, json_out: bool = False) -> None:
    """Print tracing / Logfire export status for ``sevn config tracing``.

    Args:
        json_out (bool): Emit JSON envelope when True.

    Examples:
        >>> show_tracing_config(json_out=False)  # doctest: +SKIP
    """
    bw = load_bound_workspace()
    status = logfire_export_status(bw.config)
    payload = _status_payload(status)
    if json_out:
        emit_json_success(command="sevn config tracing", data=payload)
        return
    typer.echo("Tracing export")
    typer.echo(f"  Logfire sink: {'enabled' if status.enabled else 'disabled'}")
    if status.token_ref:
        typer.echo(f"  token_ref: {status.token_ref}")
    if status.project:
        typer.echo(f"  project: {status.project}")
    if status.local_sinks:
        typer.echo(f"  local sinks: {', '.join(status.local_sinks)}")
    else:
        typer.echo("  local sinks: none")
    typer.echo("")
    typer.echo("Enable:  sevn tracing logfire enable [--token TOKEN]")
    typer.echo("Disable: sevn tracing logfire disable")
    typer.echo("Restart the gateway after changing export settings.")


async def _store_logfire_token(content_root: Any, token: str) -> None:
    """Persist a Logfire bearer token in the workspace secrets chain.

    Args:
        content_root (Any): Workspace content root path.
        token (str): Logfire write token plaintext.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(_store_logfire_token(Path('.'), 'tok'))  # doctest: +SKIP
    """
    bw = load_bound_workspace()
    chain = secrets_chain_from_workspace(content_root, bw.config.secrets_backend)
    await chain.set(LOGFIRE_SECRET_LOGICAL_KEY, token.strip())


def _apply_logfire_export(
    *,
    enabled: bool,
    token: str | None = None,
    token_ref: str | None = None,
    project: str | None = None,
    keep_local: bool = True,
) -> LogfireExportStatus:
    """Mutate ``sevn.json`` Logfire export settings and return the new status.

    Args:
        enabled (bool): Add or remove the Logfire sink.
        token (str | None): Optional token to store in secrets.
        token_ref (str | None): Optional ``token_ref`` override.
        project (str | None): Optional service name override.
        keep_local (bool): Retain sqlite/jsonl sinks when enabling.

    Returns:
        LogfireExportStatus: Post-mutation export posture.

    Examples:
        >>> _apply_logfire_export(enabled=False)  # doctest: +SKIP
    """
    bw = load_bound_workspace()
    sevn_json = bw.layout.sevn_json_path
    if token:
        asyncio.run(_store_logfire_token(bw.layout.content_root, token))
        token_ref = token_ref or DEFAULT_LOGFIRE_TOKEN_REF

    def _mutate(doc: dict[str, Any]) -> None:
        apply_logfire_export_to_sevn_doc(
            doc,
            enabled=enabled,
            token_ref=token_ref,
            project=project,
            keep_local_sinks=keep_local,
        )

    mutate_sevn_json(sevn_json, _mutate)
    doc = load_raw_sevn_json(sevn_json)
    return logfire_export_status(WorkspaceConfig.model_validate(doc))


def register(app: typer.Typer) -> None:
    """Attach ``tracing`` Typer subapp to ``app``.

    Args:
        app (typer.Typer): Root CLI application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    tracing = typer.Typer(no_args_is_help=True, help="Trace export configuration (Logfire).")
    app.add_typer(tracing, name="tracing")

    logfire = typer.Typer(no_args_is_help=True, help="Logfire trace export.")
    tracing.add_typer(logfire, name="logfire")

    @logfire.command("enable")
    def logfire_enable(
        token: str | None = typer.Option(
            None,
            "--token",
            help="Store this Logfire write token in the workspace secrets chain.",
        ),
        token_ref: str | None = typer.Option(
            None,
            "--token-ref",
            help="Override tracing.sinks[].token_ref (default: encrypted_file:logfire.token).",
        ),
        project: str | None = typer.Option(
            None,
            "--project",
            help="Logfire service.name override (default: sevn-gateway).",
        ),
        logfire_only: bool = typer.Option(
            False,
            "--logfire-only",
            help="Drop sqlite/jsonl sinks so new spans export only to Logfire.",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON result."),
    ) -> None:
        """Add a Logfire sink to ``tracing.sinks[]`` and optionally store the token."""
        try:
            status = _apply_logfire_export(
                enabled=True,
                token=token,
                token_ref=token_ref,
                project=project,
                keep_local=not logfire_only,
            )
        except CliPreconditionError as exc:
            raise typer.Exit(4) from exc
        except Exception as exc:
            typer.secho(f"Could not enable Logfire export: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        if json_out:
            emit_json_success(command="sevn tracing logfire enable", data=_status_payload(status))
            return
        typer.echo("Logfire export enabled in sevn.json.")
        if token:
            typer.echo(f"Stored token under secrets key `{LOGFIRE_SECRET_LOGICAL_KEY}`.")
        typer.echo("Restart the gateway: sevn gateway restart")

    @logfire.command("disable")
    def logfire_disable(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON result."),
    ) -> None:
        """Remove the Logfire sink from ``tracing.sinks[]``."""
        try:
            status = _apply_logfire_export(enabled=False)
        except CliPreconditionError as exc:
            raise typer.Exit(4) from exc
        except Exception as exc:
            typer.secho(f"Could not disable Logfire export: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        if json_out:
            emit_json_success(command="sevn tracing logfire disable", data=_status_payload(status))
            return
        typer.echo("Logfire export disabled in sevn.json.")
        typer.echo("Restart the gateway: sevn gateway restart")


__all__ = ["register", "show_tracing_config"]
