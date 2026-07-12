"""Argv to run uvicorn from the installed ``sevn`` tool environment.

Module: sevn.cli.uvicorn_argv
Depends: shutil, sys, pathlib

Exports:
    uvicorn_program_argv — absolute-path argv for gateway/proxy daemons and handoff.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _resolve_uvicorn_executable() -> str | None:
    """Return the uvicorn binary in the *running* ``sevn`` environment, if present.

    Resolves a sibling of ``sys.executable`` (the interpreter running this ``sevn`` process)
    rather than the ambient ``PATH``. The gateway/proxy daemons must run the same code as the
    ``sevn`` CLI that installed them — not whatever virtualenv happens to be active on ``PATH``
    when the service unit is generated. (Previously this preferred ``shutil.which("uvicorn")``,
    which on a multi-checkout machine baked a stray dev-tree venv into the launchd/systemd unit.)
    Returns ``None`` to fall back to ``python -m uvicorn`` with the same interpreter.

    Returns:
        str | None: Executable path, or None to fall back to ``python -m uvicorn``.

    Examples:
        >>> isinstance(_resolve_uvicorn_executable(), (str, type(None)))
        True
    """
    sibling = Path(sys.executable).resolve().parent / "uvicorn"
    if sibling.is_file():
        return str(sibling)
    return None


def uvicorn_program_argv(
    *,
    module: str,
    host: str = "127.0.0.1",
    port: int,
    factory: bool = False,
) -> list[str]:
    """Build argv for gateway/proxy uvicorn without ``uv run`` from operator workspace.

    ``uv run uvicorn`` requires a project root (``pyproject.toml``). Daemon units and
    onboarding handoff run with ``WorkingDirectory`` under the operator workspace, so
    use the same uvicorn binary as the running ``sevn`` CLI instead.

    Args:
        module (str): Uvicorn target (e.g. ``sevn.gateway.http_server:create_app``).
        host (str): Bind host.
        port (int): Listen port.
        factory (bool): Pass ``--factory`` when ``module`` is a factory callable.

    Returns:
        list[str]: argv for ``subprocess.Popen`` or launchd ``ProgramArguments``.

    Examples:
        >>> argv = uvicorn_program_argv(
        ...     module="sevn.gateway.http_server:create_app",
        ...     port=3001,
        ...     factory=True,
        ... )
        >>> argv[-1]
        '3001'
        >>> "run" not in argv
        True
    """
    tail: list[str] = [module]
    if factory:
        tail.append("--factory")
    tail.extend(["--host", host, "--port", str(port)])
    exe = _resolve_uvicorn_executable()
    if exe:
        return [exe, *tail]
    return [sys.executable, "-m", "uvicorn", *tail]


__all__ = ["uvicorn_program_argv"]
