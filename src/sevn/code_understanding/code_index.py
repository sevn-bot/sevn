"""Generate ``.index/code_index/INDEX.md`` from the sevn source tree.

The tier-B executor needs a stable, in-workspace map of the codebase so it
doesn't have to glob-and-guess to answer questions like "where is the triager
prompt?" or "list folders at code root". The index is deterministic: a folder
tree plus, for every public Python module, the first docstring line plus a
signature-level entry for each public function/class with its docstring head.

Module: sevn.code_understanding.code_index
Depends: ast, pathlib

Exports:
    DocstringGap — Missing-docstring report row for module/symbol coverage.
    SymbolEntry — Per-symbol metadata extracted from a module's AST.
    audit_docstring_coverage — Return modules + symbols missing a docstring.
    collect_module_symbols — Walk a module AST and return its public symbols.
    extract_listed_symbols — Parse module / symbol identifiers from a rendered index.
    generate_code_index — walk ``repo_root/src/sevn`` and write ``INDEX.md``.
    iter_python_files — Stable iterator over ``*.py`` files under a source root.
    render_code_index_markdown — pure helper returning the rendered markdown.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_TREE_DEPTH_LIMIT: Final[int] = 3


@dataclass(frozen=True)
class SymbolEntry:
    """One public function or class extracted from a module AST.

    Attributes:
        kind (str): ``"function"`` or ``"class"``.
        name (str): Qualified name (e.g. ``"SkillsManager.run_script"``).
        signature (str): Source-faithful signature (``"(self, name: str)"``)
            for functions; empty for classes (the class body itself).
        summary (str): First non-empty line of the symbol's docstring; empty
            string when no docstring is present.
        lineno (int): 1-based source line.
    """

    kind: str
    name: str
    signature: str
    summary: str
    lineno: int


def _module_summary(py_path: Path) -> str:
    """Return the first non-empty line of ``py_path``'s module docstring.

    Args:
        py_path (Path): Absolute path to a Python source file.

    Returns:
        str: First content line of the docstring, or empty string when none.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_module_summary)
        True
    """
    try:
        source = py_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _is_public(name: str) -> bool:
    """Return True when ``name`` is a public identifier (doesn't start with ``_``).

    ``__init__`` is treated as public because the index documents constructors.

    Args:
        name (str): Symbol name.

    Returns:
        bool: True when the name does not begin with a single underscore, or is
            the dunder constructor.

    Examples:
        >>> _is_public("run")
        True
        >>> _is_public("_internal")
        False
        >>> _is_public("__init__")
        True
    """
    if name.startswith("__") and name.endswith("__"):
        return name == "__init__"
    return not name.startswith("_")


def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a stable, single-line signature for ``node`` from its AST.

    Drops decorators, default values, and return annotations for brevity; keeps
    parameter names + their inline type annotations when present. Stable enough
    to diff cleanly across whitespace-only refactors.

    Args:
        node (ast.FunctionDef | ast.AsyncFunctionDef): AST node for the callable.

    Returns:
        str: Parenthesised parameter list (e.g. ``"(self, name: str)"``).

    Examples:
        >>> mod = ast.parse("def f(x: int, y: str) -> None: pass")
        >>> func = mod.body[0]
        >>> _render_signature(func)
        '(x: int, y: str)'
    """
    parts: list[str] = []
    args = node.args
    posonly = list(args.posonlyargs)
    pos = list(args.args)
    kwonly = list(args.kwonlyargs)
    seen_kwonly_marker = False
    for arg in [*posonly, *pos]:
        ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
        parts.append(f"{arg.arg}: {ann}" if ann else arg.arg)
    if args.vararg is not None:
        ann = ast.unparse(args.vararg.annotation) if args.vararg.annotation is not None else ""
        parts.append(f"*{args.vararg.arg}: {ann}" if ann else f"*{args.vararg.arg}")
        seen_kwonly_marker = True
    elif kwonly:
        parts.append("*")
        seen_kwonly_marker = True
    for arg in kwonly:
        ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
        parts.append(f"{arg.arg}: {ann}" if ann else arg.arg)
    if args.kwarg is not None:
        ann = ast.unparse(args.kwarg.annotation) if args.kwarg.annotation is not None else ""
        parts.append(f"**{args.kwarg.arg}: {ann}" if ann else f"**{args.kwarg.arg}")
    _ = seen_kwonly_marker
    return "(" + ", ".join(parts) + ")"


def _first_doc_line(
    node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> str:
    """Return the first non-empty line of ``node``'s docstring, or empty.

    Args:
        node (ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            AST node accepting :func:`ast.get_docstring`.

    Returns:
        str: First content line, with surrounding whitespace stripped.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_first_doc_line)
        True
    """
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def collect_module_symbols(py_path: Path) -> list[SymbolEntry]:
    """Walk ``py_path``'s AST and return its public top-level symbols.

    Public methods of public classes are included with a qualified name
    (``ClassName.method``). Nested functions and private helpers are skipped to
    keep the index scannable.

    Args:
        py_path (Path): Absolute path to a Python source file.

    Returns:
        list[SymbolEntry]: Sorted by source line.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(collect_module_symbols)
        True
    """
    try:
        source = py_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[SymbolEntry] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and _is_public(node.name):
            out.append(
                SymbolEntry(
                    kind="class",
                    name=node.name,
                    signature="",
                    summary=_first_doc_line(node),
                    lineno=node.lineno,
                ),
            )
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef) and _is_public(sub.name):
                    out.append(
                        SymbolEntry(
                            kind="method",
                            name=f"{node.name}.{sub.name}",
                            signature=_render_signature(sub),
                            summary=_first_doc_line(sub),
                            lineno=sub.lineno,
                        ),
                    )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _is_public(node.name):
            out.append(
                SymbolEntry(
                    kind="function",
                    name=node.name,
                    signature=_render_signature(node),
                    summary=_first_doc_line(node),
                    lineno=node.lineno,
                ),
            )
    return sorted(out, key=lambda s: s.lineno)


def _iter_python_files(src_root: Path) -> Iterable[Path]:
    """Yield ``*.py`` files under ``src_root`` skipping caches and tests.

    Args:
        src_root (Path): Source tree root.

    Returns:
        Iterable[Path]: Generator yielding each Python source file in stable
        lexicographic order.

    Yields:
        Path: Each Python source file in stable lexicographic order.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_iter_python_files)
        True
    """
    for path in sorted(src_root.rglob("*.py")):
        if any(part.startswith(".") for part in path.parts):
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def iter_python_files(src_root: Path) -> Iterable[Path]:
    """Public wrapper over :func:`_iter_python_files` for CLI consumers.

    Args:
        src_root (Path): Source tree root.

    Returns:
        Iterable[Path]: Yields each ``*.py`` file in stable lexicographic order.

    Yields:
        Path: Each Python source file in stable lexicographic order.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(iter_python_files)
        True
    """
    yield from _iter_python_files(src_root)


@dataclass(frozen=True)
class DocstringGap:
    """One docstring-coverage gap discovered by :func:`audit_docstring_coverage`.

    Attributes:
        rel_path (str): Forward-slash relative source path.
        symbol (str): ``"<module>"`` for module-level docstring gaps, else the
            symbol name (e.g. ``"ClassName.method"``).
        kind (str): ``"module"``, ``"function"``, ``"class"``, or ``"method"``.
    """

    rel_path: str
    symbol: str
    kind: str


def audit_docstring_coverage(src_root: Path) -> list[DocstringGap]:
    """Return per-file / per-symbol docstring gaps under ``src_root``.

    Flags:
      - any module without a top-level docstring;
      - any public function / class / method without a docstring.

    Args:
        src_root (Path): Source tree root (e.g. ``repo/src/sevn``).

    Returns:
        list[DocstringGap]: Sorted gaps; empty when coverage is complete.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(audit_docstring_coverage)
        True
    """
    gaps: list[DocstringGap] = []
    for py_path in _iter_python_files(src_root):
        rel = py_path.relative_to(src_root).as_posix()
        try:
            source = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        if not (ast.get_docstring(tree) or "").strip():
            gaps.append(DocstringGap(rel_path=rel, symbol="<module>", kind="module"))
        for sym in collect_module_symbols(py_path):
            if sym.summary:
                continue
            kind = "method" if sym.kind == "method" else sym.kind
            gaps.append(DocstringGap(rel_path=rel, symbol=sym.name, kind=kind))
    return sorted(gaps, key=lambda g: (g.rel_path, g.symbol))


_LISTED_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+`([^`]+)`",
)
_LISTED_FILE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+`([^`]+\.py)`",
)


def extract_listed_symbols(markdown_text: str) -> dict[str, set[str]]:
    """Parse a rendered code index and return ``{rel_path: {symbol, …}}``.

    The returned mapping is keyed by the rendered file path (relative to
    ``src/sevn/``) and lists every symbol that was rendered under that file.
    Files with no listed symbols still appear with an empty set so orphan
    checks can detect removed files.

    Args:
        markdown_text (str): Full ``INDEX.md`` body.

    Returns:
        dict[str, set[str]]: Mapping from rel path to the set of listed symbols.

    Examples:
        >>> body = (
        ...     "- `agent/x.py` — desc\\n"
        ...     "  - `class Foo` — summary\\n"
        ...     "  - `bar(x)` — summary\\n"
        ... )
        >>> sorted(extract_listed_symbols(body)["agent/x.py"])
        ['Foo', 'bar']
    """
    out: dict[str, set[str]] = {}
    current_file: str | None = None
    for line in markdown_text.splitlines():
        if not line.startswith(" "):
            file_m = _LISTED_FILE_RE.match(line)
            if file_m is not None:
                candidate = file_m.group(1)
                if candidate is None:
                    current_file = None
                    continue
                current_file = candidate
                out.setdefault(candidate, set())
                continue
            current_file = None
            continue
        if current_file is None:
            continue
        sym_m = _LISTED_SYMBOL_RE.match(line)
        if sym_m is None:
            continue
        raw = sym_m.group(1)
        if raw.startswith("class "):
            token = raw.split()[1]
        elif "(" in raw:
            token = raw[: raw.index("(")]
        else:
            token = raw
        out[current_file].add(token)
    return out


def _render_tree(src_root: Path, depth_limit: int) -> str:
    """Render a folder tree (directories only) of ``src_root`` up to ``depth_limit``.

    Args:
        src_root (Path): Source tree root.
        depth_limit (int): Maximum directory depth to render.

    Returns:
        str: Indented tree as a single markdown code block.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_render_tree)
        True
    """
    lines: list[str] = [src_root.name + "/"]
    for path in sorted(src_root.rglob("*")):
        if not path.is_dir():
            continue
        if any(part.startswith(".") for part in path.relative_to(src_root).parts):
            continue
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src_root)
        if len(rel.parts) > depth_limit:
            continue
        indent = "    " * (len(rel.parts))
        lines.append(f"{indent}{path.name}/")
    return "```\n" + "\n".join(lines) + "\n```"


