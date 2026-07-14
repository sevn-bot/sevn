"""Changelog validator shim — canonical implementation in ``skw.changelog_validate``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SKW_SRC = _ROOT / "spec-kit-wave" / "src"
if str(_SKW_SRC) not in sys.path:
    sys.path.insert(0, str(_SKW_SRC))

from skw.changelog_validate import (  # noqa: E402
    check_staged_gate,
    load_changelog_rules,
    main,
    validate_changelog,
)

__all__ = [
    "check_staged_gate",
    "load_changelog_rules",
    "main",
    "validate_changelog",
]

if __name__ == "__main__":
    raise SystemExit(main())
