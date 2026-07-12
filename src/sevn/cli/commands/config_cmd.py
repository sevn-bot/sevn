"""``sevn config`` (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.config_cmd
Depends: json, copy, typer, sevn.cli.errors, sevn.cli.json_util, sevn.cli.workspace,
    sevn.cli.workspace_schema, sevn.onboarding.draft_store, sevn.onboarding.promote,
    sevn.onboarding.validate, sevn.onboarding.web_app

Exports:
    register — attach ``config`` subcommands.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import NoReturn

import typer
from pydantic import ValidationError

from sevn.cli.config_paths import iter_config_sections, section_by_slug
from sevn.cli.config_sections import format_section_plain, section_payload
from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.workspace import load_bound_workspace
from sevn.cli.workspace_schema import (
    config_set_reload_hint,
    dotted_path_in_schema,
    load_workspace_json_schema,
    parse_config_set_value,
)
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.config.model_resolution import maybe_split_unified_model_on_config_set
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import _set_nested


def _config_set_fail(
    *,
    command: str,
    error_code: str,
    message: str,
    exit_code: int,
    json_out: bool,
) -> NoReturn:
    """Emit config-set failure output and exit.

    Args:
        command (str): Command label for JSON envelopes.
        error_code (str): Stable machine-readable code.
        message (str): Human-readable message.
        exit_code (int): Process exit code.
        json_out (bool): When True, emit JSON to stdout.

    Returns:
        NoReturn: Never returns normally.

    Raises:
        typer.Exit: Always raised after emitting output.

    Examples:
        >>> try:
        ...     _config_set_fail(
        ...         command="sevn config set",
        ...         error_code="USAGE",
        ...         message="bad",
        ...         exit_code=2,
        ...         json_out=False,
        ...     )
        ... except typer.Exit as exc:
        ...     exc.exit_code == 2
        ... except SystemExit:
        ...     pass
        True
    """
    if json_out:
        emit_json_failure(
            command=command,
            error_code=error_code,
            message=message,
            exit_code=exit_code,
        )
    else:
        typer.secho(message, err=True)
    raise typer.Exit(exit_code)


def _show_config_section(slug: str, *, json_out: bool) -> None:
    """Print one ``/config`` section summary and exit.

    Args:
        slug (str): Section slug.
        json_out (bool): Emit JSON envelope when True.

    Raises:
        typer.Exit: On unknown slug or workspace errors.

    Examples:
        >>> import typer
        >>> try:
        ...     _show_config_section("not-real", json_out=False)
        ... except typer.Exit as exc:
        ...     exc.exit_code == 2
        ... else:
        ...     False
        True
    """
    section = section_by_slug(slug)
    if section is None:
        message = f"unknown config section {slug!r}; run `sevn config sections`"
        if json_out:
            emit_json_failure(
                command=f"sevn config {slug}",
                error_code="USAGE",
                message=message,
                exit_code=2,
            )
        else:
            typer.secho(message, err=True)
        raise typer.Exit(2)
    try:
        bw = load_bound_workspace()
    except CliPreconditionError as exc:
        if json_out:
            emit_json_failure(
                command=f"sevn config {slug}",
                error_code="WORKSPACE_PRECONDITION",
                message=str(exc),
                exit_code=4,
            )
        else:
            typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc
    if json_out:
        emit_json_success(
            command=f"sevn config {slug}",
            data=section_payload(section, bw.raw),
        )
    else:
        typer.echo(format_section_plain(section, bw.raw))
    raise typer.Exit(0)


def register(app: typer.Typer) -> None:
    """Attach ``sevn config`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    cfg = typer.Typer(
        help="Inspect and validate the bound workspace ``sevn.json`` file.",
        invoke_without_command=True,
    )
    app.add_typer(cfg, name="config")

    @cfg.callback()
    def config_root(ctx: typer.Context) -> None:
        """Open the interactive section menu when no subcommand is given."""
        if ctx.invoked_subcommand is not None:
            return
        from sevn.cli.tui.config_menu import run_config_menu

        slug = run_config_menu()
        if slug is None:
            typer.echo(ctx.get_help())
            raise typer.Exit(0)
        _show_config_section(slug, json_out=False)

    @cfg.command("sections")
    def config_sections(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit JSON list of sections and dot-paths.",
        ),
    ) -> None:
        """List Telegram ``/config`` sections and ``sevn.json`` dot-path SSOT."""
        sections = iter_config_sections()
        if json_out:
            emit_json_success(
                command="sevn config sections",
                data={
                    "sections": [
                        {
                            "slug": sec.slug,
                            "label": sec.label,
                            "callback": sec.callback,
                            "dot_paths": list(sec.dot_paths),
                        }
                        for sec in sections
                    ]
                },
            )
        else:
            typer.echo("sevn config sections (Telegram /config parity):\n")
            for sec in sections:
                typer.echo(f"  {sec.slug:<16} {sec.label}")
            typer.echo("\nRun `sevn config <slug>` or `sevn config` for the interactive menu.")
        raise typer.Exit(0)

    for _section in iter_config_sections():

        def _make_section_handler(section_slug: str) -> Callable[[], None]:
            def _handler(
                json_out: bool = typer.Option(
                    False,
                    "--json",
                    help="Emit JSON section summary.",
                ),
            ) -> None:
                _show_config_section(section_slug, json_out=json_out)

            _handler.__name__ = f"config_{section_slug}"
            return _handler

        cfg.command(
            _section.slug,
            help=f"Show {_section.label} keys ({_section.callback}).",
        )(_make_section_handler(_section.slug))

    @cfg.command("second-brain")
    def config_second_brain(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit JSON envelope with resolved paths and layout status.",
        ),
    ) -> None:
        """Show Second Brain enabled state, vault path, and layout status."""
        from sevn.cli.commands.second_brain_cmd import show_second_brain_config

        show_second_brain_config(json_out=json_out)

    @cfg.command("subagents")
    def config_subagents(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit JSON envelope with limits, enabled flag, and orphan count.",
        ),
    ) -> None:
        """Show sub-agent limits, enabled flag, and storage orphan count."""
        from sevn.cli.commands.subagents_cmd import show_subagents_config

        show_subagents_config(json_out=json_out)

    @cfg.command("tracing")
    def config_tracing(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit JSON envelope with Logfire export status.",
        ),
    ) -> None:
        """Show trace export status and Logfire sink configuration."""
        from sevn.cli.commands.tracing_cmd import show_tracing_config

        show_tracing_config(json_out=json_out)

    @cfg.command("show")
    def config_show(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Print bound ``sevn.json`` (redact in future; raw JSON for v1)."""
        try:
            bw = load_bound_workspace()
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command="sevn config show",
                    error_code="WORKSPACE_PRECONDITION",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        if json_out:
            emit_json_success(
                command="sevn config show",
                data={"sevn_json": str(bw.sevn_json_path), "document": bw.raw},
            )
        else:
            typer.echo(json.dumps(bw.raw, indent=2, sort_keys=True))
        raise typer.Exit(0)

    @cfg.command("validate")
    def config_validate(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Re-parse bound ``sevn.json`` with schema gate."""
        try:
            bw = load_bound_workspace()
        except CliPreconditionError as exc:
            if json_out:
                emit_json_failure(
                    command="sevn config validate",
                    error_code="WORKSPACE_PRECONDITION",
                    message=str(exc),
                    exit_code=4,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        try:
            validate_workspace_document(bw.raw)
        except ValueError as exc:
            if json_out:
                emit_json_failure(
                    command="sevn config validate",
                    error_code="VALIDATION",
                    message=str(exc),
                    exit_code=1,
                )
            else:
                typer.secho(str(exc), err=True)
            raise typer.Exit(1) from exc
        from sevn.config.workspace_config import parse_workspace_config
        from sevn.onboarding.live_validate import emit_openai_oauth_warnings
        from sevn.onboarding.validate import emit_unused_provider_warnings
        from sevn.security.secrets.factory import secrets_chain_from_workspace

        emit_unused_provider_warnings(parse_workspace_config(bw.raw), echo=typer.secho)
        chain = secrets_chain_from_workspace(bw.layout.content_root, bw.config.secrets_backend)
        emit_openai_oauth_warnings(bw.raw, echo=typer.secho, secrets_chain=chain)
        if json_out:
            emit_json_success(
                command="sevn config validate",
                data={"sevn_json": str(bw.sevn_json_path), "ok": True},
            )
        else:
            typer.echo("sevn.json: valid")
        raise typer.Exit(0)

    @cfg.command("set")
    def config_set(
        dot_path: str = typer.Argument(
            ...,
            help="Dot-separated key path in sevn.json (e.g. gateway.port).",
        ),
        value: str = typer.Argument(
            ...,
            help="JSON literal or string value to assign.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write JSON success or failure envelopes to stdout.",
        ),
    ) -> None:
        """Set a key in bound ``sevn.json`` (atomic promote)."""
        command = "sevn config set"
        dotted = dot_path.strip()
        if not dotted:
            _config_set_fail(
                command=command,
                error_code="USAGE",
                message="dot path must not be empty",
                exit_code=2,
                json_out=json_out,
            )
        try:
            schema = load_workspace_json_schema()
        except (OSError, json.JSONDecodeError) as exc:
            _config_set_fail(
                command=command,
                error_code="WORKSPACE_PRECONDITION",
                message=f"cannot load infra/sevn.schema.json: {exc}",
                exit_code=4,
                json_out=json_out,
            )
        if not dotted_path_in_schema(schema, dotted):
            _config_set_fail(
                command=command,
                error_code="USAGE",
                message=f"unknown config key {dotted!r} (not in infra/sevn.schema.json)",
                exit_code=2,
                json_out=json_out,
            )
        try:
            bw = load_bound_workspace()
        except CliPreconditionError as exc:
            _config_set_fail(
                command=command,
                error_code="WORKSPACE_PRECONDITION",
                message=str(exc),
                exit_code=4,
                json_out=json_out,
            )
        parsed_value = parse_config_set_value(value)
        updated = copy.deepcopy(bw.raw)
        _set_nested(updated, dotted, parsed_value)
        maybe_split_unified_model_on_config_set(updated, dotted, parsed_value)
        try:
            validate_workspace_document(updated)
        except (ValidationError, UnsupportedSchemaVersionError, ValueError) as exc:
            _config_set_fail(
                command=command,
                error_code="USAGE",
                message=str(exc),
                exit_code=2,
                json_out=json_out,
            )
        write_draft(bw.sevn_json_path, updated)
        promote_draft(bw.sevn_json_path, backup_previous=bw.sevn_json_path.is_file())
        hint = config_set_reload_hint(dotted)
        if hint and not json_out:
            typer.secho(hint, err=True)
        if json_out:
            emit_json_success(
                command=command,
                data={
                    "sevn_json": str(bw.sevn_json_path),
                    "path": dotted,
                    "value": parsed_value,
                },
            )
        else:
            typer.echo(f"set {dotted}")
        raise typer.Exit(0)
