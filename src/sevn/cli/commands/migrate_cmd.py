"""``sevn migrate`` (`specs/23-cli.md` §2.4, `specs/22-onboarding.md` §2.3).

Module: sevn.cli.commands.migrate_cmd
Depends: sys, typer, sevn.onboarding.migrate, sevn.cli.workspace

Exports:
    register — attach ``migrate`` command.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from sevn.cli.workspace import bound_workspace_dir
from sevn.onboarding.migrate import (
    describe_schema_upgrade,
    import_foreign_workspace,
    upgrade_schema_inplace,
)


def register(app: typer.Typer) -> None:
    """Attach ``migrate`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("migrate")
    def migrate(
        path: Path | None = typer.Argument(None, help="Foreign workspace root to import."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; no writes."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Consent to in-place schema upgrade."),
    ) -> None:
        """In-place schema upgrade (no path) or import plan (with path)."""
        if path is None:
            root = bound_workspace_dir()
            sevn_json = root / "sevn.json"
            if not sevn_json.is_file():
                typer.secho(f"missing bound workspace config: {sevn_json}", err=True)
                raise typer.Exit(4)
            try:
                preview = describe_schema_upgrade(root)
            except Exception as exc:
                typer.secho(str(exc), err=True)
                raise typer.Exit(4) from exc
            if not preview["changed"]:
                typer.echo(json.dumps(preview, indent=2, sort_keys=True))
                raise typer.Exit(0)
            typer.echo(preview["diff"].rstrip() + "\n")
            if dry_run:
                summary = {
                    "changed": True,
                    "backup": None,
                    "diff": preview["diff"],
                    "detail": "dry-run only — no files written",
                }
                typer.echo(json.dumps(summary, indent=2, sort_keys=True))
                raise typer.Exit(0)

            consent = yes
            if not consent:
                if sys.stdin.isatty() and sys.stdout.isatty():
                    consent = typer.confirm("Apply schema upgrade?", default=False)
                else:
                    typer.secho(
                        "non-interactive session: pass --yes to apply the upgrade or use --dry-run to preview.",
                        err=True,
                    )
                    raise typer.Exit(2)
            if not consent:
                raise typer.Abort()  # noqa: RSE102
            try:
                summary = upgrade_schema_inplace(
                    root,
                    consent=True,
                    dry_run=False,
                )
            except Exception as exc:
                typer.secho(str(exc), err=True)
                raise typer.Exit(4) from exc
            typer.echo(json.dumps(summary, indent=2, sort_keys=True))
            raise typer.Exit(0)

        plan = import_foreign_workspace(path.resolve(), dry_run=dry_run)
        typer.echo(str(plan.to_json_dict()))
        raise typer.Exit(0)
