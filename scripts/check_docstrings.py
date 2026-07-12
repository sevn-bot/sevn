#!/usr/bin/env python3
"""Docstring structure checks for ADR 17 (Exports, Args, Returns, Examples).

Module: scripts.check_docstrings
Depends: argparse, ast, doctest, pathlib, re, sys

Checked roots (``make lint``): ``src/sevn/`` and ``scripts/`` — skips ``src/sevn/data/bundled_skills/`` (skill subprocess scripts; ``make skills-core-check``).

Exports:
    Violation — One docstring violation record.
    main — CLI entry.

Examples:
    >>> bool(_parse_export_names("Exports:\\n    X — y\\n") == {"X"})
    True
"""

from __future__ import annotations

import argparse
import ast
import doctest
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Violation(NamedTuple):
    """One docstring violation."""

    path: Path
    lineno: int
    message: str


EXPORT_ITEM = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:[—\-])\s+.+$")
TOP_BREAK = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\s*:\s*$",
)

_EXAMPLES_HEAD = re.compile(r"(?ms)^\s*Examples:\s*\n(.*)\Z")


def _examples_region(doc: str) -> str | None:
    """Return the docstring tail starting at ``Examples:`` (ADR layout: Examples last).

    Args:
        doc (str): Full callable docstring.

    Returns:
        str | None: Region beginning with ``Examples:\\n`` plus body, or ``None``.

    Examples:
        >>> _examples_region("Args:\\n    x (int):\\n\\nExamples:\\n    >>> 1\\n    1\\n")
        'Examples:\\n    >>> 1\\n    1\\n'
        >>> _examples_region("no examples") is None
        True
    """
    m = _EXAMPLES_HEAD.search(doc)
    if not m:
        return None
    return "Examples:\n" + m.group(1)


def _compile_doctest_source(src: str) -> str | None:
    """Return an error string when doctest example source is not valid Python.

    Args:
        src (str): ``doctest.Example.source`` (command block only).

    Returns:
        str | None: Human-readable syntax error, or ``None`` when compilable.

    Examples:
        >>> _compile_doctest_source("callable(int)") is None
        True
        >>> _compile_doctest_source("++++") is not None
        True
    """
    text = src.rstrip()
    if not text:
        return None
    suffix = text + "\n"
    try:
        compile(suffix, "<doctest>", "single")
        return None
    except SyntaxError:
        try:
            compile(suffix, "<doctest>", "exec")
            return None
        except SyntaxError as exc:
            return exc.msg


def _doctest_example_syntax_messages(doc: str) -> list[str]:
    """Validate Python syntax of each ``>>>`` command block under ``Examples:``.

    Semantic correctness (expected output matches runtime) is enforced separately by
    ``make doctest`` / ``pytest --doctest-modules`` (`plan/architecture/17-coding-standards.md`).

    Args:
        doc (str): Callable docstring.

    Returns:
        list[str]: Messages for each invalid chunk (empty when OK).

    Examples:
        >>> bool(_doctest_example_syntax_messages(
        ...     "Examples:\\n    >>> ++++\\n    1\\n"
        ... ))
        True
        >>> _doctest_example_syntax_messages(
        ...     "Examples:\\n    >>> True\\n    True\\n"
        ... )
        []
    """
    region = _examples_region(doc)
    if region is None or ">>>" not in region:
        return []
    parser = doctest.DocTestParser()
    try:
        parts = parser.parse(region)
    except ValueError as exc:
        return [f"doctest parse error in Examples: {exc}"]
    errors: list[str] = []
    for part in parts:
        if isinstance(part, doctest.Example):
            msg = _compile_doctest_source(part.source)
            if msg:
                preview = part.source.strip().splitlines()
                head = preview[0] if preview else ""
                errors.append(f"invalid doctest Examples: `{head}` — {msg}")
    return errors


_CALLABLE_ONLY_RE = re.compile(r"^callable\s*\([^)]*\)\s*$", re.DOTALL)


