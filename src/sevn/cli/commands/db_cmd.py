"""``sevn db`` — backup and restore workspace ``sevn.db`` (#147).

Module: sevn.cli.commands.db_cmd
Depends: typer, sevn.storage.backup, sevn.cli.workspace

Exports:
    register — attach ``db backup`` and ``db restore`` commands.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from sevn.config.loader import find_sevn_json
from sevn.config.workspace_config import parse_workspace_config
from sevn.storage.backup import backup_sevn_db, restore_sevn_db
from sevn.storage.errors import StorageError
from sevn.storage.paths import sevn_db_path
from sevn.workspace.layout import WorkspaceLayout


def _resolve_db_path() -> Path:
    """Return ``sevn.db`` for the workspace bound to cwd ``sevn.json``.

    Returns:
        Path: Absolute path to ``.sevn/sevn.db``.

    Raises:
        typer.Exit: Exit code 2 when no workspace config is found.

    Examples:
        >>> import typer
        >>> try:
        ...     _resolve_db_path()
        ... except typer.Exit as exc:
        ...     exc.exit_code == 2
        ... else:
        ...     False
        True
    """
    sevn_json = find_sevn_json()
    if sevn_json is None:
        typer.echo("No sevn.json found; run from a workspace directory.", err=True)
        raise typer.Exit(2)
    cfg = parse_workspace_config(json.loads(sevn_json.read_text(encoding="utf-8")))
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    return sevn_db_path(layout.dot_sevn)


def register(app: typer.Typer) -> None:
    """Register ``db backup`` and ``db restore`` commands.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> import typer
        >>> register(typer.Typer())
    """
    db = typer.Typer(help="Workspace SQLite backup and restore.")
    app.add_typer(db, name="db")

    @db.command("backup")
    def db_backup(
        dest: Path = typer.Argument(..., help="Output backup file path."),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Write a consistent copy of ``.sevn/sevn.db`` to ``dest``."""
        source = _resolve_db_path()
        try:
            backup_sevn_db(source, dest)
        except StorageError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        payload = {"ok": True, "source": str(source), "dest": str(dest.resolve())}
        if json_out:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(f"backup written to {dest.resolve()}")

    @db.command("restore")
    def db_restore(
        backup: Path = typer.Argument(..., help="Backup file produced by ``db backup``."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Overwrite without prompt."),
        json_out: bool = typer.Option(False, "--json"),
    ) -> None:
        """Replace ``.sevn/sevn.db`` from a prior backup file."""
        dest = _resolve_db_path()
        if not yes and dest.is_file() and not typer.confirm(f"Overwrite {dest}?", default=False):
            raise typer.Abort()  # noqa: RSE102
        try:
            restore_sevn_db(backup, dest)
        except StorageError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(4) from exc
        payload = {"ok": True, "backup": str(backup.resolve()), "dest": str(dest)}
        if json_out:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(f"restored {dest} from {backup.resolve()}")
