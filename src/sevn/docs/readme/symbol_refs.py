"""Path and symbol reference verification for README Level 3 (subsystem).

Module: sevn.docs.readme.symbol_refs
Depends: ast, pathlib, re

Exports:
    extract_level3_section — slice markdown between L3 and References headings.
    extract_curated_prose_section — slice curated Level 1-2 prose before L3.
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

_LEVEL1_START = re.compile(r"^##\s+Level 1 — Overview", re.MULTILINE)
_LEVEL3_START = re.compile(r"^##\s+Level 3 — Deep dive", re.MULTILINE)
_REFERENCES_START = re.compile(r"^##\s+References\b", re.MULTILINE)
_PY_PATH = re.compile(r"`(src/[^`\s]+\.py)`|\[[^\]]*\]\(([^)#\s]+\.py)(?:#L\d+)?\)")
_SYMBOL = re.compile(
    r"`([A-Z][A-Za-z0-9_]*(?:\.[a-z_][A-Za-z0-9_]*)+)`|"
    r"\[`([A-Z][A-Za-z0-9_]*(?:\.[a-z_][A-Za-z0-9_]*)+)`\]\([^)]+\.py#L\d+\)"
)
_SYMBOL_LINK = re.compile(
    r"\[`([A-Z][A-Za-z0-9_]*(?:\.[a-z_][A-Za-z0-9_]*)+)`\]\(([^)]+\.py)(?:#L\d+)?\)"
)
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


def extract_curated_prose_section(markdown: str) -> str:
    """Return curated Level 1-2 prose before the Level 3 heading.

        Args:
    markdown (str): Full README body.

        Returns:
            str: Level 1-2 section text (may be empty when headings are absent).

        Examples:
            >>> body = "## Level 1 — Overview\\n\\nL1\\n\\n## Level 2 — How it works\\n\\nL2\\n\\n## Level 3 — Deep dive\\n"
            >>> "L2" in extract_curated_prose_section(body)
            True
            >>> "Deep dive" not in extract_curated_prose_section(body)
            True
    """
    start = _LEVEL1_START.search(markdown)
    if start is None:
        l3 = _LEVEL3_START.search(markdown)
        return markdown[: l3.start()] if l3 else markdown
    section = markdown[start.start() :]
    l3 = _LEVEL3_START.search(section)
    if l3:
        return section[: l3.start()]
    return section


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
        rel = (match.group(1) or match.group(2) or "").strip()
        rel = _normalize_repo_py_path(rel)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        candidate = repo_root / rel
        if not candidate.is_file():
            errors.append(f"missing cited path: {rel}")
    return errors


def _normalize_repo_py_path(raw: str) -> str:
    """Normalize a markdown href or backtick path to a repo-relative ``src/...py`` path.

        Args:
    raw (str): Raw path from a README cite.

        Returns:
            str: Normalized repo-relative path, or empty when not derivable.

        Examples:
            >>> _normalize_repo_py_path("../../src/sevn/demo/a.py")
            'src/sevn/demo/a.py'
    """
    normalized = raw.replace("\\", "/").split("#", maxsplit=1)[0]
    if normalized.startswith("src/"):
        return normalized
    marker = "src/"
    idx = normalized.find(marker)
    if idx >= 0:
        return normalized[idx:]
    return normalized


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
    py_paths = [
        _normalize_repo_py_path(match.group(1) or match.group(2) or "")
        for match in _PY_PATH.finditer(text)
    ]
    py_paths = [path for path in py_paths if path]
    default_py = py_paths[0] if len(py_paths) == 1 else None

    for match in _SYMBOL.finditer(text):
        symbol = match.group(1) or match.group(2) or ""
        if not symbol or "." not in symbol:
            continue
        suffix = symbol.rsplit(".", maxsplit=1)[-1].lower()
        if suffix in _FILE_EXT_SUFFIXES:
            continue
        py_rel = _nearest_py_path(text, match.start(), py_paths, default_py)
        if py_rel is None:
            link = _SYMBOL_LINK.search(text, match.start(), match.end() + 120)
            if link:
                py_rel = _normalize_repo_py_path(link.group(2))
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
        for needle in (f"`{rel}`", f"]({rel}", f"](../../{rel}", rel):
            idx = text.rfind(needle, 0, symbol_pos)
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
