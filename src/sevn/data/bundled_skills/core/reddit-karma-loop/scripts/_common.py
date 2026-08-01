"""Shared helpers for ``reddit-karma-loop`` bundled skill scripts.

Module: sevn.data.bundled_skills.core.reddit-karma-loop.scripts._common
Depends: os, sys, pathlib, sevn.lcm.script_cli

Exports:
    dry_run_requested — CLI/env dry-run selector.
    skill_root — bundled skill directory path.
    load_template — read ``templates/*.md`` relative to skill root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sevn.lcm.script_cli import workspace_from_env

_DRY_RUN_ENV = "SEVN_REDDIT_KARMA_DRY_RUN"
_SKILL_ROOT = Path(__file__).resolve().parents[1]


def skill_root() -> Path:
    """Return the bundled skill root directory."""
    return _SKILL_ROOT


def dry_run_requested(argv: list[str] | None = None) -> bool:
    """Return whether dry-run was requested via ``--dry-run`` or env."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in args or "-n" in args:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def load_template(name: str = "comment_draft") -> str:
    """Load ``templates/<name>.md`` from the skill root."""
    path = _SKILL_ROOT / "templates" / f"{name}.md"
    if not path.is_file():
        msg = f"missing template: {path}"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def workspace_path() -> Path:
    """Resolve workspace from env (``SEVN_WORKSPACE`` / cwd)."""
    return workspace_from_env()


__all__ = ["dry_run_requested", "load_template", "skill_root", "workspace_path"]
