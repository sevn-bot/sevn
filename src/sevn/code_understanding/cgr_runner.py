"""Subprocess runner for allowlisted ``cgr`` CLI (`specs/28-code-understanding.md` §2.2).

Exports:
    run_cgr_subprocess — execute ``cgr`` when present on PATH.
    read_export_file — read capped export bytes from disk.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path  # noqa: TC003 — runtime path checks in read_export_file

from sevn.code_understanding.cgr_adapter import build_cgr_argv, read_export_capped


async def run_cgr_subprocess(
    subcommand: str,
    *,
    extra: list[str] | None = None,
    timeout_seconds: float = 120.0,
) -> tuple[int, bytes, bytes]:
    """Run an allowlisted ``cgr`` subcommand.

    Args:
        subcommand (str): One of the allowlisted subcommands.
        extra (list[str] | None, optional): Extra argv tokens after subcommand.
        timeout_seconds (float, optional): Subprocess wall timeout.

    Returns:
        tuple[int, bytes, bytes]: ``(returncode, stdout, stderr)``.

    Raises:
        FileNotFoundError: When ``cgr`` is not on ``PATH``.

    Examples:
        >>> run_cgr_subprocess.__name__
        'run_cgr_subprocess'
    """
    if shutil.which("cgr") is None:
        msg = "code_graph_rag: `cgr` not found on PATH (install optional extra code-graph-rag)"
        raise FileNotFoundError(msg)
    argv = build_cgr_argv(subcommand, extra)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout or b"", stderr or b""


def read_export_file(path: Path, *, max_bytes: int) -> bytes:
    """Read export JSON from ``path`` with a byte cap.

    Args:
        path (Path): Export file on disk.
        max_bytes (int): Maximum bytes to return.

    Returns:
        bytes: Capped file contents.

    Examples:
        >>> read_export_file(Path("/dev/null"), max_bytes=10)
        b''
    """
    if not path.is_file():
        return b""
    data = path.read_bytes()
    return read_export_capped(data, max_bytes)


__all__ = ["read_export_file", "run_cgr_subprocess"]
