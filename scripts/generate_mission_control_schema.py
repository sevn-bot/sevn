#!/usr/bin/env python3
"""Generate or verify ``infra/mission-control.schema.json`` golden artifact.

Module: scripts.generate_mission_control_schema
Depends: argparse, json, subprocess, sys, scripts.mission_control_schema_lib

Exports:
    main — CLI entry.

Examples:
    >>> from pathlib import Path
    >>> from scripts.mission_control_schema_lib import GOLDEN_PATH
    >>> isinstance(GOLDEN_PATH, Path)
    True
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.mission_control_schema_lib import (  # noqa: E402
    GOLDEN_PATH,
    META_SCHEMA_PATH,
    build_schema_document,
    normalize_schema_for_compare,
)

__all__ = ["main"]


def _validate_meta_schema(golden_path: Path) -> None:
    """Validate golden JSON against the meta JSON-Schema document.

    Args:
        golden_path (Path): Committed schema golden path.

    Returns:
        None: Raises ``SystemExit`` on validation failure.

    Examples:
        >>> _validate_meta_schema(GOLDEN_PATH)  # doctest: +SKIP
    """
    if not META_SCHEMA_PATH.is_file():
        msg = f"meta schema missing: {META_SCHEMA_PATH}"
        raise SystemExit(msg)
    cmd = [
        "uv",
        "run",
        "check-jsonschema",
        f"--schemafile={META_SCHEMA_PATH}",
        str(golden_path),
    ]
    result = subprocess.run(cmd, cwd=_REPO, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)


def main(argv: list[str] | None = None) -> int:
    """Build schema document; ``--write`` updates golden, default verifies sync.

    Args:
        argv (list[str] | None): CLI args (``--write`` to update golden).

    Returns:
        int: ``0`` on success; ``1`` when verify diff fails.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description="Mission Control dashboard schema generator")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write infra/mission-control.schema.json (regenerate golden)",
    )
    args = parser.parse_args(argv)

    doc = build_schema_document()
    if args.write:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"mission-control-schema-generate: wrote {GOLDEN_PATH.relative_to(_REPO)}",
            file=sys.stderr,
        )
        _validate_meta_schema(GOLDEN_PATH)
        return 0

    if not GOLDEN_PATH.is_file():
        print(
            f"mission-control-schema-generate: missing golden {GOLDEN_PATH.relative_to(_REPO)} "
            "(run with --write)",
            file=sys.stderr,
        )
        return 1

    committed = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if normalize_schema_for_compare(committed) != normalize_schema_for_compare(doc):
        print(
            "mission-control-schema-generate: golden is stale "
            "(run: make mission-control-schema-generate)",
            file=sys.stderr,
        )
        return 1

    _validate_meta_schema(GOLDEN_PATH)
    print(
        f"mission-control-schema-generate: golden in sync -> {GOLDEN_PATH.relative_to(_REPO)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
