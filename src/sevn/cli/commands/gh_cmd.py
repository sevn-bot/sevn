"""``sevn gh`` — GitHub integration helpers for operators.

Module: sevn.cli.commands.gh_cmd
Depends: typer, sevn.cli.commands.secrets_cmd, sevn.cli.terminal_util, sevn.proxy.integration.github

Constants:
    GITHUB_TOKEN_CREATE_URL — GitHub PAT creation page.

Exports:
    register — attach ``gh`` command group to the root Typer app.
    echo_gh_intro — print GitHub setup guidance with a clickable link.
    echo_github_token_setup_guide — PAT creation steps before ``--stdin`` entry.
"""

from __future__ import annotations

import typer

from sevn.cli.commands.secrets_cmd import execute_secrets_put
from sevn.cli.terminal_util import terminal_hyperlink
from sevn.proxy.integration.github import GITHUB_TOKEN_SECRET

GITHUB_TOKEN_CREATE_URL: str = "https://github.com/settings/tokens/new"

_GH_GROUP_HELP: str = (
    "GitHub integration helpers for sevn.\n\n"
    "GitHub REST calls (issues sync, gh-issues/gh-pr skills) go through the egress "
    "proxy. Store a personal access token as ``integration.github.token`` so the proxy "
    "can authenticate.\n\n"
    "Create a token on GitHub (repo read access for issue sync; add ``repo`` for PR "
    "writes):\n"
    f"  {GITHUB_TOKEN_CREATE_URL}\n\n"
    "Store the token with ``sevn gh add-github-token`` (or "
    "``sevn secrets put integration.github.token``). Requires a running gateway and a "
    "resolvable gateway bearer (``sevn gateway set-gateway-token`` or "
    "``SEVN_GATEWAY_TOKEN``)."
)


def echo_github_token_setup_guide() -> None:
    """Print GitHub PAT creation steps and a clickable link.

    Examples:
        >>> echo_github_token_setup_guide()  # doctest: +SKIP
    """
    link = terminal_hyperlink(
        GITHUB_TOKEN_CREATE_URL, "Open GitHub — create a personal access token"
    )
    typer.echo("Create a GitHub personal access token, then paste it at the prompt below.")
    typer.echo("")
    typer.echo(f"  {link}")
    typer.echo(f"  {GITHUB_TOKEN_CREATE_URL}")
    typer.echo("")
    typer.echo("On GitHub, choose:")
    typer.echo('  • Token type: classic ("Generate new token (classic)") is simplest.')
    typer.echo("  • Note: e.g. sevn-bot")
    typer.echo("  • Expiration: your preference (90 days or no expiration).")
    typer.echo("  • Scopes:")
    typer.echo("      - ``repo`` (full) if you need PR create/merge via gh-pr skills")
    typer.echo("      - or ``public_repo`` / read-only repo access for issue sync only")
    typer.echo("  • Generate token, copy it once (GitHub will not show it again).")
    typer.echo("")


def echo_gh_intro() -> None:
    """Print GitHub token setup guidance with a clickable link when supported.

    Examples:
        >>> echo_gh_intro()  # doctest: +SKIP
    """
    echo_github_token_setup_guide()
    typer.echo(
        "Store it with: sevn gh add-github-token --stdin  "
        "(or --value <token>; equivalent to "
        f"sevn secrets put {GITHUB_TOKEN_SECRET})",
    )


def register(app: typer.Typer) -> None:
    """Attach ``gh`` commands to the root Typer app.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    gh = typer.Typer(
        help=_GH_GROUP_HELP,
        no_args_is_help=False,
    )
    app.add_typer(gh, name="gh")

    @gh.callback(invoke_without_command=True)
    def gh_root(ctx: typer.Context) -> None:
        """GitHub integration helpers for sevn."""
        if ctx.invoked_subcommand is None:
            echo_gh_intro()
            typer.echo("")
            typer.echo(ctx.get_help())
            raise typer.Exit(0)

    @gh.command("add-github-token")
    def add_github_token(
        value: str | None = typer.Option(
            None,
            "--value",
            help="GitHub personal access token plaintext (prefer --stdin for safety).",
        ),
        stdin: bool = typer.Option(
            False,
            "--stdin",
            help="Read token from stdin, or prompt securely when run in a terminal.",
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
        """Store ``integration.github.token`` for the egress proxy (gateway-delegated)."""
        if stdin:
            echo_github_token_setup_guide()

        if value is None and not stdin:
            typer.secho(
                "add-github-token: provide --value, --stdin, or pipe one line into stdin",
                err=True,
            )
            raise typer.Exit(4)

        execute_secrets_put(
            alias=GITHUB_TOKEN_SECRET,
            command="sevn gh add-github-token",
            value=value,
            stdin=stdin,
            confirm_fingerprint=confirm_fingerprint,
            json_out=json_out,
            stdin_prompt="GitHub token: ",
        )
