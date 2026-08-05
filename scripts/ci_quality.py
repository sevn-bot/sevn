"""Non-short-circuit runner for ``make ci-quality``.

Module: scripts.ci_quality
Depends: scripts.ci_lib

Exports:
    main — run every advisory quality target and return the first failure.

Examples:
    >>> from ci_lib import CI_QUALITY_TARGETS
    >>> "complexity-ratchet" in CI_QUALITY_TARGETS
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ci_lib import CI_QUALITY_TARGETS, run_make_targets


def main() -> int:
    """Run all ``ci-quality`` member targets without Makefile short-circuit.

    Returns:
        int: First non-zero exit code, or ``0`` when every member passes.

    Examples:
        >>> main() in (0, 1)
        True
    """
    return run_make_targets(list(CI_QUALITY_TARGETS), prefix="ci-quality")


if __name__ == "__main__":
    raise SystemExit(main())
