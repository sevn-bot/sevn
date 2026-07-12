"""Typer root for the ``sevn`` operator CLI (`specs/23-cli.md` §2.1).

Module: sevn.cli.app
Depends: importlib.metadata, loguru, pathlib, sys, typer, sevn.cli.commands.*, sevn.cli.errors

Exports:
    main — console script entrypoint.
    version_detail — ``sevn version`` subcommand implementation.

Private:
    app — Typer application instance (not a function export).
"""

from __future__ import annotations

import json
import os
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

import typer
from loguru import logger

from sevn.cli.cli_activity_log import install_cli_activity_log, log_cli_invocation
from sevn.cli.commands.about_docs_cmd import register as register_about_docs
from sevn.cli.commands.agent_cmd import register as register_agent
from sevn.cli.commands.channels_cmd import register as register_channels
from sevn.cli.commands.completion import register as register_completion
from sevn.cli.commands.config_cmd import register as register_config
from sevn.cli.commands.dashboard_cmd import register as register_dashboard
from sevn.cli.commands.deploy_cmd import register as register_deploy
from sevn.cli.commands.doctor import register as register_doctor
from sevn.cli.commands.export_secrets_cmd import register as register_export_secrets
from sevn.cli.commands.gateway import register as register_gateway
from sevn.cli.commands.gh_cmd import register as register_gh
from sevn.cli.commands.gui_cmd import register as register_gui
from sevn.cli.commands.guide_cmd import register as register_guide
from sevn.cli.commands.improve_cmd import register as register_improve
from sevn.cli.commands.logs_cmd import register as register_logs
from sevn.cli.commands.memory_cmd import register as register_memory
from sevn.cli.commands.message_cmd import register as register_message
from sevn.cli.commands.migrate_cmd import register as register_migrate
from sevn.cli.commands.models_cmd import register as register_models
from sevn.cli.commands.onboard import register as register_onboard
from sevn.cli.commands.openwiki_cmd import register as register_openwiki
from sevn.cli.commands.pairing_cmd import register as register_pairing
from sevn.cli.commands.placeholders import register as register_placeholders
from sevn.cli.commands.providers_cmd import register as register_providers
from sevn.cli.commands.proxy_cmd import register as register_proxy
from sevn.cli.commands.readme_cmd import register as register_readme
from sevn.cli.commands.second_brain_cmd import register as register_second_brain
from sevn.cli.commands.secrets_cmd import register as register_secrets
from sevn.cli.commands.sessions import register as register_sessions
from sevn.cli.commands.shell_history_cmd import register as register_shell_history
from sevn.cli.commands.skills_cmd import register as register_skills
from sevn.cli.commands.subagents_cmd import register as register_subagents
from sevn.cli.commands.sync_cmd import register as register_sync
from sevn.cli.commands.telegram_test import register as register_telegram_test
from sevn.cli.commands.tools_cmd import register as register_tools
from sevn.cli.commands.traces_cmd import register as register_traces
from sevn.cli.commands.tracing_cmd import register as register_tracing
from sevn.cli.commands.tunnel_cmd import register as register_tunnel
from sevn.cli.commands.turn_bundle_cmd import register as register_turn_bundle
from sevn.cli.commands.unboard import register as register_unboard
from sevn.cli.commands.update_cmd import register as register_update
from sevn.cli.commands.usage_cmd import register as register_usage
from sevn.cli.commands.voice_cmd import register as register_voice
from sevn.cli.errors import CliAuthError, CliPreconditionError, CliUsageError
from sevn.cli.help.panels import apply_root_panels
from sevn.cli.render.console import configure_render

