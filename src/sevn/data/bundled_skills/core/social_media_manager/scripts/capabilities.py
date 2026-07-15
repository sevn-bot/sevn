#!/usr/bin/env python3
"""Emit the social_media_manager per-platform capabilities matrix (D8).

Delegates to :func:`execute_social_media_manager_task` with ``medium=capabilities``
so script output matches the L2 worker matrix (six sites, allowed media, effective
medium, site-appropriate skills, readiness).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import dry_run_requested, run_social_media_task  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """CLI entry.

    Args:
        argv (list[str] | None): Optional argv override.

    Returns:
        int: Process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    return run_social_media_task({"medium": "capabilities"}, dry_run=dry_run_requested(args))


if __name__ == "__main__":
    raise SystemExit(main())