def _iter_doctest_examples(doc: str) -> list[doctest.Example]:
    """Return doctest examples under ``Examples:`` (ADR layout: ``Examples`` last).

    Args:
        doc (str): Callable or module docstring.

    Returns:
        list[doctest.Example]: Parsed examples (empty when absent or unparseable).

    Examples:
        >>> _iter_doctest_examples(
        ...     "Examples:\\n    >>> 1\\n    1\\n"
        ... )[0].source.strip()
        '1'
    """
    region = _examples_region(doc)
    if region is None:
        return []
    try:
        parts = doctest.DocTestParser().parse(region)
    except ValueError:
        return []
    return [p for p in parts if isinstance(p, doctest.Example)]


def _parse_doctest_examples(doc: str) -> tuple[list[doctest.Example], str | None]:
    """Parse ``Examples:`` doctest blocks; return examples or a parse error message.

    Args:
        doc (str): Callable or module docstring.

    Returns:
        tuple[list[doctest.Example], str | None]: Examples and optional error text.

    Examples:
        >>> ex, err = _parse_doctest_examples("Examples:\\n    >>> 1\\n    1\\n")
        >>> ex[0].source.strip()
        '1'
        >>> err is None
        True
    """
    region = _examples_region(doc)
    if region is None:
        return [], None
    try:
        parts = doctest.DocTestParser().parse(region)
    except ValueError as exc:
        return [], f"invalid doctest Examples: {exc}"
    return [p for p in parts if isinstance(p, doctest.Example)], None