app = typer.Typer(
    name="sevn",
    help=(
        "sevn operator CLI for workspace setup, health checks, and local services.\n\n"
        "Exit codes: 0 success; 2 usage/argv; 3 auth; 4 precondition or not implemented.\n"
        "Non-TTY onboarding: use `sevn onboard --web` or `--config` (fast path) / `--profile`.\n"
        "`--json` (where implemented): `doctor`, `gateway status`, `proxy status`, "
        "`config show`, `config validate` — see each command's `--help`."
    ),
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    print_version: bool = typer.Option(
        False,
        "--version",
        help="Print CLI semver and exit.",
        is_eager=True,
    ),
    log_file: Path | None = typer.Option(
        None,
        "--log-file",
        help="Append redacted logs to this path (0600); fail early if not writable.",
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help="Disable ANSI color and Rich formatting on stdout.",
    ),
    no_cli_log: bool = typer.Option(
        False,
        "--no-cli-log",
        help="Disable default-on operator activity log at {workspace}/logs/cli.log.",
    ),
) -> None:
    """Handle global options before subcommands run.
    Args:
        ctx (typer.Context): Typer invocation context.
        print_version (bool): When True, print semver and exit.
        log_file (Path | None): Optional log file path.
        no_color (bool): Disable Rich/ANSI when True.
        no_cli_log (bool): Disable ``cli.log`` activity sink when True.
    Examples:
        >>> from unittest.mock import MagicMock, patch
        >>> import typer
        >>> ctx = MagicMock(invoked_subcommand=None)
        >>> ctx.get_help = MagicMock(return_value="help")
        >>> with patch.object(typer, "echo"):
        ...     try:
        ...         _root(ctx, print_version=False, log_file=None, no_color=False, no_cli_log=True)
        ...     except typer.Exit as exc:
        ...         exc.exit_code == 0
        ...     else:
        ...         False
        True
    """
    configure_render(no_color=no_color)
    if not no_cli_log:
        install_cli_activity_log(enabled=True)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            if not log_file.exists():
                log_file.touch(mode=0o600)
            else:
                os.chmod(log_file, 0o600)
            logger.add(
                log_file,
                format="{level} {name} {message}",
                level="INFO",
                mode="a",
                encoding="utf-8",
            )
        except OSError as exc:
            typer.secho(f"cannot open --log-file {log_file}: {exc}", err=True)
            raise typer.Exit(4) from exc
    log_cli_invocation(subcommand=ctx.invoked_subcommand)
    if print_version:
        try:
            v = pkg_version("sevn")
        except PackageNotFoundError:
            v = "0.0.0"
        typer.echo(v)
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help(), err=False)
        raise typer.Exit(0)


@app.command("version")
def version_detail(
    verbose: bool = typer.Option(False, "--verbose", help="Extra build/runtime lines."),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON diagnostic object on stdout without the standard success envelope.",
    ),
) -> None:
    """Show CLI version metadata.
    Args:
        verbose (bool): Include Python runtime string when True.
        json_out (bool): Emit JSON with ``cli_version`` keys.
    Examples:
        >>> import typer
        >>> from unittest.mock import patch
        >>> with patch.object(typer, "echo"):
        ...     try:
        ...         version_detail(verbose=False, json_out=False)
        ...     except typer.Exit as exc:
        ...         exc.exit_code == 0
        ...     else:
        ...         False
        True
    """
    try:
        cli_version = pkg_version("sevn")
    except PackageNotFoundError:
        cli_version = "0.0.0"
    if json_out:
        payload = {
            "cli_version": cli_version,
            "python_version": sys.version.split()[0],
            "gateway_api_min": "0",
        }
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(0)
    typer.echo(cli_version)
    if verbose:
        typer.echo(sys.version)
    raise typer.Exit(0)


register_doctor(app)
register_onboard(app)
register_pairing(app)
register_export_secrets(app)
register_unboard(app)
register_migrate(app)
register_gateway(app)
register_proxy(app)
register_tunnel(app)
register_logs(app)
register_traces(app)
register_config(app)
register_completion(app)
register_memory(app)
register_improve(app)
register_secrets(app)
register_second_brain(app)
register_tracing(app)
register_shell_history(app)
register_gh(app)
register_openwiki(app)
register_skills(app)
register_subagents(app)
register_sync(app)
register_telegram_test(app)
register_turn_bundle(app)
register_dashboard(app)
register_agent(app)
register_models(app)
register_voice(app)
register_channels(app)
register_tools(app)
register_usage(app)
register_providers(app)
register_message(app)
register_gui(app)
register_sessions(app)
register_update(app)
register_deploy(app)
register_placeholders(app)
register_readme(app)
register_about_docs(app)
register_guide(app)
apply_root_panels(app)


def main() -> None:
    """Invoke the Typer application with stable exit-code mapping.
    Examples:
        >>> import io
        >>> import sys
        >>> from unittest.mock import patch
        >>> buf_out, buf_err = io.StringIO(), io.StringIO()
        >>> with patch.object(sys, "argv", ["sevn", "--help"]), patch.object(
        ...     sys, "stdout", buf_out
        ... ), patch.object(sys, "stderr", buf_err):
        ...     try:
        ...         main()
        ...     except SystemExit as exc:
        ...         code = int(exc.code)
        ...     else:
        ...         code = None
        >>> code == 0
        True
    """
    try:
        app()
    except CliUsageError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(2) from exc
    except CliAuthError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(3) from exc
    except CliPreconditionError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(getattr(exc, "exit_code", 4)) from exc
