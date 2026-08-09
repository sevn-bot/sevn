"""Changelog validator shim — canonical implementation in ``skw.changelog_validate``.

The implementation lives in the operator's ``spec-kit-wave`` kit, which is gitignored
(``.gitignore`` ``/spec-kit-wave``) and never published. This shim resolves it by path
rather than by install, so it must tolerate the kit being absent: a clone of the public
repo, a fresh ``git worktree`` (gitignored trees are not copied), or CI without the kit.

Without the guard below, ``pre-commit install`` in a public clone turns every commit
touching ``src/`` or ``scripts/`` into a ``ModuleNotFoundError: No module named 'skw'``
traceback naming a directory the contributor cannot see. ``make changelog-check`` already
degrades the same way via ``[ -d spec-kit-wave/src ]``; this brings the pre-commit entry
point in line. The gate still runs, unchanged, wherever the kit is present.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SKW_SRC = _ROOT / "spec-kit-wave" / "src"
if str(_SKW_SRC) not in sys.path:
    sys.path.insert(0, str(_SKW_SRC))

try:
    from skw.changelog_validate import (
        check_staged_gate,
        load_changelog_rules,
        main,
        validate_changelog,
    )

    SKW_AVAILABLE = True
except ModuleNotFoundError:  # spec-kit-wave not present — degrade to a no-op
    SKW_AVAILABLE = False

    _SKIP_NOTE = (
        "changelog_validate: skipped (spec-kit-wave not present — the changelog "
        "gate is operator-local; see CONTRIBUTING for the changelog convention)"
    )

    def _unavailable(*_args: Any, **_kwargs: Any) -> Any:
        """Fail loudly when the API is called directly without the kit installed."""
        raise RuntimeError(
            "skw.changelog_validate is unavailable: spec-kit-wave is not present at "
            f"{_SKW_SRC}. Only the CLI entry point degrades to a no-op."
        )

    check_staged_gate = _unavailable
    load_changelog_rules = _unavailable
    validate_changelog = _unavailable

    def main(argv: list[str] | None = None) -> int:
        """No-op CLI entry (``argv`` kept for signature parity with the real one).

        Warns on stderr and exits 0 so the commit is not blocked.
        """
        del argv
        print(_SKIP_NOTE, file=sys.stderr)
        return 0


__all__ = [
    "SKW_AVAILABLE",
    "check_staged_gate",
    "load_changelog_rules",
    "main",
    "validate_changelog",
]

if __name__ == "__main__":
    raise SystemExit(main())
