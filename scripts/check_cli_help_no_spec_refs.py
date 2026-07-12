#!/usr/bin/env python3
"""Reject spec citations in operator-visible CLI and static UI copy.

Module: scripts.check_cli_help_no_spec_refs
Depends: argparse, ast, pathlib, re, sys

Exports:
    Violation — One forbidden spec reference record.
    scan_ui_tree — Scan static UI assets for spec markers.
    scan_cli_tree — Scan CLI modules for spec markers.
    main — CLI entry.

Examples:
    >>> import re
    >>> bool(re.search(r"specs/\\d", "specs/23-cli.md"))
    True
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import re
import sys
from pathlib import Path
from typing import NamedTuple

SPEC_REF = re.compile(r"specs/\d", re.IGNORECASE)
SECTION_REF = re.compile(r"§\s*\d")


class Violation(NamedTuple):
    """One forbidden spec reference in a CLI string literal."""

    path: Path
    lineno: int
    snippet: str


def _has_spec_marker(text: str) -> bool:
    """Return True when ``text`` cites a spec file or section marker.

    Args:
        text (str): Candidate operator-facing string.

    Returns:
        bool: Whether the text violates the hygiene rule.

    Examples:
        >>> _has_spec_marker("see specs/23-cli.md")
        True
        >>> _has_spec_marker("exit code 4")
        False
    """
    return bool(SPEC_REF.search(text) or SECTION_REF.search(text))


def _is_docstring(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> bool:
    """Return True when ``node`` is a function/class/module docstring.

    Args:
        node (ast.Constant): String constant under inspection.
        parents (dict[ast.AST, ast.AST]): Parent pointers for the AST.

    Returns:
        bool: Whether the constant is documentation, not operator copy.

    Examples:
        >>> _is_docstring(ast.Constant(value="x"), {})
        False
    """
    parent = parents.get(node)
    if not isinstance(parent, (ast.Expr, ast.Assign)):
        return False
    grand = parents.get(parent)
    if isinstance(parent, ast.Expr) and isinstance(
        grand, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    ):
        body = grand.body
        return bool(body) and body[0] is parent
    if isinstance(parent, ast.Assign) and isinstance(grand, ast.Module):
        targets = parent.targets
        return bool(targets) and isinstance(targets[0], ast.Name) and targets[0].id == "__doc__"
    return False


def _is_typer_command(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when ``node`` is decorated with ``*.command(...)``.

    Typer turns the function's docstring into the subcommand's ``--help`` short
    text, so those docstrings are operator-facing copy that must obey the rule.

    Args:
        node (ast.FunctionDef | ast.AsyncFunctionDef): Function definition.

    Returns:
        bool: Whether this function backs a Typer command.

    Examples:
        >>> _is_typer_command(ast.parse("def f(): pass").body[0])
        False
    """
    for deco in node.decorator_list:
        call = deco if isinstance(deco, ast.Call) else None
        if call is None:
            continue
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr == "command":
            return True
    return False


def _iter_operator_strings(path: Path) -> list[tuple[int, str]]:
    """Yield non-docstring string constants from one CLI module.

    Also yields the first-line docstring of any function decorated with
    ``*.command(...)`` because Typer surfaces those as the subcommand's
    ``--help`` short text.

    Args:
        path (Path): Python file under ``src/sevn/cli``.

    Returns:
        list[tuple[int, str]]: ``(lineno, text)`` pairs to scan.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "m.py"
        >>> _ = p.write_text("x = 1\\n", encoding="utf-8")
        >>> _iter_operator_strings(p)[0][1]
        '1'
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_docstring(node, parents):
                continue
            out.append((node.lineno or 0, node.value))
        elif isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
            if parts:
                out.append((node.lineno or 0, "".join(parts)))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_typer_command(node):
            doc = ast.get_docstring(node)
            if doc:
                first_line = doc.splitlines()[0]
                out.append((node.lineno or 0, first_line))
    return out


def scan_ui_tree(root: Path) -> list[Violation]:
    """Scan wizard and dashboard static assets for spec markers.

    Args:
        root (Path): Repository root.

    Returns:
        list[Violation]: All violations found.

    Examples:
        >>> scan_ui_tree(Path(__file__).resolve().parents[1])
        []
    """
    ui_roots = (
        root / "src" / "sevn" / "onboarding" / "web_wizard",
        root / "src" / "sevn" / "ui" / "spa" / "dashboard",
    )
    violations: list[Violation] = []
    for ui_root in ui_roots:
        if not ui_root.is_dir():
            continue
        for path in sorted(ui_root.glob("*")):
            if path.suffix not in {".html", ".js"}:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if _has_spec_marker(line):
                    violations.append(
                        Violation(
                            path=path,
                            lineno=lineno,
                            snippet=line.strip()[:120],
                        )
                    )
    return violations


def scan_cli_tree(root: Path) -> list[Violation]:
    """Scan ``src/sevn/cli`` for spec markers in operator-facing literals.

    Args:
        root (Path): Repository root.

    Returns:
        list[Violation]: All violations found.

    Examples:
        >>> root = Path(__file__).resolve().parents[1]
        >>> isinstance(scan_cli_tree(root), list)
        True
    """
    cli_root = root / "src" / "sevn" / "cli"
    violations: list[Violation] = []
    for path in sorted(cli_root.rglob("*.py")):
        for lineno, text in _iter_operator_strings(path):
            if _has_spec_marker(text):
                snippet = text.replace("\n", " ")[:120]
                violations.append(Violation(path=path, lineno=lineno, snippet=snippet))
    return violations


def main(argv: list[str] | None = None) -> int:
    """Run the CLI string hygiene check.

    Args:
        argv (list[str] | None): Optional argv (defaults to ``sys.argv[1:]``).

    Returns:
        int: Exit code (0 pass, 1 fail).

    Examples:
        >>> main(["--root", "."]) in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing src/sevn/cli.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    violations = scan_cli_tree(root) + scan_ui_tree(root)
    if not violations:
        return 0
    for v in violations:
        rel = v.path
        with contextlib.suppress(ValueError):
            rel = v.path.relative_to(args.root.resolve())
        print(f"{rel}:{v.lineno}: operator string cites specs: {v.snippet!r}", file=sys.stderr)
    print(f"check_cli_help_no_spec_refs: {len(violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
