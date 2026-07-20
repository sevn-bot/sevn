"""Fail when the pullfrog-py pin drifts between the workflow and the Makefile.

The CI review action (``.github/workflows/pullfrog.yml``) pins
``alexhawat/pullfrog-py@<sha>``; the ``Makefile``'s ``PULLFROG_PY_REF`` default
must match it so local ``make review`` runs the same reviewed code as CI. Nothing
else enforces that invariant, so a one-sided bump would silently break it — this
gate makes such drift fail CI (wired into ``make ci-parity``).

Module: scripts.check_pullfrog_ref_parity
Depends: re, pathlib, sys

Exports:
    main — CLI entry; compares the two pinned refs and reports drift.

Examples:
    >>> from pathlib import Path
    >>> REPO_ROOT == Path(__file__).resolve().parents[1]
    True
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pullfrog.yml"
MAKEFILE = REPO_ROOT / "Makefile"

# `uses: alexhawat/pullfrog-py@<ref>` in the workflow.
_WORKFLOW_RE = re.compile(r"uses:\s*alexhawat/pullfrog-py@(?P<ref>[0-9a-fA-F]{7,40})\b")
# `PULLFROG_PY_REF ?= $(if $(SEVN_PULLFROG_PY_REF),$(SEVN_PULLFROG_PY_REF),<ref>)`
# in the Makefile — the default (third) argument is the pinned ref.
_MAKEFILE_RE = re.compile(
    r"PULLFROG_PY_REF\s*\?=\s*\$\(if\s*\$\(SEVN_PULLFROG_PY_REF\)\s*,\s*"
    r"\$\(SEVN_PULLFROG_PY_REF\)\s*,\s*(?P<ref>[^),\s]+)\s*\)"
)


def main() -> int:
    """Compare the workflow and Makefile pullfrog-py pins.

    Returns:
        int: ``0`` when the two refs match, ``1`` on drift or a missing pin.

    Examples:
        >>> main() in (0, 1)
        True
    """

    def extract(pattern: re.Pattern[str], path: Path, what: str) -> str | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"pullfrog-ref-check: cannot read {path}: {exc}", file=sys.stderr)
            return None
        match = pattern.search(text)
        if match is None:
            print(f"pullfrog-ref-check: no {what} pin found in {path}", file=sys.stderr)
            return None
        return match.group("ref")

    workflow_ref = extract(_WORKFLOW_RE, WORKFLOW, "workflow action")
    makefile_ref = extract(_MAKEFILE_RE, MAKEFILE, "PULLFROG_PY_REF default")
    if workflow_ref is None or makefile_ref is None:
        return 1
    if workflow_ref != makefile_ref:
        print(
            "pullfrog-ref-check: pullfrog-py pin drift —\n"
            f"  workflow (.github/workflows/pullfrog.yml): {workflow_ref}\n"
            f"  Makefile (PULLFROG_PY_REF default):        {makefile_ref}\n"
            "Bump both to the same SHA so local `make review` matches CI.",
            file=sys.stderr,
        )
        return 1
    print(f"pullfrog-ref-check: ok — both pinned to {workflow_ref}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
