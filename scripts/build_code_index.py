#!/usr/bin/env python3
"""Regenerate (or audit) ``.index/code_index/INDEX.md`` from ``src/sevn/``.

Walks the source tree, collects per-module + per-public-symbol docstring heads
via :mod:`sevn.code_understanding.code_index`, and writes a deterministic
markdown index. CI gates can opt into:

  - ``--check`` — fail if the on-disk file would change.
  - ``--require-docstrings`` — fail when any module / public function / class /
    method is missing its docstring.
  - ``--check-orphans`` — fail when files or symbols listed in the on-disk
    index no longer exist in the source (rename / delete detection).

Module: scripts.build_code_index
Depends: argparse, pathlib, sys, sevn.code_understanding.code_index

Exports:
    main — CLI entry; returns a process exit code.

Examples:
    >>> import inspect
    >>> inspect.isfunction(main)
    True
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve the repo root from this script's location so the CLI works from any cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from sevn.code_understanding.code_index import (  # noqa: E402  (post sys.path)
    audit_docstring_coverage,
    collect_module_symbols,
    extract_listed_symbols,
    iter_python_files,
    render_code_index_markdown,
)

_DEFAULT_OUTPUT = _REPO_ROOT / ".index" / "code_index" / "INDEX.md"
_SRC_ROOT = _REPO_ROOT / "src" / "sevn"


def _check_stale(expected: str, output_path: Path) -> list[str]:
    """Return a list of human-readable lines when ``output_path`` is stale.

    Args:
        expected (str): Freshly rendered markdown body.
        output_path (Path): Destination ``INDEX.md``.

    Returns:
        list[str]: One ``stale: ...`` line when the file differs (or is
            missing); empty list otherwise.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_check_stale)
        True
    """
    if not output_path.is_file():
        return [f"stale: {output_path} is missing — run `make code-index`"]
    on_disk = output_path.read_text(encoding="utf-8")
    if on_disk == expected:
        return []
    return [
        f"stale: {output_path} is out of date — regenerate with `make code-index`",
    ]


def _check_docstrings() -> list[str]:
    """Return a list of human-readable lines naming docstring-coverage gaps.

    Mirrors :mod:`scripts.check_docstrings` by ignoring bundled skill subprocess
    scripts (``data/bundled_skills/``) — those carry the ``make
    skills-core-check`` contract instead of ADR-17 docstrings.

    Returns:
        list[str]: One line per gap, prefixed with ``missing docstring:``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_check_docstrings)
        True
    """
    out: list[str] = []
    for gap in audit_docstring_coverage(_SRC_ROOT):
        if "data/bundled_skills/" in gap.rel_path:
            continue
        out.append(f"missing docstring: {gap.kind} {gap.rel_path}:{gap.symbol}")
    return out


def _check_orphans(output_path: Path) -> list[str]:
    """Return human-readable lines for symbols / files in the index that are gone.

    Args:
        output_path (Path): Destination ``INDEX.md``.

    Returns:
        list[str]: One line per orphaned entry; empty when the index matches
            the current source tree.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_check_orphans)
        True
    """
    if not output_path.is_file():
        return []
    on_disk = output_path.read_text(encoding="utf-8")
    listed = extract_listed_symbols(on_disk)
    current_files: dict[str, set[str]] = {}
    for py_path in iter_python_files(_SRC_ROOT):
        rel = py_path.relative_to(_SRC_ROOT).as_posix()
        current_files[rel] = {sym.name for sym in collect_module_symbols(py_path)}
    out: list[str] = []
    for rel, symbols in sorted(listed.items()):
        if rel not in current_files:
            out.append(f"orphan: file `{rel}` listed in index but missing from source")
            continue
        for sym in sorted(symbols - current_files[rel]):
            out.append(f"orphan: `{rel}` → `{sym}` listed in index but missing from source")
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Generate or audit ``INDEX.md``.

    Args:
        argv (list[str] | None): Argv tail (``None`` means use ``sys.argv``).

    Returns:
        int: ``0`` on success, ``1`` on any failed check, ``2`` on usage error.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Destination markdown path (default: .index/code_index/INDEX.md).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Audit only; do not write. Fail if file would change.",
    )
    parser.add_argument(
        "--require-docstrings",
        action="store_true",
        help="Fail when any module / public function / class / method is missing its docstring.",
    )
    parser.add_argument(
        "--check-orphans",
        action="store_true",
        help="Fail when files or symbols listed in the index no longer exist in the source.",
    )
    args = parser.parse_args(argv)

    if not _SRC_ROOT.is_dir():
        print(f"error: {_SRC_ROOT} not found", file=sys.stderr)
        return 2

    rendered = render_code_index_markdown(_REPO_ROOT)
    failures: list[str] = []
    audit_only = args.check or args.require_docstrings or args.check_orphans
    if args.check:
        failures.extend(_check_stale(rendered, args.output))
    if args.require_docstrings:
        failures.extend(_check_docstrings())
    if args.check_orphans:
        failures.extend(_check_orphans(args.output))

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        print(f"{len(failures)} failure(s)", file=sys.stderr)
        return 1

    if not audit_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
