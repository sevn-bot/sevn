"""Export ``TriageResult`` JSON Schema to ``infra/triage_result.schema.json``.

``specs/10-schema-ontology.md`` §11 — machine-readable JSON Schema export for
``TriageResult`` so OpenAPI / dashboard forms / external consumers can validate
Triager output without importing Python types.

Module: scripts.export_triage_schema
Depends: argparse, json, pathlib, sevn.agent.triager.models, sys

Exports:
    build_schema — produce the stable JSON Schema dict for ``TriageResult``.
    schema_path — canonical infra path for the exported schema.
    main — CLI entry; default verifies parity, ``--write`` refreshes.

Examples:
    >>> from scripts.export_triage_schema import build_schema
    >>> build_schema()["title"]
    'TriageResult'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sevn.agent.triager.models import TriageResult

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra"


def schema_path() -> Path:
    """Return the canonical infra path for the ``TriageResult`` schema.

    Returns:
        Path: ``infra/triage_result.schema.json``.

    Examples:
        >>> schema_path().name
        'triage_result.schema.json'
    """
    return INFRA / "triage_result.schema.json"


def build_schema() -> dict[str, Any]:
    """Produce the JSON Schema dict for ``TriageResult``.

    Returns:
        dict[str, Any]: Pydantic-emitted JSON Schema with sorted keys for
        deterministic byte output.

    Examples:
        >>> schema = build_schema()
        >>> schema["title"]
        'TriageResult'
        >>> "$defs" in schema
        True
    """
    return TriageResult.model_json_schema()


def _serialize(schema: dict[str, Any]) -> str:
    """Encode the schema as deterministic, newline-terminated JSON.

    Args:
        schema (dict[str, Any]): JSON Schema dict from ``build_schema``.

    Returns:
        str: Pretty-printed JSON with trailing newline for git-friendliness.

    Examples:
        >>> _serialize({"a": 1}).endswith("\\n")
        True
    """
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry: verify parity or refresh ``infra/triage_result.schema.json``.

    Args:
        argv (list[str] | None): Optional argv override for tests.

    Returns:
        int: ``0`` on success, ``1`` when the on-disk schema drifts from
        ``TriageResult.model_json_schema()`` and ``--write`` was not passed.

    Examples:
        >>> main([]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Overwrite infra/triage_result.schema.json with the current schema.",
    )
    args = parser.parse_args(argv)

    text = _serialize(build_schema())
    target = schema_path()
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target.relative_to(REPO_ROOT)}")
        return 0

    if not target.is_file():
        print(
            f"schema-export: missing {target.relative_to(REPO_ROOT)} — run `make schema-export`",
            file=sys.stderr,
        )
        return 1
    on_disk = target.read_text(encoding="utf-8")
    if on_disk != text:
        print(
            "schema-export: infra/triage_result.schema.json drifted from "
            "TriageResult.model_json_schema(); run `make schema-export`.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI smoke
    raise SystemExit(main())
