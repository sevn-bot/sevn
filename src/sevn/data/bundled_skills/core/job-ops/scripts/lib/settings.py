"""Environment + logging helpers for ``job-ops`` skill scripts.

Module: job-ops/scripts/lib/settings.py

Scripts run as subprocesses launched by the sevn skill runner. ``loguru`` logs go
to **stderr** so ``stdout`` stays a single JSON envelope (the skill-runner contract).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

_CONFIGURED = False


def get_logger() -> logger.__class__:  # type: ignore[name-defined]
    """Return the shared loguru logger configured to write to stderr.

    Returns:
        The process ``loguru`` logger sink (stderr only).
    """
    global _CONFIGURED
    if not _CONFIGURED:
        logger.remove()
        level = os.environ.get("SEVN_JOB_OPS_LOG_LEVEL", "INFO").strip().upper() or "INFO"
        logger.add(sys.stderr, level=level, backtrace=False, diagnose=False)
        _CONFIGURED = True
    return logger


def content_root_from_env() -> Path:
    """Return the workspace content root from ``SEVN_CONTENT_ROOT``/``SEVN_WORKSPACE``.

    Returns:
        Path: Absolute content root directory.
    """
    content_raw = os.environ.get("SEVN_CONTENT_ROOT", "").strip()
    if content_raw:
        return Path(content_raw).expanduser().resolve()
    workspace_raw = os.environ.get("SEVN_WORKSPACE", "").strip()
    if workspace_raw:
        return Path(workspace_raw).expanduser().resolve()
    return Path.cwd().resolve()


def session_id_from_env() -> str:
    """Return the gateway session id from ``SEVN_SESSION_ID`` (default ``default``)."""
    return os.environ.get("SEVN_SESSION_ID", "").strip() or "default"


def data_dir(content_root: Path | None = None) -> Path:
    """Return the ``<content_root>/job-ops`` data directory, creating it if needed.

    Args:
        content_root (Path | None): Override content root; defaults to env resolution.

    Returns:
        Path: The job-ops workspace data directory.
    """
    root = content_root if content_root is not None else content_root_from_env()
    out = root / "job-ops"
    out.mkdir(parents=True, exist_ok=True)
    return out
