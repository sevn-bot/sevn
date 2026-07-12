"""``sevn unboard`` remove-operator install (`specs/23-cli.md` §2.5.1).

Module: sevn.cli.commands.unboard
Depends: os, shutil, sys, pathlib, typer, sevn.cli.errors, sevn.cli.operator_lock,
    sevn.cli.repo_sync, sevn.cli.service_manager, sevn.cli.workspace

Exports:
    register — attach ``unboard``, ``uninstall``, and ``remove`` commands.
    run_unboard — shared teardown handler for tests and alias delegation.
    discover_operator_home_paths — list installed ``~/.sevn*`` home paths.
    resolve_operator_home — resolve ``--home`` or default operator install path.
    resolve_source_root — locate checkout for ``--with-source``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.gateway_teardown import stop_all_gateway_instances
from sevn.cli.install_discovery import discover_operator_homes
from sevn.cli.operator_lock import OperatorLockHeld, operator_lock
from sevn.cli.repo_sync import resolve_sevn_repo_root
from sevn.cli.service_manager import ServiceManagerError
from sevn.cli.workspace import sevn_home_dir

_ALIAS_NOTICE = "use sevn unboard"
_INSTALL_NOT_FOUND = "no operator install found"


def discover_operator_home_paths() -> list[Path]:
    """Return installed operator home paths (compat wrapper for tests).

    Returns:
        list[Path]: Sorted absolute operator home paths.

    Examples:
        >>> isinstance(discover_operator_home_paths(), list)
        True
    """
    return [row.home for row in discover_operator_homes()]


def _operator_home_has_config(home: Path) -> bool:
    """Return True when ``home`` contains a bound ``workspace/sevn.json``.

    Args:
        home (Path): Candidate operator home.

    Returns:
        bool: Whether the install marker file exists.

    Examples:
        >>> _operator_home_has_config(Path("/nonexistent"))
        False
    """
    return (home / "workspace" / "sevn.json").is_file()


def resolve_operator_home(*, home: Path | None) -> Path:
    """Resolve the operator home targeted by ``sevn unboard``.

    Args:
        home (Path | None): Explicit ``--home`` value or None for default discovery.

    Returns:
        Path: Absolute operator home to remove.

    Raises:
        CliPreconditionError: When no install can be resolved (exit ``4``).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> op = Path(tempfile.mkdtemp())
        >>> _ = (op / "workspace").mkdir()
        >>> _ = (op / "workspace" / "sevn.json").write_text("{}", encoding="utf-8")
        >>> resolve_operator_home(home=op) == op.resolve()
        True
    """
    if home is not None:
        target = home.expanduser().resolve()
        if not _operator_home_has_config(target):
            msg = (
                f"operator home has no workspace/sevn.json: {target} "
                "(pass --home to an installed operator home)"
            )
            raise CliPreconditionError(msg, exit_code=4)
        return target

    default = sevn_home_dir()
    if _operator_home_has_config(default):
        return default

    candidates = discover_operator_homes()
    if len(candidates) == 1:
        return candidates[0].home
    if len(candidates) > 1 and sys.stdin.isatty() and sys.stdout.isatty():
        typer.echo("Multiple operator homes found:")
        for idx, candidate in enumerate(candidates, start=1):
            typer.echo(f"  {idx}. {candidate.home}")
        choice = int(typer.prompt("Select home to remove", type=int))
        if 1 <= choice <= len(candidates):
            return candidates[choice - 1].home
        raise CliPreconditionError("invalid selection", exit_code=2)

    msg = (
        "no operator install found "
        "(set SEVN_HOME or pass --home to a directory with workspace/sevn.json)"
    )
    raise CliPreconditionError(msg, exit_code=4)


def resolve_source_root() -> Path | None:
    """Locate the sevn source checkout for ``--with-source``.

    Resolution order: ``SEVN_SOURCE_ROOT`` when set and existing; else editable
    install heuristic via :func:`resolve_sevn_repo_root`.

    Returns:
        Path | None: Checkout root, or None when ambiguous.

    Raises:
        CliPreconditionError: When ``SEVN_SOURCE_ROOT`` is set but not a directory.

    Examples:
        >>> resolve_source_root() is None or isinstance(resolve_source_root(), Path)
        True
    """
    env = os.environ.get("SEVN_SOURCE_ROOT", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if not root.is_dir():
            msg = f"SEVN_SOURCE_ROOT is not a directory: {root}"
            raise CliPreconditionError(msg, exit_code=4)
        return root
    try:
        return resolve_sevn_repo_root()
    except Exception:
        return None


def run_unboard(
    *,
    yes: bool = False,
    with_source: bool = False,
    home: Path | None = None,
    dry_run: bool = False,
) -> None:
    """Remove operator install: stop units, delete unit files, remove home tree.

    Args:
        yes (bool): Skip interactive confirmations.
        with_source (bool): Also delete the resolved source checkout.
        home (Path | None): Explicit operator home; default from env or discovery.
        dry_run (bool): Print planned actions without writes.

    Raises:
        typer.Exit: Mapped CLI exit codes on failure.

    Examples:
        >>> import contextlib
        >>> import io
        >>> import tempfile
        >>> from pathlib import Path
        >>> from typer import Exit
        >>> from unittest.mock import patch
        >>> op = Path(tempfile.mkdtemp())
        >>> _ = (op / "workspace").mkdir()
        >>> _ = (op / "workspace" / "sevn.json").write_text("{}", encoding="utf-8")
        >>> code = 0
        >>> buf = io.StringIO()
        >>> with contextlib.redirect_stdout(buf), patch(
        ...     "sevn.cli.commands.unboard.stop_all_gateway_instances"
        ... ):
        ...     try:
        ...         run_unboard(yes=True, home=op, dry_run=True)
        ...     except Exit as exc:
        ...         code = exc.exit_code
        >>> code
        0
    """
    resolve_exc: CliPreconditionError | None = None
    try:
        operator_home = resolve_operator_home(home=home)
    except CliPreconditionError as exc:
        resolve_exc = exc
        operator_home = home.expanduser().resolve() if home is not None else sevn_home_dir()

    gateway_only = resolve_exc is not None
    install_not_found = gateway_only and _INSTALL_NOT_FOUND in str(resolve_exc)

    source_root: Path | None = None
    if with_source:
        try:
            source_root = resolve_source_root()
        except CliPreconditionError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(getattr(exc, "exit_code", 4)) from exc
        if source_root is None:
            msg = (
                "cannot resolve source checkout for --with-source "
                "(set SEVN_SOURCE_ROOT to the checkout directory)"
            )
            typer.secho(msg, err=True)
            raise typer.Exit(4)

    if not yes and not dry_run:
        if gateway_only:
            typer.echo("No operator install found; will stop gateway and proxy services.")
        else:
            typer.echo(f"This will remove operator home: {operator_home}")
        if with_source and source_root is not None:
            typer.echo(f"and source checkout: {source_root}")
        if not typer.confirm("Continue?", default=False):
            raise typer.Exit(0)
        if (
            with_source
            and source_root is not None
            and not typer.confirm(f"Delete source checkout {source_root}?", default=False)
        ):
            raise typer.Exit(0)

    if dry_run:
        typer.echo("dry-run: stop gateway + proxy (units, launchd labels, orphan uvicorn)")
        stop_all_gateway_instances(operator_home=operator_home, dry_run=True)
        if gateway_only:
            typer.echo("dry-run: no operator home to remove")
        else:
            typer.echo(f"dry-run: delete operator home tree {operator_home}")
        if with_source and source_root is not None:
            typer.echo(f"dry-run: delete source checkout {source_root}")
        if resolve_exc is not None:
            typer.secho(str(resolve_exc), err=True)
            raise typer.Exit(0 if install_not_found else resolve_exc.exit_code)
        raise typer.Exit(0)

    from sevn.ui.terminal_theme import style_success

    try:
        stop_all_gateway_instances(operator_home=operator_home, dry_run=False)
    except ServiceManagerError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc

    if gateway_only:
        typer.echo(style_success("stopped gateway and proxy services"))
        if resolve_exc is not None:
            typer.secho(str(resolve_exc), err=True)
        raise typer.Exit(0 if install_not_found else getattr(resolve_exc, "exit_code", 4))

    try:
        with operator_lock(operator_home):
            if operator_home.is_dir():
                shutil.rmtree(operator_home)
            if with_source and source_root is not None and source_root.is_dir():
                shutil.rmtree(source_root)
    except OperatorLockHeld as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc
    except OSError as exc:
        typer.secho(f"failed to remove files: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(style_success(f"removed operator home: {operator_home}"))
    if with_source and source_root is not None:
        typer.echo(f"removed source checkout: {source_root}")


def register(app: typer.Typer) -> None:
    """Attach ``unboard``, ``uninstall``, and ``remove`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("unboard")
    def unboard_cmd(
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Skip interactive confirmations.",
        ),
        with_source: bool = typer.Option(
            False,
            "--with-source",
            help=(
                "Also delete the sevn source checkout (set SEVN_SOURCE_ROOT when "
                "auto-detection is ambiguous)."
            ),
        ),
        home: Path | None = typer.Option(
            None,
            "--home",
            help="Operator home to remove (default: SEVN_HOME or discovered ~/.sevn*).",
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Print planned teardown steps without executing them.",
        ),
    ) -> None:
        """Remove operator install: stop units, delete home tree, optional source checkout."""
        run_unboard(yes=yes, with_source=with_source, home=home, dry_run=dry_run)

    @app.command("uninstall")
    def uninstall_cmd(
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive confirmations."),
        with_source: bool = typer.Option(
            False,
            "--with-source",
            help="Also delete the sevn source checkout.",
        ),
        home: Path | None = typer.Option(None, "--home", help="Operator home to remove."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; no writes."),
    ) -> None:
        """Alias for ``sevn unboard`` (prints redirect notice)."""
        typer.secho(_ALIAS_NOTICE, err=True)
        run_unboard(yes=yes, with_source=with_source, home=home, dry_run=dry_run)

    @app.command("remove")
    def remove_cmd(
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive confirmations."),
        with_source: bool = typer.Option(
            False,
            "--with-source",
            help="Also delete the sevn source checkout.",
        ),
        home: Path | None = typer.Option(None, "--home", help="Operator home to remove."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; no writes."),
    ) -> None:
        """Alias for ``sevn unboard`` (prints redirect notice)."""
        typer.secho(_ALIAS_NOTICE, err=True)
        run_unboard(yes=yes, with_source=with_source, home=home, dry_run=dry_run)