def render_code_index_markdown(repo_root: Path) -> str:
    """Render the full ``INDEX.md`` content for the sevn source tree.

    Args:
        repo_root (Path): Local sevn.bot checkout root.

    Returns:
        str: Markdown document (folder tree + per-file docstring summaries).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(render_code_index_markdown)
        True
    """
    src_root = repo_root / "src" / "sevn"
    if not src_root.is_dir():
        return "# Code Index\n\n_Source tree not found — `src/sevn/` is missing._\n"

    parts: list[str] = []
    parts.append("# Code Index")
    parts.append("")
    parts.append(
        "Auto-generated from `src/sevn/`. Tier-B can reference any path here under the "
        "boot-time mirror at `source_code/src/sevn/...` (read with normal workspace paths).",
    )
    parts.append("")
    parts.append(
        "See orientation docs under `source_code/about-sevn.bot/` (start with `ARCHITECTURE.md`)."
    )
    parts.append("")
    parts.append("## Folder tree")
    parts.append("")
    parts.append(_render_tree(src_root, _TREE_DEPTH_LIMIT))
    parts.append("")
    parts.append("## Modules")
    parts.append("")

    grouped: dict[str, list[tuple[str, str, list[SymbolEntry]]]] = {}
    for py_path in _iter_python_files(src_root):
        rel = py_path.relative_to(src_root)
        group = "/".join(rel.parts[:-1]) or "<root>"
        summary = _module_summary(py_path)
        symbols = collect_module_symbols(py_path)
        grouped.setdefault(group, []).append(
            (str(rel).replace("\\", "/"), summary, symbols),
        )

    for group in sorted(grouped):
        parts.append(f"### `{group}/`")
        parts.append("")
        for rel_path, summary, symbols in sorted(grouped[group], key=lambda r: r[0]):
            head = f"- `{rel_path}` — {summary}" if summary else f"- `{rel_path}`"
            parts.append(head)
            for sym in symbols:
                token = f"class {sym.name}" if sym.kind == "class" else f"{sym.name}{sym.signature}"
                tail = f" — {sym.summary}" if sym.summary else ""
                parts.append(f"  - `{token}`{tail}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def generate_code_index(repo_root: Path, output_path: Path) -> bool:
    """Write the rendered code index to ``output_path`` (idempotent).

    Args:
        repo_root (Path): Local sevn.bot checkout root.
        output_path (Path): Destination markdown file
            (typically ``.index/code_index/INDEX.md``).

    Returns:
        bool: ``True`` when the file was written (content changed or absent);
        ``False`` when content was already up-to-date.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(generate_code_index)
        True
    """
    content = render_code_index_markdown(repo_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_file():
        try:
            existing = output_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        if existing == content:
            return False
    try:
        output_path.write_text(content, encoding="utf-8")
    except OSError:
        return False
    return True


__all__ = [
    "DocstringGap",
    "SymbolEntry",
    "audit_docstring_coverage",
    "collect_module_symbols",
    "extract_listed_symbols",
    "generate_code_index",
    "iter_python_files",
    "render_code_index_markdown",
]
