"""``sevn export-secrets`` argv façade (`specs/06-secrets.md`, `specs/22-onboarding.md`).

Decrypts a workspace secrets store and writes a portable ``.env`` bundle that also embeds
the full ``sevn.json`` document and bot name. The bundle feeds ``sevn onboard fast <file>``
to recreate a bot without the onboarding forms.

Module: sevn.cli.commands.export_secrets_cmd
Depends: asyncio, sys, pathlib, typer, sevn.onboarding.export_bundle

Exports:
    register — attach the ``export-secrets`` command to the root Typer app.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from sevn.onboarding.export_bundle import ExportBundleError, run_export_secrets


def register(app: typer.Typer) -> None:
    """Attach ``sevn export-secrets`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("export-secrets")
    def export_secrets(
        workspace_root: Path = typer.Argument(
            ...,
            help="Workspace dir, its sevn.json, or an operator home (with workspace/sevn.json).",
        ),
        to_file: Path = typer.Option(
            ...,
            "--to-file",
            help="Destination .env path (written 0600). Carries secrets + full sevn.json + bot name.",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Overwrite the destination file if it already exists.",
        ),
    ) -> None:
        """Export workspace secrets and config to a plaintext ``.env`` bundle.

        Prompts for the store passphrase on a TTY when neither the environment nor the
        login Keychain can unlock the encrypted store. Reuse the file with
        ``sevn onboard fast <file>`` to provision a similar bot quickly.
        """
        interactive = sys.stdin.isatty() and sys.stdout.isatty()

        def _prompt(var: str) -> str:
            if not interactive:
                return ""
            return str(typer.prompt(f"{var} (to unlock store)", hide_input=True))

        try:
            result = asyncio.run(
                run_export_secrets(
                    workspace_root=workspace_root,
                    to_file=to_file,
                    force=force,
                    passphrase_prompt=_prompt,
                )
            )
        except ExportBundleError as exc:
            typer.secho(exc.message, err=True)
            raise typer.Exit(exc.exit_code) from exc

        typer.echo(
            f"exported {result.secret_count} secret(s) for bot {result.bot_name!r} to {result.path}"
        )
        typer.secho(
            "this file contains plaintext secrets — keep it private",
            err=True,
        )
        if result.git_unignored_warning:
            typer.secho(
                f"warning: {result.path.name} is not gitignored — add it to .gitignore",
                err=True,
                fg=typer.colors.YELLOW,
            )
        raise typer.Exit(0)
