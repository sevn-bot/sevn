"""Fail when checked-in ``infra/`` metadata drifts from golden config fixtures.

``specs/25-cicd-full.md`` §10.4 — Phase 1 parity: JSON Schema + long-description
pairing + the same ``check-jsonschema`` contract as ``make config-schema``.

Module: scripts.check_infra_parity
Depends: json, pathlib, subprocess, sys

Exports:
    main — CLI entry; validates infra JSON and schema gate.

Examples:
    >>> from pathlib import Path
    >>> REPO_ROOT == Path(__file__).resolve().parents[1]
    True
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFRA = REPO_ROOT / "infra"
SCHEMA = INFRA / "sevn.schema.json"
LONG_DESC = INFRA / "sevn_config_long_description.json"
TEMPLATE = INFRA / "sevn.json.template"
FIXTURES = (
    REPO_ROOT / "tests" / "fixtures" / "config" / "schema_v1_min.json",
    REPO_ROOT / "tests" / "fixtures" / "config" / "schema_v2_min.json",
)


def main() -> int:
    """Validate infra JSON artefacts and re-run the config-schema gate.

    Returns:
        int: ``0`` on success, ``1`` on failure.

    Examples:
        >>> main() in (0, 1)
        True
    """
    for path in (SCHEMA, LONG_DESC, TEMPLATE):
        if not path.is_file():
            print(f"infra parity: missing {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1

    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        long_doc = json.loads(LONG_DESC.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"infra parity: invalid JSON — {exc}", file=sys.stderr)
        return 1

    meta = long_doc.get("_meta")
    if not isinstance(meta, dict):
        print(
            "infra parity: sevn_config_long_description.json missing _meta object", file=sys.stderr
        )
        return 1
    paired = meta.get("paired_schema")
    if paired != "infra/sevn.schema.json":
        print(
            f"infra parity: _meta.paired_schema must be 'infra/sevn.schema.json', got {paired!r}",
            file=sys.stderr,
        )
        return 1
    tpl = meta.get("paired_template")
    if tpl != "infra/sevn.json.template":
        print(
            f"infra parity: _meta.paired_template must be 'infra/sevn.json.template', got {tpl!r}",
            file=sys.stderr,
        )
        return 1

    if not isinstance(schema, dict):
        print("infra parity: sevn.schema.json root must be a JSON object", file=sys.stderr)
        return 1

    for golden in FIXTURES:
        if not golden.is_file():
            print(f"infra parity: missing golden {golden.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1

    cmd = [
        "uv",
        "run",
        "check-jsonschema",
        "--schemafile",
        str(SCHEMA),
        *[str(p) for p in FIXTURES],
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    if proc.returncode != 0:
        print(
            "infra parity: check-jsonschema failed (same gate as make config-schema)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