def _is_property_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when ``node`` is a ``@property`` (or setter) method.

    Args:
        node (ast.FunctionDef | ast.AsyncFunctionDef): AST node.

    Returns:
        bool: Whether treated as a property accessor.

    Examples:
        >>> import ast as A
        >>> t = A.parse("class C:\\n    @property\\n    def x(self): return 1\\n").body[0]
        >>> m = t.body[0]
        >>> assert isinstance(m, A.FunctionDef)
        >>> _is_property_method(m)
        True
    """
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "property":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr in {"property", "setter", "getter"}:
            return True
        if isinstance(dec, ast.Call):
            fn = dec.func
            if isinstance(fn, ast.Name) and fn.id == "property":
                return True
    return False


def _enforce_direct_call_examples(path: Path) -> bool:
    """Return True for ``src/sevn/cli/**/*.py`` (stricter behavioral doctest rules).

    Args:
        path (Path): Source file being checked.

    Returns:
        bool: Whether to require a doctest calling ``{name}(...)``.

    Examples:
        >>> from pathlib import Path
        >>> _enforce_direct_call_examples(Path("src/sevn/cli/app.py"))
        True
        >>> _enforce_direct_call_examples(Path("src/sevn/config/loader.py"))
        False
    """
    parts = path.parts
    marker = ("src", "sevn", "cli")
    return any(parts[i : i + len(marker)] == marker for i in range(len(parts) - len(marker) + 1))


def _behavioral_example_messages(
    doc: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    owner_class_name: str | None,
    path: Path,
) -> list[str]:
    """Enforce behavioral doctests (no ``callable(...)``-only; real calls).

    Args:
        doc (str): Callable docstring.
        node (ast.FunctionDef | ast.AsyncFunctionDef): Callable being documented.
        owner_class_name (str | None): Enclosing class name for ``__init__`` checks.
        path (Path): Source file (scopes strict direct-call rules to ``sevn/cli``).

    Returns:
        list[str]: Human-readable violations (empty when OK).

    Examples:
        >>> import ast as A
        >>> fake = A.parse("def f(): pass\\n").body[0]
        >>> assert isinstance(fake, A.FunctionDef)
        >>> len(_behavioral_example_messages(
        ...     "Examples:\\n    >>> callable(y)\\n    True\\n",
        ...     fake,
        ...     owner_class_name=None,
        ...     path=Path("src/sevn/cli/x.py"),
        ... )) >= 1
        True
    """
    examples, parse_err = _parse_doctest_examples(doc)
    if parse_err:
        return [parse_err]
    if not examples:
        return []
    joined = "\n".join(ex.source for ex in examples)
    out: list[str] = []

    for ex in examples:
        src = ex.source.strip()
        if src and _CALLABLE_ONLY_RE.fullmatch(src):
            out.append(
                "Examples: do not use callable(...) alone — show a real call with arguments "
                "(plan/architecture/17-coding-standards.md §Docstrings)",
            )
            break

    if not _enforce_direct_call_examples(path):
        return out

    if _is_property_method(node):
        return out

    if node.name == "__init__":
        if owner_class_name and not re.search(
            rf"\b{re.escape(owner_class_name)}\s*\(",
            joined,
        ):
            out.append(
                f"Examples: doctest must show {owner_class_name!r}(...) construction "
                "(not callable(...) smoke)",
            )
        return out

    short_dunder = len(node.name) > 2 and node.name.startswith("__") and node.name.endswith("__")
    if short_dunder:
        return out

    if not re.search(rf"\b{re.escape(node.name)}\s*\(", joined):
        out.append(
            f"Examples: doctest must call {node.name!r}(...) with a concrete argument list "
            "(plan/architecture/17-coding-standards.md §Docstrings)",
        )
    return out


def _module_callable_only_violation(mod_doc: str) -> str | None:
    """Reject module-level ``Examples:`` that are only ``callable(...)``.

    Args:
        mod_doc (str): Module docstring text.

    Returns:
        str | None: Violation message or ``None``.

    Examples:
        >>> _module_callable_only_violation(
        ...     "M.\\n\\nExports:\\n    (none)\\n\\nExamples:\\n    >>> callable(f)\\n    True\\n"
        ... ) is not None
        True
    """
    if "Examples:" not in mod_doc or ">>>" not in mod_doc:
        return None
    examples, parse_err = _parse_doctest_examples(mod_doc)
    if parse_err:
        return parse_err
    for ex in examples:
        if ex.source.strip() and _CALLABLE_ONLY_RE.fullmatch(ex.source.strip()):
            return (
                "module Examples: do not use callable(...) alone — show a real import/call "
                "(plan/architecture/17-coding-standards.md §Docstrings)"
            )
    return None


def _parse_export_names(module_doc: str) -> set[str]:
    """Parse ``Exports:`` names (flat or under Classes/Functions headings).

    Args:
        module_doc (str): Module docstring text only.

    Returns:
        set[str]: Exported public symbols.

    Examples:
        >>> _parse_export_names("Exports:\\n    Foo — desc\\n")
        {'Foo'}
        >>> _parse_export_names("intro\\n\\nExports:\\n    (none)\\n")
        set()
        >>> _parse_export_names("Exports:\\n    A — one\\nPrivate:\\n    _b — two\\n") == {"A"}
        True
    """
    lines = module_doc.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("Exports:"))
    except StopIteration:
        return set()
    names: set[str] = set()
    for line in lines[start + 1 :]:
        st = line.strip()
        if not st:
            continue
        if not line[:1].isspace():
            if st == "Private:":
                break
            if TOP_BREAK.match(line) and st not in ("Classes:", "Functions:", "Private:"):
                break
            continue
        if st in ("Classes:", "Functions:", "Private:", "(none)"):
            continue
        m = EXPORT_ITEM.match(line)
        if m:
            names.add(m.group(1))
    return names


def _public_module_members(tree: ast.Module) -> set[str]:
    """Return top-level public class and function names.

    Args:
        tree (ast.Module): Parsed module.

    Returns:
        set[str]: Public names.

    Examples:
        >>> _public_module_members(ast.parse("class A: pass\\ndef _b(): pass"))
        {'A'}
    """
    out: set[str] = set()
    for node in tree.body:
        if isinstance(
            node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) and not node.name.startswith("_"):
            out.add(node.name)
    return out


def _func_params(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    is_method: bool,
) -> list[ast.arg]:
    """Parameters requiring ``Args:`` lines (excludes ``self`` / ``cls``).

    Args:
        node (ast.FunctionDef | ast.AsyncFunctionDef): Callable AST node.
        is_method (bool): True if defined inside a class.

    Returns:
        list[ast.arg]: AST arg nodes.

    Examples:
        >>> import ast as A
        >>> t = A.parse("class C:\\n    def m(self, x: int) -> None: pass")
        >>> cls = t.body[0]
        >>> fn = cls.body[0]
        >>> assert isinstance(fn, A.FunctionDef)
        >>> [a.arg for a in _func_params(fn, is_method=True)]
        ['x']
    """
    a = node.args
    out: list[ast.arg] = [*a.posonlyargs, *a.args]
    if a.vararg:
        out.append(a.vararg)
    out.extend(a.kwonlyargs)
    if a.kwarg:
        out.append(a.kwarg)
    if is_method and out and out[0].arg in ("self", "cls"):
        out = out[1:]
    return out


def _has_dataclass_decorator(class_node: ast.ClassDef) -> bool:
    """Return True when ``class_node`` is decorated with ``@dataclass``.

    Args:
        class_node (ast.ClassDef): Class AST node.

    Returns:
        bool: Whether any decorator names ``dataclass``.

    Examples:
        >>> import ast as A
        >>> t = A.parse("@dataclass\\nclass C:\\n    x: int\\n").body[0]
        >>> assert isinstance(t, A.ClassDef)
        >>> _has_dataclass_decorator(t)
        True
    """
    for dec in class_node.decorator_list:
        name: str | None = None
        if isinstance(dec, ast.Name):
            name = dec.id
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            name = dec.func.id
        elif isinstance(dec, ast.Attribute):
            name = dec.attr
        if name == "dataclass":
            return True
    return False


def _is_synthesized_dataclass_init(
    class_node: ast.ClassDef,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Return True for ``@dataclass``-generated ``__init__`` (ADR §Data Models).

    Args:
        class_node (ast.ClassDef): Enclosing class.
        node (ast.FunctionDef | ast.AsyncFunctionDef): Method (typically ``__init__``).

    Returns:
        bool: Whether the method body is only a synthesized stub.

    Examples:
        >>> import ast as A
        >>> src = (
        ...     "@dataclass\\nclass C:\\n    x: int\\n\\n"
        ...     "    def __init__(self, x: int) -> None:\\n        pass\\n"
        ... )
        >>> cls = A.parse(src).body[0]
        >>> assert isinstance(cls, A.ClassDef)
        >>> init = next(
        ...     n for n in cls.body if isinstance(n, A.FunctionDef) and n.name == "__init__"
        ... )
        >>> _is_synthesized_dataclass_init(cls, init)
        True
    """
    if node.name != "__init__" or not _has_dataclass_decorator(class_node):
        return False
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return not body or (len(body) == 1 and isinstance(body[0], ast.Pass))


