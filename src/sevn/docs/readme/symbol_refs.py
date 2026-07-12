"""Path and symbol reference verification for README Level 3 (subsystem).

Module: sevn.docs.readme.symbol_refs
Depends: ast, pathlib, re

Exports:
    extract_level3_section — slice markdown between L3 and References headings.
    validate_path_refs — verify backtick ``src/...`` paths exist.
    validate_symbol_refs — verify ``Class.method`` symbols in cited Python files.

Examples:
    >>> from pathlib import Path
    >>> text = "## Level 3 — Deep dive\\n\\nSee `src/sevn/x/a.py`.\\n\\n## References\\n"
    >>> section = extract_level3_section(text)
    >>> "a.py" in section
    True
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_LEVEL3_START = re.compile(r"^##\s+Level 3 — Deep dive", re.MULTILINE)
_REFERENCES_START = re.compile(r"^##\s+References\b", re.MULTILINE)
_PY_PATH = re.compile(r"`(src/[^`\s]+\.py)`")
_SYMBOL = re.compile(r"`([A-Z][A-Za-z0-9_]*(?:\.[a-z_][A-Za-z0-9_]*)+)`")
_FILE_EXT_SUFFIXES = frozenset(
    {
        "css",
        "gif",
        "html",
        "jpeg",
        "jpg",
        "json",
        "md",
        "png",
        "py",
        "svg",
        "toml",
        "txt",
        "yaml",
        "yml",
    }
)


def extract_level3_section(markdown: str) -> str:
    """Return the Level 3 body between its heading and References.

        Args:
    markdown (str): Full README body.

        Returns:
            str: Level 3 section text (may be empty).

        Examples:
            >>> extract_level3_section("## Level 3 — Deep dive\\n\\nBody\\n\\n## References\\n")
            '\\n\\nBody\\n\\n'
    """
    start = _LEVEL3_START.search(markdown)
    if not start:
        return ""
    after = markdown[start.end() :]
    end = _REFERENCES_START.search(after)
    if end:
        return after[: end.start()]
    return after


def validate_path_refs(text: str, repo_root: Path) -> list[str]:
    """Verify backtick-quoted ``src/...py`` paths exist under ``repo_root``.

        Args:
    text (str): Markdown body to scan.
    repo_root (Path): Repository root.

        Returns:
            list[str]: Errors for missing paths.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> py = td / "src/sevn/demo/a.py"
            >>> py.parent.mkdir(parents=True)
            >>> _ = py.write_text("x=1\\n", encoding="utf-8")
            >>> validate_path_refs("See `src/sevn/demo/a.py`.", td)
            []
    """
    repo_root = repo_root.resolve()
    errors: list[str] = []
    seen: set[str] = set()
    for match in _PY_PATH.finditer(text):
        rel = match.group(1).strip()
        if rel in seen:
            continue
        seen.add(rel)
        candidate = repo_root / rel
        if not candidate.is_file():
            errors.append(f"missing cited path: {rel}")
    return errors


def validate_symbol_refs(text: str, repo_root: Path) -> list[str]:
    """Verify ``Class.method`` symbols cited in Level 3 exist in Python files.

        Args:
    text (str): Level 3 section body.
    repo_root (Path): Repository root.

        Returns:
            list[str]: Errors for symbols that cannot be resolved.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> py = td / "src/sevn/demo/a.py"
            >>> py.parent.mkdir(parents=True)
            >>> _ = py.write_text("class Foo:\\n    def bar(self): pass\\n", encoding="utf-8")
            >>> validate_symbol_refs("Entry `Foo.bar` in `src/sevn/demo/a.py`.", td)
            []
    """
    repo_root = repo_root.resolve()
    errors: list[str] = []
    py_paths = [match.group(1) for match in _PY_PATH.finditer(text)]
    default_py = py_paths[0] if len(py_paths) == 1 else None

    for match in _SYMBOL.finditer(text):
        symbol = match.group(1)
        if "." not in symbol:
            continue
        suffix = symbol.rsplit(".", maxsplit=1)[-1].lower()
        if suffix in _FILE_EXT_SUFFIXES:
            continue
        py_rel = _nearest_py_path(text, match.start(), py_paths, default_py)
        if py_rel is None:
            errors.append(f"symbol {symbol!r} has no associated .py path")
            continue
        py_file = repo_root / py_rel
        if not py_file.is_file():
            errors.append(f"symbol {symbol!r}: missing file {py_rel}")
            continue
        if not _symbol_defined_in_file(py_file, symbol):
            errors.append(f"symbol not found: {symbol} in {py_rel}")
    return errors


def _nearest_py_path(
    text: str,
    symbol_pos: int,
    py_paths: list[str],
    default_py: str | None,
) -> str | None:
    """Pick the closest preceding ``src/...py`` path for a symbol cite.

        Args:
    text (str): Section body.
    symbol_pos (int): Start index of the symbol match.
    py_paths (list[str]): All cited paths in the section.
    default_py (str | None): Sole path when only one is cited.

        Returns:
            str | None: Repo-relative Python path.

        Examples:
            >>> _nearest_py_path("in `src/a.py` see `Foo.bar`", 20, ["src/a.py"], "src/a.py")
            'src/a.py'
    """
    if default_py is not None:
        return default_py
    best: tuple[int, str] | None = None
    for rel in py_paths:
        idx = text.rfind(f"`{rel}`", 0, symbol_pos)
        if idx >= 0 and (best is None or idx > best[0]):
            best = (idx, rel)
    return best[1] if best else None


def _symbol_defined_in_file(py_file: Path, symbol: str) -> bool:
    """Return True when ``Class.method`` exists in ``py_file``.

        Args:
    py_file (Path): Python source file.
    symbol (str): Dotted symbol (``Class.method``).

        Returns:
            bool: True when AST walk finds the symbol.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> path = td / "m.py"
            >>> _ = path.write_text("class Foo:\\n    def bar(self): pass\\n", encoding="utf-8")
            >>> _symbol_defined_in_file(path, "Foo.bar")
            True
    """
    parts = symbol.split(".")
    if len(parts) < 2:
        return False
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except SyntaxError:
        return False

    if len(parts) == 2:
        class_name, method_name = parts[0], parts[1]
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == method_name
                    ):
                        return True
        return False

    class_path = parts[:-1]
    final_name = parts[-1]
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_path[0]):
            continue
        current: ast.ClassDef = node
        for nested_name in class_path[1:]:
            nxt: ast.ClassDef | None = None
            for child in current.body:
                if isinstance(child, ast.ClassDef) and child.name == nested_name:
                    nxt = child
                    break
            if nxt is None:
                break
            current = nxt
        else:
            for child in current.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and child.name == final_name
                ):
                    return True
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and target.id == final_name:
                            return True
                if (
                    isinstance(child, ast.AnnAssign)
                    and isinstance(child.target, ast.Name)
                    and child.target.id == final_name
                ):
                    return True
            return False
    return False
