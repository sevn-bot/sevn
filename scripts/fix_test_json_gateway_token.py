#!/usr/bin/env python3
"""Inject ``gateway.token`` into test JSON literals that only have ``schema_version``.

Module: scripts.fix_test_json_gateway_token
Depends: pathlib, re, sys

Exports:
    main — CLI entry; rewrite Python sources in place.

Examples:
    >>> _patch('{"schema_version": 1, "foo": 1}').startswith("{")
    True
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TOKEN_KV = '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}'
# After "schema_version": N, insert gateway if block lacks "gateway"
_PAT = re.compile(
    r'(\{\s*"schema_version"\s*:\s*\d+\s*,)(?![^}]*"gateway")',
)


def _patch(text: str) -> str:
    """Insert gateway token JSON after ``schema_version`` when missing.

    Args:
        text (str): Python source containing JSON literals.

    Returns:
        str: Patched source text.

    Examples:
        >>> "gateway" in _patch('{"schema_version": 1, "x": 1}')
        True
    """
    return _PAT.sub(rf"\1 {_TOKEN_KV},", text)


def main(paths: list[str]) -> int:
    """Rewrite files under ``paths``; return process exit code.

    Args:
        paths (list[str]): Files or directories to scan.

    Returns:
        int: ``0`` on success.

    Examples:
        >>> main([])
        0
    """
    n = 0
    for raw in paths:
        path = Path(raw)
        if path.suffix != ".py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"schema_version"' not in text:
            continue
        new = _patch(text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            n += 1
            print(path)
    print(f"updated {n} files")
    return 0


if __name__ == "__main__":
    roots = sys.argv[1:] or ["tests"]
    files: list[str] = []
    for root in roots:
        p = Path(root)
        files.extend(str(f) for f in p.rglob("*.py")) if p.is_dir() else files.append(str(p))
    raise SystemExit(main(files))
