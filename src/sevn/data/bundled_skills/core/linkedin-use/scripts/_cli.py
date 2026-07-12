"""Shared helpers for bundled ``linkedin-use`` skill scripts."""

from __future__ import annotations

import os
from pathlib import Path

from sevn.lcm.script_cli import write_error


def content_root_from_env() -> Path:
    """Return workspace content root from ``SEVN_CONTENT_ROOT`` or ``SEVN_WORKSPACE``."""
    content_raw = os.environ.get("SEVN_CONTENT_ROOT", "").strip()
    if content_raw:
        return Path(content_raw).expanduser().resolve()
    workspace_raw = os.environ.get("SEVN_WORKSPACE", "").strip()
    if workspace_raw:
        return Path(workspace_raw).expanduser().resolve()
    write_error(code="VALIDATION_ERROR", error="SEVN_CONTENT_ROOT is not set")
    raise SystemExit(1)


def session_id_from_env() -> str:
    """Return gateway session id from ``SEVN_SESSION_ID`` (default ``default``)."""
    return os.environ.get("SEVN_SESSION_ID", "").strip() or "default"
