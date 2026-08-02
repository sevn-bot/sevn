"""Thin compatibility aliases for migrated operator ``x-use`` / ``social_browser`` scripts.

Module: sevn.integrations.social_media.legacy_compat
Depends: os, sys, pathlib, sevn.browser.chrome, sevn.data.bundled_skills paths

Exports:
    dry_run_requested — CLI/env dry-run selector (bundled script parity).
    resolve_browser_profile — alias for :func:`sevn.browser.chrome.resolve_profile_dir`.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Final

from sevn.browser.chrome import resolve_profile_dir
from sevn.browser.recipes.social import FACEBOOK_EGRESS_DOMAINS, X_EGRESS_DOMAINS

if TYPE_CHECKING:
    from pathlib import Path

X_USE_SKILL_ID: Final[str] = "x-use"
FACEBOOK_USE_SKILL_ID: Final[str] = "facebook-use"
SOCIAL_BROWSER_SKILL_IDS: Final[frozenset[str]] = frozenset(
    {X_USE_SKILL_ID, FACEBOOK_USE_SKILL_ID},
)

SKILL_EGRESS: Final[dict[str, tuple[str, ...]]] = {
    X_USE_SKILL_ID: X_EGRESS_DOMAINS,
    FACEBOOK_USE_SKILL_ID: FACEBOOK_EGRESS_DOMAINS,
}

_DRY_RUN_ENV = "SEVN_SOCIAL_BROWSER_DRY_RUN"

__all__ = [
    "FACEBOOK_USE_SKILL_ID",
    "SKILL_EGRESS",
    "SOCIAL_BROWSER_SKILL_IDS",
    "X_USE_SKILL_ID",
    "dry_run_requested",
    "resolve_browser_profile",
]


def dry_run_requested(argv: list[str] | None = None) -> bool:
    """Return whether dry-run was requested via CLI flag or env.

    Args:
        argv (list[str] | None): CLI argv (defaults to ``sys.argv[1:]``).

    Returns:
        bool: ``True`` when dry-run is active.

    Examples:
        >>> dry_run_requested(["--dry-run"])
        True
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--dry-run" in args or "-n" in args:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_browser_profile(
    content_root: Path,
    session_id: str = "default",
    *,
    cfg: object | None = None,
) -> Path:
    """Resolve persistent Chrome profile directory (legacy ``social_browser`` name).

    Args:
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        cfg (object | None): Optional workspace config.

    Returns:
        Path: Absolute profile directory path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> resolve_browser_profile(root).name
        'default'
    """
    return resolve_profile_dir(content_root, session_id, cfg=cfg)  # type: ignore[arg-type]
