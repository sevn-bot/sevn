"""Onboard daemon install gate (`specs/23-cli.md` §4.2 decision 6).

Module: sevn.cli.install_gate
Depends: os, pathlib, typer, sevn.cli.operator_lock, sevn.cli.service_manager, sevn.cli.workspace

Exports:
    should_install_daemon — reuse-aware install gate.
    parse_install_daemon_flag_from_env — read ``SEVN_ONBOARD_INSTALL_DAEMON``.
    parse_reuse_from_env — read ``SEVN_ONBOARD_REUSE``.
    install_daemon_plan — install paired units; return summary line.
    maybe_install_daemon_after_promote — post-promote hook for web/TUI.
    run_install_daemon — install paired gateway + proxy user units.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from sevn.cli.operator_lock import OperatorLockHeld, operator_lock
from sevn.cli.service_manager import (
    ServiceManagerError,
    both_units_installed_and_active,
    install_paired_units,
)
from sevn.cli.workspace import sevn_home_dir


def should_install_daemon(
    *,
    home: Path,
    reuse: bool,
    install_daemon_flag: bool,
) -> bool:
    """Return whether post-promote should install gateway + proxy user units.

    Args:
        home (Path): Operator home for unit presence/active probes (``Path.home()``).
        reuse (bool): When True, skip install if both units are healthy.
        install_daemon_flag (bool): CLI ``--install-daemon`` or env equivalent.

    Returns:
        bool: ``True`` when ``run_install_daemon`` should run.

    Examples:
        >>> should_install_daemon(
        ...     home=Path("/tmp/h"), reuse=False, install_daemon_flag=True
        ... )
        True
        >>> should_install_daemon(
        ...     home=Path("/tmp/h"), reuse=False, install_daemon_flag=False
        ... )
        False
    """
    if not install_daemon_flag:
        return False
    if not reuse:
        return True
    return not both_units_installed_and_active(home)


def parse_install_daemon_flag_from_env() -> bool:
    """Read ``SEVN_ONBOARD_INSTALL_DAEMON`` (default on).

    Returns:
        bool: ``False`` only when env is ``0`` (or empty after strip).

    Examples:
        >>> import os
        >>> from unittest.mock import patch
        >>> with patch.dict(os.environ, {"SEVN_ONBOARD_INSTALL_DAEMON": "1"}):
        ...     parse_install_daemon_flag_from_env()
        True
        >>> with patch.dict(os.environ, {"SEVN_ONBOARD_INSTALL_DAEMON": "0"}):
        ...     parse_install_daemon_flag_from_env()
        False
    """
    raw = os.environ.get("SEVN_ONBOARD_INSTALL_DAEMON", "1").strip()
    return raw not in ("0", "")


def parse_reuse_from_env() -> bool:
    """Read ``SEVN_ONBOARD_REUSE`` (default off until reuse gate sets it).

    Returns:
        bool: ``True`` when env is ``1`` or ``true`` (case-insensitive).

    Examples:
        >>> import os
        >>> from unittest.mock import patch
        >>> with patch.dict(os.environ, {}, clear=True):
        ...     parse_reuse_from_env()
        False
        >>> with patch.dict(os.environ, {"SEVN_ONBOARD_REUSE": "1"}):
        ...     parse_reuse_from_env()
        True
    """
    raw = os.environ.get("SEVN_ONBOARD_REUSE", "0").strip().lower()
    return raw in ("1", "true", "yes")


def install_daemon_plan(*, dry_run: bool = False) -> str:
    """Install paired units and return a human-readable summary line.

    Args:
        dry_run (bool, optional): Plan only. Defaults to False.

    Returns:
        str: Summary of installed unit paths.

    Raises:
        OperatorLockHeld: When another CLI process holds the operator lock.
        ServiceManagerError: When install fails on this platform.

    Examples:
        >>> import os, tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> home = Path(tempfile.mkdtemp())
        >>> with patch.dict(os.environ, {"SEVN_HOME": str(home)}):
        ...     line = install_daemon_plan(dry_run=True)
        >>> "service units" in line
        True
    """
    home = sevn_home_dir()
    with operator_lock(home):
        plan = install_paired_units(home=Path.home(), dry_run=dry_run)
    if (
        not os.environ.get("SEVN_DISABLE_DAEMON_INSTALL", "").strip()
        and home != Path.home().resolve()
        and not str(home).startswith(str(Path.home()))
    ):
        # Defence-in-depth: refuse to leave behind a plist whose body points at an
        # operator home outside the real ``Path.home()`` (catches the case where
        # tests mutate ``SEVN_HOME`` to a temp dir but the plist install path still
        # resolves to ``~/Library/LaunchAgents``). See ``conftest.py``.
        for path in (plan.gateway_unit_path, plan.proxy_unit_path):
            path.unlink(missing_ok=True)
        msg = (
            f"refused to install paired units: SEVN_HOME={home} is outside "
            f"{Path.home()} (set SEVN_DISABLE_DAEMON_INSTALL=1 for non-host installs)"
        )
        raise ServiceManagerError(msg)
    return f"service units ({plan.platform}): {plan.gateway_unit_path} + {plan.proxy_unit_path}"


def run_install_daemon(*, dry_run: bool = False) -> None:
    """Install paired gateway + proxy user units under the operator home.

    Args:
        dry_run (bool, optional): Plan only. Defaults to False.

    Raises:
        typer.Exit: Exit code 4 on lock or platform errors.

    Examples:
        >>> import os, tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> home = Path(tempfile.mkdtemp())
        >>> with patch.dict(os.environ, {"SEVN_HOME": str(home)}), patch(
        ...     "sevn.cli.install_gate.typer.echo"
        ... ):
        ...     run_install_daemon(dry_run=True) is None
        True
    """
    try:
        line = install_daemon_plan(dry_run=dry_run)
    except OperatorLockHeld as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc
    except ServiceManagerError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc
    typer.echo(line)


def maybe_install_daemon_after_promote(
    *,
    operator_home: Path | None = None,
    install_daemon_flag: bool | None = None,
    reuse: bool | None = None,
) -> str | None:
    """Install units after promote when the gate allows (web/TUI/CLI hook).

    Args:
        operator_home (Path | None, optional): Home for unit probes; defaults to
            ``Path.home()``.
        install_daemon_flag (bool | None, optional): Override env when set.
        reuse (bool | None, optional): Override ``SEVN_ONBOARD_REUSE`` when set.

    Returns:
        str | None: Install summary line, or ``None`` when skipped.

    Raises:
        OperatorLockHeld: When install runs but the operator lock is held.
        ServiceManagerError: When install runs but the platform install fails.

    Examples:
        >>> import os
        >>> from unittest.mock import patch
        >>> with patch.dict(os.environ, {"SEVN_ONBOARD_INSTALL_DAEMON": "0"}):
        ...     maybe_install_daemon_after_promote() is None
        True
    """
    home = operator_home if operator_home is not None else Path.home()
    flag = (
        install_daemon_flag
        if install_daemon_flag is not None
        else parse_install_daemon_flag_from_env()
    )
    reuse_flag = reuse if reuse is not None else parse_reuse_from_env()
    if not should_install_daemon(home=home, reuse=reuse_flag, install_daemon_flag=flag):
        return None
    return install_daemon_plan()


__all__ = [
    "install_daemon_plan",
    "maybe_install_daemon_after_promote",
    "parse_install_daemon_flag_from_env",
    "parse_reuse_from_env",
    "run_install_daemon",
    "should_install_daemon",
]
