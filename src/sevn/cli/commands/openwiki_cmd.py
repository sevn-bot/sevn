"""``sevn openwiki`` — install and configure LangChain OpenWiki.

Module: sevn.cli.commands.openwiki_cmd
Depends: sys, typer, sevn.cli.commands.secrets_cmd, sevn.skills.openwiki_install

Exports:
    register — attach ``openwiki`` command group to the root Typer app.
    echo_openwiki_intro — print setup guidance for operators.
"""

from __future__ import annotations

import sys

import typer

from sevn.cli.commands.secrets_cmd import execute_secrets_put
from sevn.skills.openwiki_install import (
    MIN_NODE_MAJOR,
    OPENWIKI_NPM_PACKAGE,
    openwiki_cli_installed,
    run_openwiki_install,
)
from sevn.skills.openwiki_secrets import OPENWIKI_LLM_API_KEY_SECRET

OPENWIKI_UPSTREAM_URL = "https://github.com/langchain-ai/openwiki"

_OPENWIKI_GROUP_HELP = (
    "LangChain OpenWiki helpers for sevn.\n\n"
    "OpenWiki generates LLM-authored wiki pages for a codebase. When "
    "``skills.openwiki.enabled`` is true, sevn forwards credentials from "
    "sevn secrets into the OpenWiki subprocess.\n\n"
    "Quick start:\n"
    "  1. sevn openwiki install\n"
    "  2. sevn openwiki configure --stdin\n"
    "  3. Enable ``skills.openwiki.enabled`` in sevn.json or Telegram /config\n\n"
    f"Upstream: {OPENWIKI_UPSTREAM_URL}"
)


def echo_openwiki_intro() -> None:
    """Print OpenWiki setup guidance for operators.

    Examples:
        >>> echo_openwiki_intro()  # doctest: +SKIP
    """
    installed = "installed" if openwiki_cli_installed() else "not installed"
    typer.echo("LangChain OpenWiki — LLM-generated agent wiki for a codebase.")
    typer.echo("")
    typer.echo(f"  CLI status: openwiki is {installed} on PATH")
    typer.echo(f"  Requires: Node >= {MIN_NODE_MAJOR}, npm, npm package {OPENWIKI_NPM_PACKAGE!r}")
    typer.echo("")
    typer.echo("Install and configure:")
    typer.echo("  sevn openwiki install")
    typer.echo("  sevn openwiki configure --stdin")
    typer.echo("")
    typer.echo(
        "Or run both: sevn openwiki setup --stdin\n"
        "Then set skills.openwiki.enabled: true in sevn.json or enable via Telegram /config."
    )


