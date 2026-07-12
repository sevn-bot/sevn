"""Mission Control sevn CLI console API (MC W1 §2c).

Module: sevn.ui.dashboard.api.cli_console
Depends: asyncio, json, re, shutil, sys, fastapi, pydantic, sevn.ui.dashboard.api.deps

Exports:
    CliRunBody — POST body schema.
    CliRunResponse — subprocess result schema.
    cli_run — execute ``sevn`` subcommand argv in workspace cwd (owner+csrf).
    cli_shortcuts — preset shortcut manifest for SPA.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sevn.ui.dashboard.api.deps import require_dashboard_csrf, require_dashboard_owner
from sevn.ui.dashboard.services.auth import DashboardClaims
from sevn.workspace.layout import WorkspaceLayout

router = APIRouter(prefix="/cli", tags=["dashboard-cli"])

_CLI_TIMEOUT_S = 120.0
_CONFIRM_TOKEN = "confirm"  # nosec B105

_DENYLIST: tuple[tuple[str, ...], ...] = (
    ("onboard", "--install-daemon"),
    ("secrets", "rm"),
    ("migrate", "apply"),
    ("ops", "snapshots", "restore"),
)

_SECRET_ECHO_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|bearer)\s*[:=]\s*\S+",
)

_SHORTCUTS_PATH = Path(__file__).resolve().parents[3] / "data" / "dashboard" / "cli_shortcuts.json"


class CliRunBody(BaseModel):
    """Body for ``POST /cli/run``."""

    argv: list[str] = Field(min_length=1)
    confirm_token: str | None = None


class CliRunResponse(BaseModel):
    """Subprocess result envelope."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


def _sevn_exec_argv(argv: list[str]) -> list[str]:
    """Build argv to invoke ``sevn`` via ``uv run`` or ``python -m``.

    Args:
        argv (list[str]): Subcommand arguments after ``sevn``.

    Returns:
        list[str]: Executable argv prefix + subcommand args.

    Examples:
        >>> _sevn_exec_argv(["doctor"])[-1]
        'doctor'
    """
    uv_bin = shutil.which("uv")
    if uv_bin:
        return [uv_bin, "run", "sevn", *argv]
    return [sys.executable, "-m", "sevn.cli.app", *argv]


def _argv_needs_confirm(argv: list[str]) -> bool:
    """Return whether ``argv`` matches a denylisted destructive subcommand.

    Args:
        argv (list[str]): Tokenized CLI arguments.

    Returns:
        bool: ``True`` when ``confirm_token`` is required.

    Examples:
        >>> _argv_needs_confirm(["doctor", "--json"])
        False
    """
    lowered = [part.lower() for part in argv]
    for pattern in _DENYLIST:
        if len(lowered) >= len(pattern) and lowered[: len(pattern)] == list(pattern):
            return True
    return False


def _redact_output(text: str) -> str:
    """Redact obvious secret patterns from CLI stdout/stderr echo.

    Args:
        text (str): Raw subprocess output.

    Returns:
        str: Redacted text safe for dashboard display.

    Examples:
        >>> _redact_output("token=abc")
        'token=<redacted>'
    """
    return _SECRET_ECHO_RE.sub(r"\1=<redacted>", text)


async def _run_sevn(
    layout: WorkspaceLayout,
    argv: list[str],
) -> CliRunResponse:
    """Execute ``sevn`` in ``layout.content_root`` with timeout.

    Args:
        layout (WorkspaceLayout): Workspace layout (cwd).
        argv (list[str]): Subcommand argv tail.

    Returns:
        CliRunResponse: Captured exit code and streams.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_sevn)
        True
    """
    cmd = _sevn_exec_argv(argv)
    started = time.perf_counter()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(layout.content_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=None,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=_CLI_TIMEOUT_S,
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    duration_ms = int((time.perf_counter() - started) * 1000)
    stdout = _redact_output(stdout_b.decode("utf-8", errors="replace"))
    stderr = _redact_output(stderr_b.decode("utf-8", errors="replace"))
    return CliRunResponse(
        exit_code=int(proc.returncode or 0),
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )


@router.get("/shortcuts")
async def cli_shortcuts(
    _claims: DashboardClaims = Depends(require_dashboard_owner),
) -> dict[str, Any]:
    """Return preset CLI shortcut buttons for the SPA.

    Args:
        _claims (DashboardClaims): Verified dashboard owner.

    Returns:
        dict[str, Any]: Shortcut manifest JSON.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cli_shortcuts)
        True
    """
    if _SHORTCUTS_PATH.is_file():
        loaded = json.loads(_SHORTCUTS_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    return {
        "shortcuts": [
            {"label": "Doctor (JSON)", "argv": ["doctor", "--json"]},
            {"label": "Config validate", "argv": ["config", "validate"]},
            {"label": "Gateway status", "argv": ["gateway", "status"]},
        ],
    }


@router.post("/run", response_model=CliRunResponse)
async def cli_run(
    request: Request,
    body: CliRunBody,
    _claims: DashboardClaims = Depends(require_dashboard_owner),
    _csrf: None = Depends(require_dashboard_csrf),
) -> CliRunResponse:
    """Run ``sevn`` with argv list in workspace cwd (owner+csrf).

    Args:
        request (Request): FastAPI request with layout.
        body (CliRunBody): argv list and optional confirm token.
        _claims (DashboardClaims): Verified dashboard owner.
        _csrf (None): CSRF guard.

    Returns:
        CliRunResponse: Exit code and captured output.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cli_run)
        True
    """
    argv = [str(part).strip() for part in body.argv if str(part).strip()]
    if not argv:
        raise HTTPException(status_code=422, detail="argv required")
    if any("\x00" in part for part in argv):
        raise HTTPException(status_code=422, detail="invalid argv")
    if _argv_needs_confirm(argv) and (body.confirm_token or "").strip() != _CONFIRM_TOKEN:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "CONFIRM_REQUIRED",
                "message": "destructive subcommand requires confirm_token",
            },
        )
    layout: WorkspaceLayout = request.app.state.layout
    try:
        return await _run_sevn(layout, argv)
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail="command timed out") from exc


__all__ = ["cli_run", "cli_shortcuts", "router"]
