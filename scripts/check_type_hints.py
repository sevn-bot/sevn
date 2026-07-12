#!/usr/bin/env python3
"""Static visitor: ADR 17 type-hint rules for public callables.

Module: scripts.check_type_hints
Depends: ast, pathlib

Exports:
    Violation — One type-hint rule violation record.
    main — CLI entry; exits 1 on violations.

Examples:
    >>> _is_public_name("f")
    True
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple


class Violation(NamedTuple):
    """One type-hint rule violation."""

    path: Path
    lineno: int
    message: str


def _is_public_name(name: str) -> bool:
    """Return True if ADR treats this callable as public for type checks.

    Args:
        name (str): Function or method name.

    Returns:
        bool: True for ``__init__`` and names not starting with ``_``.

    Examples:
        >>> _is_public_name("__init__")
        True
        >>> _is_public_name("_private")
        False
    """
    if name == "__init__":
        return True
    return not name.startswith("_")


def _annotation_issues(node: ast.expr | None) -> list[str]:
    """Return issues for a return or parameter annotation expression.

    Args:
        node (ast.expr | None): Annotation AST node, or None if missing.

    Returns:
        list[str]: Human-readable problems (empty if ``node`` is None — handled by caller).

    Examples:
        >>> _annotation_issues(None)
        []
    """
    if node is None:
        return []
    problems: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in ("List", "Dict", "Set", "Tuple", "Union"):
            problems.append(
                f"use builtin generics or | syntax, not typing.{child.id} (found {child.id!r})"
            )
        if (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "typing"
            and child.attr in ("List", "Dict", "Set", "Tuple", "Union", "Optional")
        ):
            problems.append(f"avoid typing.{child.attr}; use PEP 585 / | syntax")
    return problems


def _check_function(
    path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    is_method: bool,
) -> list[Violation]:
    """Validate one function's annotations per ADR §Type Hints check script spec.

    Args:
        path (Path): Source file path (for diagnostics).
        node (ast.FunctionDef | ast.AsyncFunctionDef): Function to check.
        is_method (bool): True if nested in a class.

    Returns:
        list[Violation]: Collected violations.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "t.py"
        >>> _ = p.write_text(
        ...     "def f(a):\\n    return a\\n", encoding="utf-8"
        ... )
        >>> tree = ast.parse(p.read_text(encoding="utf-8"))
        >>> fn = tree.body[0]
        >>> assert isinstance(fn, ast.FunctionDef)
        >>> len(_check_function(p, fn, is_method=False)) >= 1
        True
    """
    if not _is_public_name(node.name):
        return []

    violations: list[Violation] = []
    if node.returns is None:
        violations.append(
            Violation(
                path,
                node.lineno,
                f"public function {node.name!r} needs a return type (use -> None if applicable)",
            )
        )
    else:
        for msg in _annotation_issues(node.returns):
            violations.append(
                Violation(path, node.lineno, f"{node.name}: return annotation — {msg}")
            )

    args = node.args
    to_check: list[ast.arg] = [*args.posonlyargs, *args.args]
    if args.vararg:
        to_check.append(args.vararg)
    to_check.extend(args.kwonlyargs)
    if args.kwarg:
        to_check.append(args.kwarg)
    if is_method and to_check and to_check[0].arg in ("self", "cls"):
        to_check = to_check[1:]

    for arg in to_check:
        if arg.annotation is None:
            violations.append(
                Violation(
                    path,
                    arg.lineno or node.lineno,
                    f"public function {node.name!r}: parameter {arg.arg!r} needs a type hint",
                )
            )
        else:
            for msg in _annotation_issues(arg.annotation):
                violations.append(
                    Violation(
                        path,
                        arg.lineno or node.lineno,
                        f"{node.name}({arg.arg}): {msg}",
                    )
                )

    return violations


def _check_file(path: Path) -> list[Violation]:
    """Collect type-hint violations for one Python file.

    Args:
        path (Path): Path to ``.py`` file.

    Returns:
        list[Violation]: All violations in that file.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> p = d / "ok.py"
        >>> _ = p.write_text(
        ...     "def f() -> None:\\n    pass\\n", encoding="utf-8"
        ... )
        >>> _check_file(p)
        []
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [Violation(path, exc.lineno or 0, f"syntax error: {exc}")]

    violations: list[Violation] = []

    def walk_class(class_node: ast.ClassDef) -> None:
        """Recursively walk class body for nested class/function definitions."""
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                violations.extend(_check_function(path, item, is_method=True))
            elif isinstance(item, ast.ClassDef):
                walk_class(item)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            violations.extend(_check_function(path, node, is_method=False))
        elif isinstance(node, ast.ClassDef):
            walk_class(node)

    return violations


def main(argv: list[str] | None = None) -> int:
    """Run checker on each directory or file argument.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: 0 if clean, 1 if any violations.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "t.py"
        >>> _ = p.write_text("def f() -> None: pass", encoding="utf-8")
        >>> main([str(p)])
        0
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        help="Files or directories to check (e.g. src/sevn)",
    )
    args = parser.parse_args(argv)

    py_files: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            py_files.extend(sorted(p.rglob("*.py")))
        elif p.suffix == ".py":
            py_files.append(p)

    all_violations: list[Violation] = []
    for path in py_files:
        if "__pycache__" in path.parts:
            continue
        rel = path.as_posix()
        if "bundled_skills/core/last30days/" in rel and not rel.endswith(
            "bundled_skills/core/last30days/scripts/research.py"
        ):
            continue
        all_violations.extend(_check_file(path))

    if not all_violations:
        return 0

    for v in all_violations:
        loc = f"{v.path}:{v.lineno}" if v.lineno else str(v.path)
        print(f"{loc}: {v.message}", file=sys.stderr)
    print(f"\n{len(all_violations)} type-hint violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
