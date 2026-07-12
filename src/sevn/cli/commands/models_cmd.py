"""``sevn models`` — model slots and LLM sampling params (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.models_cmd
Depends: typer, sevn.cli.dashboard_api_client, sevn.cli.json_util, sevn.cli.workspace,
    sevn.config.llm_params

Exports:
    register — attach ``models`` command group to the root Typer app.
"""

from __future__ import annotations

from typing import Any

import typer

from sevn.cli.commands.agent_cmd import _format_agent_config
from sevn.cli.dashboard_api_client import dashboard_api_get
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.config.llm_params import AGENT_NAMES, set_agent_model_max_output_tokens


def _format_llm_params(body: dict[str, Any]) -> str:
    """Render LLM params document metadata as plain text.

    Args:
        body (dict[str, Any]): ``GET /api/v1/agent/llm-params`` payload.

    Returns:
        str: Human-readable summary.

    Examples:
        >>> "source" in _format_llm_params({"source": "builtin", "doc": {}})
        True
    """
    lines = [
        f"source: {body.get('source', '—')}",
        f"path: {body.get('path', '—')}",
        f"restart_required: {body.get('restart_required', True)}",
    ]
    doc = body.get("doc")
    if isinstance(doc, dict) and doc:
        lines.append("agents:")
        for key in sorted(doc):
            val = doc.get(key)
            if isinstance(val, dict):
                temp = val.get("temperature")
                top_p = val.get("top_p")
                lines.append(f"  {key}: temperature={temp!r} top_p={top_p!r}")
            else:
                lines.append(f"  {key}: {val!r}")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach ``sevn models`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    models = typer.Typer(
        help="Inspect resolved model slots and per-agent LLM sampling parameters.",
        invoke_without_command=True,
    )
    app.add_typer(models, name="models")

    @models.callback()
    def models_root(
        ctx: typer.Context,
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        if ctx.invoked_subcommand is not None:
            return
        _models_show(json_out=json_out)

    @models.command("show")
    def models_show(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show resolved model slots (same payload as ``sevn agent config``)."""
        _models_show(json_out=json_out)

    @models.command("params")
    def models_params(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Show workspace ``LLM_params_config.json`` (sampling overrides)."""
        command = "sevn models params"
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
            "/api/v1/agent/llm-params",
            command=command,
            workspace=bound.config,
            json_out=json_out,
        )
        if json_out:
            emit_json_success(command=command, data=body)
            return
        typer.echo(_format_llm_params(body))

    @models.command("set-max-output-tokens")
    def models_set_max_output_tokens(
        agent: str = typer.Argument(..., help=f"Agent name ({', '.join(AGENT_NAMES)})."),
        max_output_tokens: int = typer.Argument(..., min=1, help="Max output token cap."),
        model: str | None = typer.Option(
            None,
            "--model",
            "-m",
            help="Model id or override pattern (e.g. minimax/*). Omit for agent default.",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Set ``max_output_tokens`` in workspace ``LLM_params_config.json``."""
        command = "sevn models set-max-output-tokens"
        agent_norm = agent.strip()
        if agent_norm not in AGENT_NAMES:
            message = f"unknown agent {agent_norm!r}; expected one of {', '.join(AGENT_NAMES)}"
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="USAGE",
                    message=message,
                    exit_code=2,
                )
            else:
                typer.secho(message, err=True)
            raise typer.Exit(2)
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
        try:
            path = set_agent_model_max_output_tokens(
                bound.layout.content_root,
                agent=agent_norm,
                max_output_tokens=max_output_tokens,
                model_id=model.strip() if model is not None else None,
            )
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command=command,
                    error_code="VALIDATION",
                    message=str(exc),
                    exit_code=2,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(2) from exc
        data = {
            "agent": agent_norm,
            "max_output_tokens": max_output_tokens,
            "model_id": model.strip() if model is not None else None,
            "path": str(path),
            "restart_required": True,
        }
        if json_out:
            emit_json_success(command=command, data=data)
            return
        scope = f"model_overrides[{model!r}]" if model is not None else "agent block"
        typer.echo(
            f"Updated {agent_norm} {scope} max_output_tokens={max_output_tokens} in {path}\n"
            "Restart the gateway for the change to take effect."
        )


def _models_show(*, json_out: bool) -> None:
    """Shared implementation for ``sevn models`` and ``sevn models show``.

    Args:
        json_out (bool): Emit JSON success envelope on stdout when True.

    Examples:
        >>> _models_show(json_out=False)  # doctest: +SKIP
    """
    command = "sevn models show"
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
        "/api/v1/agent/config",
        command=command,
        workspace=bound.config,
        json_out=json_out,
    )
    if json_out:
        emit_json_success(command=command, data=body)
        return
    typer.echo(_format_agent_config(body))


__all__ = ["register"]