def register(app: typer.Typer) -> None:
    """Attach ``openwiki`` commands to the root Typer app.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    openwiki = typer.Typer(
        help=_OPENWIKI_GROUP_HELP,
        no_args_is_help=False,
    )
    app.add_typer(openwiki, name="openwiki")

    @openwiki.callback(invoke_without_command=True)
    def openwiki_root(ctx: typer.Context) -> None:
        """LangChain OpenWiki install and credential helpers."""
        if ctx.invoked_subcommand is None:
            echo_openwiki_intro()
            typer.echo("")
            typer.echo(ctx.get_help())
            raise typer.Exit(0)

    @openwiki.command("install")
    def install(
        force: bool = typer.Option(
            False,
            "--force",
            help="Run npm install even when openwiki is already on PATH.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON success or failure envelope to stdout.",
        ),
    ) -> None:
        """Install the upstream ``openwiki`` npm CLI globally."""
        code, detail = run_openwiki_install(skip_if_installed=not force)
        if json_out:
            import json

            typer.echo(
                json.dumps(
                    {
                        "ok": code == 0,
                        "command": "sevn openwiki install",
                        "detail": detail,
                        "installed": openwiki_cli_installed(),
                    }
                )
            )
        elif code == 0:
            typer.echo(detail)
        else:
            typer.secho(detail, err=True)
        if code != 0:
            raise typer.Exit(code if code > 0 else 1)

    @openwiki.command("configure")
    def configure(
        value: str | None = typer.Option(
            None,
            "--value",
            help="OpenWiki LLM API key plaintext (prefer --stdin for safety).",
        ),
        stdin: bool = typer.Option(
            False,
            "--stdin",
            help="Read key from stdin, or prompt securely when run in a terminal.",
        ),
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
        """Store ``integration.openwiki.llm_api_key`` for the bundled OpenWiki skill."""
        if stdin:
            typer.echo(
                "Paste the LLM API key for your OpenWiki provider "
                f"(stored as {OPENWIKI_LLM_API_KEY_SECRET})."
            )
            typer.echo(
                "Match ``skills.openwiki.provider`` in sevn.json "
                "(openrouter, openai, anthropic, fireworks, baseten)."
            )
            typer.echo(
                "You can skip this when an assigned provider secret already covers OpenWiki."
            )
            typer.echo("")

        if value is None and not stdin:
            typer.secho(
                "configure: provide --value, --stdin, or pipe one line into stdin",
                err=True,
            )
            raise typer.Exit(4)

        execute_secrets_put(
            alias=OPENWIKI_LLM_API_KEY_SECRET,
            command="sevn openwiki configure",
            value=value,
            stdin=stdin,
            confirm_fingerprint=confirm_fingerprint,
            json_out=json_out,
            stdin_prompt="OpenWiki LLM API key: ",
        )

    @openwiki.command("setup")
    def setup(
        stdin: bool = typer.Option(
            True,
            "--stdin/--no-stdin",
            help="Prompt for the OpenWiki LLM API key after install (default: prompt).",
        ),
        force_install: bool = typer.Option(
            False,
            "--force-install",
            help="Run npm install even when openwiki is already on PATH.",
        ),
        skip_configure: bool = typer.Option(
            False,
            "--skip-configure",
            help="Install only; do not store integration.openwiki.llm_api_key.",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Write a JSON envelope to stdout instead of plain text.",
        ),
    ) -> None:
        """Install OpenWiki and optionally store the LLM API key."""
        code, install_detail = run_openwiki_install(skip_if_installed=not force_install)
        configure_ok = skip_configure
        configure_detail = "configure skipped"
        if code != 0:
            if json_out:
                import json

                typer.echo(
                    json.dumps(
                        {
                            "ok": False,
                            "command": "sevn openwiki setup",
                            "install": {"ok": False, "detail": install_detail},
                        }
                    )
                )
            else:
                typer.secho(install_detail, err=True)
            raise typer.Exit(code if code > 0 else 1)

        if not skip_configure:
            if not stdin and sys.stdin.isatty():
                stdin = True
            if stdin:
                if not json_out:
                    typer.echo(
                        "Paste the LLM API key for your OpenWiki provider "
                        f"(stored as {OPENWIKI_LLM_API_KEY_SECRET})."
                    )
                    typer.echo(
                        "Match ``skills.openwiki.provider`` in sevn.json "
                        "(openrouter, openai, anthropic, fireworks, baseten)."
                    )
                    typer.echo(
                        "You can skip this when an assigned provider secret already covers OpenWiki."
                    )
                    typer.echo("")
                try:
                    execute_secrets_put(
                        alias=OPENWIKI_LLM_API_KEY_SECRET,
                        command="sevn openwiki setup",
                        value=None,
                        stdin=True,
                        confirm_fingerprint=None,
                        json_out=False,
                        stdin_prompt="OpenWiki LLM API key: ",
                    )
                except typer.Exit as exc:
                    if exc.exit_code == 0:
                        configure_ok = True
                        configure_detail = f"stored {OPENWIKI_LLM_API_KEY_SECRET}"
                    else:
                        configure_ok = False
                        configure_detail = "configure failed or cancelled"
                        if json_out:
                            import json

                            typer.echo(
                                json.dumps(
                                    {
                                        "ok": False,
                                        "command": "sevn openwiki setup",
                                        "install": {"ok": True, "detail": install_detail},
                                        "configure": {
                                            "ok": False,
                                            "detail": configure_detail,
                                            "exit_code": exc.exit_code,
                                        },
                                    }
                                )
                            )
                        else:
                            typer.secho(configure_detail, err=True)
                        raise
            else:
                configure_detail = (
                    "no API key provided — run `sevn openwiki configure --stdin` "
                    "or rely on assigned provider secrets"
                )
                configure_ok = True
        payload = {
            "ok": configure_ok or skip_configure,
            "command": "sevn openwiki setup",
            "install": {"ok": True, "detail": install_detail},
            "configure": {"ok": configure_ok, "detail": configure_detail},
            "next_step": "Enable skills.openwiki.enabled in sevn.json or Telegram /config",
        }
        if json_out:
            import json

            typer.echo(json.dumps(payload))
        else:
            typer.echo(install_detail)
            typer.echo(configure_detail)
            typer.echo(payload["next_step"])
