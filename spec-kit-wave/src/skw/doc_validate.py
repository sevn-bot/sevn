"""Shared doc validation entry points for spec-kit-wave folder tooling.

Exports:
    validate_doc_file — dispatch validation to the per-kind validator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skw.prd_validate import load_prd_rules, validate_prd_file
from skw.spec_validate import validate_spec_file


def validate_doc_file(
    path: Path,
    kind: str,
    *,
    repo_root: Path,
    siblings: list[Path] | None = None,
    kit_root: Path | None = None,
) -> dict[str, Any]:
    """Validate one markdown doc file for ``kind`` (``spec`` or ``prd``)."""
    if kind == "spec":
        return validate_spec_file(
            path,
            repo_root=repo_root,
            siblings=siblings,
            kit_root=kit_root,
        )
    if kind == "prd":
        root = kit_root or Path(__file__).resolve().parent.parent.parent
        errors, warnings = validate_prd_file(path, root, rules=load_prd_rules(root))
        return {
            "path": str(path),
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
        }
    msg = f"unsupported kind: {kind!r} (expected 'spec' or 'prd')"
    raise ValueError(msg)
