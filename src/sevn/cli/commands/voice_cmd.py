"""``sevn voice`` — workspace voice settings and provider health (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.voice_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.workspace

Exports:
    register — attach ``voice`` command group to the root Typer app.
"""

from __future__ import annotations

from typing import Any

import typer

from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.config.defaults import DEFAULT_VOICE_STT_PROVIDERS, DEFAULT_VOICE_TTS_PROVIDERS
from sevn.config.workspace_config import WorkspaceConfig


def _voice_settings_snapshot(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Build a JSON-serializable voice config snapshot from ``sevn.json``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.

    Returns:
        dict[str, Any]: Local voice settings (no live probes).

    Examples:
        >>> snap = _voice_settings_snapshot(WorkspaceConfig.minimal())
        >>> "stt_providers" in snap and "tts_providers" in snap
        True
    """
    voice = workspace.voice
    stt = (
        list(voice.stt_providers)
        if voice and voice.stt_providers
        else list(DEFAULT_VOICE_STT_PROVIDERS)
    )
    tts = (
        list(voice.tts_providers)
        if voice and voice.tts_providers
        else list(DEFAULT_VOICE_TTS_PROVIDERS)
    )
    return {
        "enabled": bool(voice.enabled) if voice and voice.enabled is not None else None,
        "tts_mode": voice.tts_mode if voice else None,
        "tts_voice_id": voice.tts_voice_id if voice else None,
        "stt_providers": stt,
        "tts_providers": tts,
        "voice_trigger_keywords": list(voice.voice_trigger_keywords or [])
        if voice and voice.voice_trigger_keywords
        else [],
        "max_voice_mb": voice.max_voice_mb if voice else None,
        "max_voice_seconds": voice.max_voice_seconds if voice else None,
    }


def _format_voice_settings(data: dict[str, Any]) -> str:
    """Render local voice settings as plain text.

    Args:
        data (dict[str, Any]): Snapshot from ``_voice_settings_snapshot``.

    Returns:
        str: Human-readable lines.

    Examples:
        >>> "stt_providers" in _format_voice_settings({"stt_providers": ["x"], "tts_providers": []})
        True
    """
    lines = [
        f"enabled: {data.get('enabled')}",
        f"tts_mode: {data.get('tts_mode')}",
        f"tts_voice_id: {data.get('tts_voice_id')}",
        f"stt_providers: {', '.join(data.get('stt_providers') or []) or '—'}",
        f"tts_providers: {', '.join(data.get('tts_providers') or []) or '—'}",
    ]
    keywords = data.get("voice_trigger_keywords") or []
    if keywords:
        lines.append(f"voice_trigger_keywords: {', '.join(str(k) for k in keywords)}")
    return "\n".join(lines)


def _voice_provider_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter provider health rows to voice STT/TTS backends.

    Args:
        body (dict[str, Any]): ``GET /api/v1/providers/health`` payload.

    Returns:
        list[dict[str, Any]]: Matching provider rows.

    Examples:
        >>> _voice_provider_rows({"providers": [{"id": "voice_stt.whisper"}]})
        [{'id': 'voice_stt.whisper'}]
    """
    providers = body.get("providers")
    if not isinstance(providers, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in providers:
        if not isinstance(row, dict):
            continue
        provider_id = str(row.get("id") or row.get("provider_id") or "")
        if provider_id.startswith("voice_"):
            rows.append(row)
    return rows


def _format_voice_status(rows: list[dict[str, Any]]) -> str:
    """Render voice provider probe rows as plain text.

    Args:
        rows (list[dict[str, Any]]): Filtered provider health rows.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> _format_voice_status([])
        'voice_providers: 0'
    """
    lines = [f"voice_providers: {len(rows)}"]
    for row in rows:
        provider_id = row.get("id") or row.get("provider_id") or "?"
        status = row.get("status") or row.get("state") or "?"
        detail = row.get("detail") or row.get("message") or ""
        suffix = f" ({detail})" if detail else ""
        lines.append(f"  {provider_id}: {status}{suffix}")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach ``sevn voice`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    voice = typer.Typer(
        help="Inspect voice/STT/TTS settings and live provider health.",
        invoke_without_command=True,
    )
    app.add_typer(voice, name="voice")

    @voice.callback()
    def voice_root(
        ctx: typer.Context,
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        if ctx.invoked_subcommand is not None:
            return
        _voice_show(json_out=json_out)

    @voice.command("show")
    def voice_show(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show voice settings from the bound workspace ``sevn.json``."""
        _voice_show(json_out=json_out)

    @voice.command("status")
    def voice_status(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Probe configured voice STT/TTS backends via the gateway."""
        command = "sevn voice status"
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
        rows = _voice_provider_rows(body)
        if json_out:
            emit_json_success(command=command, data={"providers": rows, "raw": body})
            return
        typer.echo(_format_voice_status(rows))


def _voice_show(*, json_out: bool) -> None:
    """Shared implementation for ``sevn voice`` and ``sevn voice show``.

    Args:
        json_out (bool): Emit JSON success envelope on stdout when True.

    Examples:
        >>> _voice_show(json_out=False)  # doctest: +SKIP
    """
    command = "sevn voice show"
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
    data = _voice_settings_snapshot(bound.config)
    if json_out:
        emit_json_success(command=command, data=data)
        return
    typer.echo(_format_voice_settings(data))


__all__ = ["register"]