def _needs_returns_section(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if docstring should include ``Returns:`` per ADR.

    Args:
        node (ast.FunctionDef | ast.AsyncFunctionDef): Callable.

    Returns:
        bool: Whether ``Returns:`` is required.

    Examples:
        >>> import ast as A
        >>> n = A.parse("def f() -> None: pass").body[0]
        >>> assert isinstance(n, A.FunctionDef)
        >>> _needs_returns_section(n)
        False
    """
    ann = node.returns
    if ann is None:
        return False
    return not (
        (isinstance(ann, ast.Constant) and ann.value is None)
        or (isinstance(ann, ast.Name) and ann.id == "None")
    )


def _validate_callable_doc(
    path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    doc: str | None,
    *,
    is_method: bool,
    owner_class_name: str | None = None,
) -> list[Violation]:
    """Validate one callable docstring.

    Args:
        path (Path): File path.
        node (ast.FunctionDef | ast.AsyncFunctionDef): Callable.
        doc (str | None): Docstring or None.
        is_method (bool): Whether defined inside a class.
        owner_class_name (str | None): Class name when ``node`` is a method.

    Returns:
        list[Violation]: Violations.

    Examples:
        >>> fn = ast.parse("def g(): pass\\n").body[0]
        >>> assert isinstance(fn, ast.FunctionDef)
        >>> len(_validate_callable_doc(Path("x.py"), fn, None, is_method=False))
        1
    """
    violations: list[Violation] = []
    if not doc:
        return [
            Violation(
                path,
                node.lineno,
                f"{node.__class__.__name__} {node.name!r} missing docstring",
            ),
        ]

    params = _func_params(node, is_method=is_method)
    if params and "Args:" not in doc:
        violations.append(
            Violation(
                path,
                node.lineno,
                f"{node.name!r} needs Args: (has parameters)",
            ),
        )
    else:
        for arg in params:
            pat = rf"^\s*{re.escape(arg.arg)} \(.*\):"
            if not re.search(pat, doc, flags=re.MULTILINE):
                violations.append(
                    Violation(
                        path,
                        arg.lineno or node.lineno,
                        f"{node.name!r}: Args: missing `{arg.arg} (type):` line",
                    ),
                )

    if _needs_returns_section(node) and "Returns:" not in doc:
        violations.append(
            Violation(path, node.lineno, f"{node.name!r} needs Returns: for non-None return"),
        )

    if "Examples:" not in doc or ">>>" not in doc:
        violations.append(
            Violation(
                path,
                node.lineno,
                f"{node.name!r} needs Examples: with >>> block",
            ),
        )
    else:
        for msg in _doctest_example_syntax_messages(doc):
            violations.append(
                Violation(
                    path,
                    node.lineno,
                    f"{node.name!r} {msg}",
                ),
            )
        for msg in _behavioral_example_messages(
            doc,
            node,
            owner_class_name=owner_class_name,
            path=path,
        ):
            violations.append(Violation(path, node.lineno, f"{node.name!r} {msg}"))
    return violations


def _walk_class(path: Path, c: ast.ClassDef) -> list[Violation]:
    """Validate class docstring and methods.

    Args:
        path (Path): File path.
        c (ast.ClassDef): Class AST node.

    Returns:
        list[Violation]: Collected issues.

    Examples:
        >>> _walk_class(Path("x"), ast.parse("class C:\\n    pass").body[0])
        [Violation(path=PosixPath('x'), lineno=1, message="class 'C' missing docstring")]
    """
    violations: list[Violation] = []
    if not ast.get_docstring(c, clean=True):
        violations.append(
            Violation(path, c.lineno, f"class {c.name!r} missing docstring"),
        )
    for item in c.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            if _is_synthesized_dataclass_init(c, item):
                continue
            violations.extend(
                _validate_callable_doc(
                    path,
                    item,
                    ast.get_docstring(item, clean=True),
                    is_method=True,
                    owner_class_name=c.name,
                ),
            )
        elif isinstance(item, ast.ClassDef):
            violations.extend(_walk_class(path, item))
    return violations


def _check_file(path: Path) -> list[Violation]:
    """Validate one Python file.

    Args:
        path (Path): Path to ``.py``.

    Returns:
        list[Violation]: All violations.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp()) / "m.py"
        >>> src = "\\n".join([
        ...     "'''M.", "", "Module: m", "", "Exports:", "    (none)", "'''",
        ...     "", "from __future__ import annotations", "", "",
        ... ])
        >>> _ = d.write_text(src, encoding="utf-8")
        >>> _check_file(d)
        []
    """
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [Violation(path, exc.lineno or 0, f"syntax error: {exc}")]

    violations: list[Violation] = []
    mod_doc = ast.get_docstring(tree, clean=True)
    if not mod_doc:
        return [Violation(path, 1, "missing module docstring")]

    if mod_msg := _module_callable_only_violation(mod_doc):
        violations.append(Violation(path, 1, mod_msg))

    public = _public_module_members(tree)
    exports = _parse_export_names(mod_doc)
    if public:
        if "Exports:" not in mod_doc:
            violations.append(
                Violation(path, 1, f"public symbols {sorted(public)} need Exports: block"),
            )
        else:
            if missing := public - exports:
                violations.append(
                    Violation(path, 1, f"Exports: missing names {sorted(missing)}"),
                )
            if extra := exports - public:
                violations.append(
                    Violation(path, 1, f"Exports: spurious names {sorted(extra)}"),
                )

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            violations.extend(_walk_class(path, node))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            violations.extend(
                _validate_callable_doc(
                    path,
                    node,
                    ast.get_docstring(node, clean=True),
                    is_method=False,
                    owner_class_name=None,
                ),
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    """Run checker.

    Args:
        argv (list[str] | None): CLI args; default ``sys.argv[1:]``.

    Returns:
        int: 0 if clean.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp()) / "m.py"
        >>> body = "\\n".join(["'''M.", "", "Module: m", "", "Exports:", "    (none)", "'''", "", "from __future__ import annotations", "", ""])
        >>> _ = d.write_text(body, encoding="utf-8")
        >>> main([str(d)])
        0
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="+")
    args = p.parse_args(argv)

    files: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        else:
            files.append(path)

    viols: list[Violation] = []
    for f in files:
        if "__pycache__" in f.parts:
            continue
        if "bundled_skills" in f.parts:
            continue
        viols.extend(_check_file(f))

    if not viols:
        return 0
    for v in viols:
        print(f"{v.path}:{v.lineno}: {v.message}", file=sys.stderr)
    print(f"\n{len(viols)} docstring violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
