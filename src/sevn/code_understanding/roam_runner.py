"""Subprocess runner for allowlisted ``roam`` CLI (`specs/28-code-understanding.md` §2.2).

Module: sevn.code_understanding.roam_runner
Depends: asyncio, pathlib, shutil, subprocess

Exports:
    build_roam_argv — construct argv for one allowlisted subcommand.
    run_roam_subprocess — execute ``roam`` when present on PATH.
    run_roam_query — sync helper returning ``(ok, text)`` for adapters and scripts.
    run_roam_query_async — async helper for native tool dispatch.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess  # nosec B404
from pathlib import Path  # noqa: TC003 — runtime cwd in subprocess helpers
from typing import Literal

RoamSubcommand = Literal["understand", "retrieve"]

ROAM_ALLOWED_SUBCOMMANDS: frozenset[RoamSubcommand] = frozenset({"understand", "retrieve"})

_MAX_OUTPUT_CHARS = 8192


def build_roam_argv(
    subcommand: RoamSubcommand,
    *,
    query: str | None = None,
) -> list[str]:
    """Build argv for one allowlisted ``roam`` subcommand.

    Args:
        subcommand (RoamSubcommand): Allowlisted subcommand name.
        query (str | None, optional): Natural-language task for ``retrieve``.

    Returns:
        list[str]: Process argv starting with ``roam``.

    Raises:
        ValueError: When ``subcommand`` is not allowlisted or ``retrieve`` lacks a query.

    Examples:
        >>> build_roam_argv("understand")
        ['roam', 'understand']
        >>> build_roam_argv("retrieve", query="where is auth?")
        ['roam', 'retrieve', 'where is auth?']
    """
    if subcommand not in ROAM_ALLOWED_SUBCOMMANDS:
        msg = f"roam_code: subcommand {subcommand!r} not allowlisted"
        raise ValueError(msg)
    argv: list[str] = ["roam", subcommand]
    if subcommand == "retrieve":
        task = (query or "").strip()
        if not task:
            msg = "roam_code: retrieve requires a non-empty query"
            raise ValueError(msg)
        argv.append(task)
    return argv


def _roam_not_found_message() -> str:
    """Return the standard error when ``roam`` is missing from PATH.

    Returns:
        str: Install hint for operators.

    Examples:
        >>> "roam" in _roam_not_found_message()
        True
    """
    return (
        "roam_code: `roam` not found on PATH "
        "(install with `uv tool install roam-code` or `pip install roam-code`)"
    )


def _run_roam_subprocess_sync(
    subcommand: RoamSubcommand,
    *,
    cwd: Path,
    query: str | None = None,
    timeout_seconds: float = 120.0,
) -> tuple[int, bytes, bytes]:
    """Run an allowlisted ``roam`` subcommand synchronously.

    Args:
        subcommand (RoamSubcommand): One of the allowlisted subcommands.
        cwd (Path): Repository root passed to the subprocess working directory.
        query (str | None, optional): Natural-language task for ``retrieve``.
        timeout_seconds (float, optional): Subprocess wall timeout.

    Returns:
        tuple[int, bytes, bytes]: ``(returncode, stdout, stderr)``.

    Raises:
        FileNotFoundError: When ``roam`` is not on ``PATH``.

    Examples:
        >>> _run_roam_subprocess_sync.__name__
        '_run_roam_subprocess_sync'
    """
    if shutil.which("roam") is None:
        raise FileNotFoundError(_roam_not_found_message())
    argv = build_roam_argv(subcommand, query=query)
    completed = subprocess.run(  # nosec B603 — argv from allowlisted build_roam_argv; no shell
        argv,
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode or 0, completed.stdout or b"", completed.stderr or b""


async def run_roam_subprocess(
    subcommand: RoamSubcommand,
    *,
    cwd: Path,
    query: str | None = None,
    timeout_seconds: float = 120.0,
) -> tuple[int, bytes, bytes]:
    """Run an allowlisted ``roam`` subcommand in ``cwd``.

    Args:
        subcommand (RoamSubcommand): One of the allowlisted subcommands.
        cwd (Path): Repository root passed to the subprocess working directory.
        query (str | None, optional): Natural-language task for ``retrieve``.
        timeout_seconds (float, optional): Subprocess wall timeout.

    Returns:
        tuple[int, bytes, bytes]: ``(returncode, stdout, stderr)``.

    Raises:
        FileNotFoundError: When ``roam`` is not on ``PATH``.

    Examples:
        >>> run_roam_subprocess.__name__
        'run_roam_subprocess'
    """
    return await asyncio.to_thread(
        _run_roam_subprocess_sync,
        subcommand,
        cwd=cwd,
        query=query,
        timeout_seconds=timeout_seconds,
    )


def _format_roam_result(
    subcommand: RoamSubcommand,
    code: int,
    stdout: bytes,
    stderr: bytes,
) -> tuple[bool, str]:
    """Normalise subprocess output into ``(ok, text)`` for roam adapters.

    Args:
        subcommand (RoamSubcommand): Subcommand that was executed.
        code (int): Process exit code.
        stdout (bytes): Captured stdout bytes.
        stderr (bytes): Captured stderr bytes.

    Returns:
        tuple[bool, str]: Success flag and ``roam_code:``-prefixed body or error.

    Examples:
        >>> _format_roam_result("understand", 0, b"brief", b"")
        (True, 'roam_code: brief')
    """
    if code != 0:
        detail = stderr.decode("utf-8", errors="replace") or f"roam {subcommand} exited {code}"
        return False, f"roam_code: {detail}"
    text = stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT_CHARS].strip()
    if not text:
        return False, f"roam_code: roam {subcommand} returned no output"
    body = text if text.startswith("roam_code:") else f"roam_code: {text}"
    return True, body


def _subcommand_for_query(query: str | None) -> RoamSubcommand:
    """Map an optional query string to an allowlisted roam subcommand.

    Args:
        query (str | None): Natural-language query when set.

    Returns:
        RoamSubcommand: ``retrieve`` when query is non-empty, else ``understand``.

    Examples:
        >>> _subcommand_for_query(None)
        'understand'
        >>> _subcommand_for_query("auth")
        'retrieve'
    """
    return "retrieve" if query and query.strip() else "understand"


def run_roam_query(root: Path, query: str | None) -> tuple[bool, str]:
    """Run ``roam understand`` or ``roam retrieve`` and normalise the response.

    Args:
        root (Path): Repository root for the subprocess working directory.
        query (str | None): Natural-language query; ``None`` selects ``understand``.

    Returns:
        tuple[bool, str]: ``(True, text)`` on success or ``(False, roam_code-prefixed error)``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ok, text = run_roam_query(Path(tempfile.mkdtemp()), "where?")
        >>> isinstance(ok, bool) and isinstance(text, str)
        True
    """
    subcommand = _subcommand_for_query(query)
    try:
        code, stdout, stderr = _run_roam_subprocess_sync(subcommand, cwd=root, query=query)
    except FileNotFoundError as exc:
        return False, str(exc)
    return _format_roam_result(subcommand, code, stdout, stderr)


async def run_roam_query_async(root: Path, query: str | None) -> tuple[bool, str]:
    """Async variant of :func:`run_roam_query` for native tool dispatch.

    Args:
        root (Path): Repository root for the subprocess working directory.
        query (str | None): Natural-language query; ``None`` selects ``understand``.

    Returns:
        tuple[bool, str]: ``(True, text)`` on success or ``(False, roam_code-prefixed error)``.

    Examples:
        >>> run_roam_query_async.__name__
        'run_roam_query_async'
    """
    subcommand = _subcommand_for_query(query)
    try:
        code, stdout, stderr = await run_roam_subprocess(subcommand, cwd=root, query=query)
    except FileNotFoundError as exc:
        return False, str(exc)
    return _format_roam_result(subcommand, code, stdout, stderr)


__all__ = [
    "ROAM_ALLOWED_SUBCOMMANDS",
    "build_roam_argv",
    "run_roam_query",
    "run_roam_query_async",
    "run_roam_subprocess",
]
