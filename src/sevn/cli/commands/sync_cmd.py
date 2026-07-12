"""``sevn sync`` — refresh a source checkout from origin (`specs/23-cli.md` §2.4.1).

Module: sevn.cli.commands.sync_cmd
Depends: pathlib, typer, sevn.cli.repo_sync

Exports:
    register — attach ``sync`` command.
"""

from __future__ import annotations

from pathlib import Path

import typer

from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root, sync_source_tree


def register(app: typer.Typer) -> None:
    """Attach ``sync`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("sync")
    def sync(
        latest: bool = typer.Option(
            False,
            "--latest",
            help=(
                "Match the remote branch tip and rerun CLI reinstall even when already up to date; "
                "reset hard when history diverged; play logo animation on interactive TTY."
            ),
        ),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: SEVN_REPO_ROOT or walk up from cwd).",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print planned git and make steps without changing the tree or services.",
        ),
        no_restart: bool = typer.Option(
            False,
            "--no-restart",
            help="Do not restart the gateway user unit after a successful sync.",
        ),
    ) -> None:
        """Update the sevn.bot source checkout and reinstall the CLI."""
        try:
            root = resolve_sevn_repo_root(repo)
            result = sync_source_tree(
                repo_root=root,
                latest=latest,
                dry_run=dry_run,
                restart_gateway=not no_restart,
            )
        except RepoSyncError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(exc.exit_code) from exc
        typer.echo(result.detail)
        raise typer.Exit(0)
