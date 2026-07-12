"""Shared binary resolver and runner for Printing Press CLI wrappers.

Module: sevn.data.bundled_skills.core.printing-press-library.scripts._pp_cli
Depends: json, os, shutil, subprocess, sys

Exports:
    BINARY_MISSING_CODE — stable error code emitted when a CLI binary is absent.
    BINARIES — mapping of function slug to Go binary name.
    resolve_binary — locate a Printing Press CLI binary on PATH.
    run_pp_cli — invoke a Printing Press CLI with argv and return a result dict.

Examples:
    >>> BINARY_MISSING_CODE
    'BINARY_MISSING'
    >>> 'espn' in BINARIES
    True
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

BINARY_MISSING_CODE = "BINARY_MISSING"

BINARIES: dict[str, str] = {
    "espn": "espn-pp-cli",
    "flight_goat": "flight-goat-pp-cli",
    "movie_goat": "movie-goat-pp-cli",
    "recipe_goat": "recipe-goat-pp-cli",
}

_INSTALL_HINT = (
    "Run: make printing-press-starter-pack  "
    "(or: npx -y @mvanhorn/printing-press-library install starter-pack)"
)

_CLI_TIMEOUT_SECONDS = 120.0


def resolve_binary(slug: str) -> str | None:
    """Return the absolute path of the binary for *slug*, or ``None`` when absent.

    Args:
        slug (str): Function slug — one of ``espn``, ``flight_goat``, ``movie_goat``,
            ``recipe_goat``.

    Returns:
        str | None: Absolute path to the binary, or ``None`` when not found on PATH.

    Examples:
        >>> result = resolve_binary("espn")
        >>> result is None or isinstance(result, str)
        True
    """
    binary_name = BINARIES.get(slug)
    if not binary_name:
        return None
    return shutil.which(binary_name)


def run_pp_cli(
    slug: str, argv: list[str], *, timeout: float = _CLI_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """Invoke a Printing Press CLI binary and return a result envelope.

    Appends ``--agent`` (JSON mode) to *argv* when not already present.

    Args:
        slug (str): Function slug — ``espn``, ``flight_goat``, ``movie_goat``, or
            ``recipe_goat``.
        argv (list[str]): Arguments forwarded to the CLI after the binary name.
        timeout (float): Subprocess wall-clock timeout in seconds. Defaults to 120.

    Returns:
        dict[str, Any]: ``{"ok": True, "data": <parsed or raw stdout>}`` on success,
            or ``{"ok": False, "code": BINARY_MISSING_CODE, "error": <str>}`` when
            the binary is absent or the subprocess fails.

    Examples:
        >>> r = run_pp_cli.__doc__  # smoke — no subprocess
        >>> r is not None
        True
    """
    binary = resolve_binary(slug)
    if not binary:
        binary_name = BINARIES.get(slug, f"{slug}-pp-cli")
        return {
            "ok": False,
            "code": BINARY_MISSING_CODE,
            "error": (f"`{binary_name}` not found on PATH. {_INSTALL_HINT}"),
        }

    cmd = [binary, *argv]
    if "--agent" not in cmd:
        cmd.append("--agent")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "code": BINARY_MISSING_CODE,
            "error": f"`{binary}` disappeared from PATH. {_INSTALL_HINT}",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "code": "CLI_TIMEOUT",
            "error": f"{BINARIES.get(slug, slug)!r} timed out after {timeout}s.",
        }

    stdout = result.stdout.strip()
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return {
            "ok": False,
            "code": "CLI_ERROR",
            "error": stderr or stdout or f"exit {result.returncode}",
        }

    try:
        data: Any = json.loads(stdout)
    except json.JSONDecodeError:
        data = stdout

    return {"ok": True, "data": data}
