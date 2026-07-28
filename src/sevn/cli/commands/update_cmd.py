"""``sevn update`` / ``sevn upgrade`` — operator upgrade helpers (`specs/23-cli.md` §2.4).

Module: sevn.cli.commands.update_cmd
Depends: json, sys, pathlib, typer, sevn.cli.repo_sync, sevn.onboarding.migrate

Exports:
    register — attach ``update`` and ``upgrade`` root commands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from sevn.cli.json_util import emit_json_success
from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root, sync_source_tree
from sevn.cli.workspace import load_bound_workspace
from sevn.onboarding.migrate import describe_schema_upgrade


def register(app: typer.Typer) -> None:
    """Attach ``sevn update`` and ``sevn upgrade`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("update")
    def update_cmd(
        branch: str | None = typer.Option(
            None,
            "--branch",
            help="Git branch to track (default: my_sevn.sync.branch or pre-0.0.1).",
        ),
        repo: Path | None = typer.Option(
            None,
            "--repo",
            help="sevn.bot checkout root (default: my_sevn.repo_path / SEVN_REPO_ROOT / cwd).",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print planned git and make steps without changing disk or services.",
        ),
        no_restart: bool = typer.Option(
            False,
            "--no-restart",
            help="Do not restart the gateway user unit after a successful update.",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Force-update the sevn.bot checkout and reinstall the CLI (discards local checkout edits)."""
        command = "sevn update"
        try:
            root = resolve_sevn_repo_root(repo)
            result = sync_source_tree(
                repo_root=root,
                latest=True,
                branch=branch,
                dry_run=dry_run,
                restart_gateway=not no_restart,
            )
        except RepoSyncError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(exc.exit_code) from exc
        data = {
            "updated": result.updated,
            "local_rev": result.local_rev,
            "remote_rev": result.remote_rev,
            "detail": result.detail,
            "repo_root": str(root),
        }
        if json_out:
            emit_json_success(command=command, data=data)
            return
        typer.echo(result.detail)

    @app.command("upgrade")
    def upgrade_cmd(
        json_out: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
    ) -> None:
        """Describe workspace schema upgrade posture for the bound ``sevn.json``."""
        command = "sevn upgrade"
        try:
            bound = load_bound_workspace()
        except Exception as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        plan = describe_schema_upgrade(bound.layout.content_root)
        data = {
            "schema_upgrade": plan,
            "hint": "Run `sevn migrate` to apply in-place schema upgrades when prompted.",
            "python_version": sys.version.split()[0],
        }
        if json_out:
            emit_json_success(command=command, data=data)
            return
        typer.echo(json.dumps(plan, indent=2, sort_keys=True))
        typer.echo("Run `sevn migrate` when an in-place schema upgrade is required.")


__all__ = ["register"]
