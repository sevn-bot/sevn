"""Deterministic MYCODE repository walker (`specs/28-code-understanding.md` §2.3).

Module: sevn.code_understanding.mycode_scan
Depends: ast, fnmatch, pathlib, sevn.code_understanding.models

Internal helpers (``_git_tracked_rel_paths``, ``_enumerate_files``, ``_looks_ignored``,
``_scan_python``, ``_scan_with_regex``) and constants (``_LANGUAGE_BY_SUFFIX``,
``_DECL_PATTERNS_BY_LANGUAGE``) drive the walk; they are not part of the public API.
The enumeration is gitignore-aware: for a git checkout only tracked files are scanned.

Exports:
    scan_repo — walk a repository root and return a deterministic digest.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.code_understanding.models import MycodeFileEntry, MycodeScanDigest

if TYPE_CHECKING:
    from collections.abc import Iterable

_LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
}

_DECL_PATTERNS_BY_LANGUAGE: dict[str, list[re.Pattern[str]]] = {
    "typescript": [
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ],
    "javascript": [
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ],
    "go": [
        re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:struct|interface)"),
    ],
    "rust": [
        re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ],
}


def _git_tracked_rel_paths(root: Path) -> list[Path] | None:
    """Return repo-relative tracked file paths via ``git ls-files`` (gitignore-aware).

    Enumerating only tracked files guarantees ``.gitignore`` is honoured, so reference
    checkouts, ``plan``/``reports`` trees, local notes, and caches that merely sit in
    the checkout directory are never indexed into ``MYCODE.md`` — keeping the scanned
    set identical to the ``workspace/source_code`` mirror. Returns ``None`` when
    ``root`` is not a usable git checkout, so the caller falls back to a filesystem
    walk (e.g. an installed package or a plain directory).

    Args:
        root (Path): Resolved scan root.

    Returns:
        list[Path] | None: Tracked relative paths, or ``None`` when git is unavailable.

    Examples:
        >>> from pathlib import Path
        >>> _git_tracked_rel_paths(Path("/nonexistent")) is None
        True
    """
    import subprocess  # nosec B404 — fixed git argv only; no shell

    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(  # nosec
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [Path(p.decode("utf-8")) for p in proc.stdout.split(b"\x00") if p]


def _enumerate_files(root_abs: Path) -> list[Path]:
    """Return the absolute files to scan under ``root_abs`` (gitignore-aware).

    When ``root_abs`` is a git checkout, only git-tracked files are returned, so
    gitignored trees on disk (reference checkouts, ``plan``/``reports``, caches) are
    never indexed — matching the ``workspace/source_code`` mirror. Otherwise the full
    recursive filesystem listing is returned and ignore patterns are applied by the
    caller. Results are sorted for deterministic output.

    Args:
        root_abs (Path): Resolved scan root.

    Returns:
        list[Path]: Absolute file paths to consider, sorted deterministically.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> d = _P(tempfile.mkdtemp())
        >>> _ = (d / "x.py").write_text("x = 1\\n", encoding="utf-8")
        >>> [p.name for p in _enumerate_files(d)]
        ['x.py']
    """
    tracked = _git_tracked_rel_paths(root_abs)
    if tracked is not None:
        files = [root_abs / rel for rel in tracked]
        return sorted(p for p in files if p.is_file())
    return sorted(p for p in root_abs.rglob("*") if p.is_file())


def _looks_ignored(rel_posix: str, patterns: list[str]) -> bool:
    """Return True when ``rel_posix`` matches any pattern.

    Args:
        rel_posix (str): POSIX-style path relative to the scan root.
        patterns (list[str]): Glob fragments (gitignore-style; ``**`` supported by fnmatch).

    Returns:
        bool: Whether the path is ignored.

    Examples:
        >>> _looks_ignored("a/b/c.py", ["a/*"])
        True
        >>> _looks_ignored("x.py", ["build/*"])
        False
    """
    for raw in patterns:
        pat = raw.strip()
        if not pat:
            continue
        if pat.endswith("/"):
            pat = pat + "*"
        if fnmatch.fnmatchcase(rel_posix, pat):
            return True
        # Also match basename and any leading-directory component
        head = rel_posix.split("/", 1)[0]
        if fnmatch.fnmatchcase(head, pat):
            return True
        if fnmatch.fnmatchcase(Path(rel_posix).name, pat):
            return True
    return False


def _scan_python(text: str) -> tuple[list[str], list[str]]:
    """Extract top-level symbol names and imports from a Python source string.

    Args:
        text (str): UTF-8 file contents.

    Returns:
        tuple[list[str], list[str]]: ``(symbols, imports)`` in source order.

    Examples:
        >>> _scan_python("import os\\ndef f():\\n    return 1\\n")
        (['f'], ['os'])
    """
    symbols: list[str] = []
    imports: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            symbols.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return symbols, imports


def _scan_with_regex(language: str, text: str) -> list[str]:
    """Apply per-language regex heuristics to extract declaration names.

    Args:
        language (str): Language tag (must be a key of ``_DECL_PATTERNS_BY_LANGUAGE``).
        text (str): File contents.

    Returns:
        list[str]: Detected symbol names in source order; empty for unsupported tags.

    Examples:
        >>> _scan_with_regex("typescript", "export class Foo {}\\n")
        ['Foo']
        >>> _scan_with_regex("rust", "pub fn bar() {}\\n")
        ['bar']
    """
    patterns = _DECL_PATTERNS_BY_LANGUAGE.get(language)
    if not patterns:
        return []
    out: list[str] = []
    for line in text.splitlines():
        for pat in patterns:
            m = pat.match(line)
            if m:
                out.append(m.group(1))
                break
    return out


def scan_repo(root: Path, ignore: Iterable[str]) -> MycodeScanDigest:
    """Walk ``root`` deterministically and return a :class:`MycodeScanDigest`.

    The walk is filesystem-only: no LLM calls and no network. When ``root`` is a git
    checkout, only git-tracked files are enumerated (via ``git ls-files``), so
    gitignored trees on disk are never indexed and the scanned set matches the
    ``workspace/source_code`` mirror; non-git roots fall back to a full filesystem
    walk. Python files are parsed with the stdlib ``ast`` module; JS/TS/Go/Rust use
    lightweight regex declaration heuristics. Ignore patterns follow gitignore-style
    fragments matched via :func:`fnmatch.fnmatchcase` and are applied on top of the
    enumeration in both modes.

    Args:
        root (Path): Repository root; resolved to an absolute path before walk.
        ignore (Iterable[str]): Glob fragments to exclude.

    Returns:
        MycodeScanDigest: Sorted per-file digest; safe to serialise to JSON.

    Raises:
        FileNotFoundError: When ``root`` does not exist on disk.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> d = _P(tempfile.mkdtemp())
        >>> _ = (d / "x.py").write_text("def hi():\\n    return 1\\n")
        >>> digest = scan_repo(d, [])
        >>> digest.files[0].path
        'x.py'
    """
    root_abs = root.resolve()
    if not root_abs.exists():
        msg = f"scan root does not exist: {root_abs}"
        raise FileNotFoundError(msg)

    patterns = [p for p in ignore if p]
    paths: list[Path] = []
    for p in _enumerate_files(root_abs):
        rel = p.relative_to(root_abs).as_posix()
        if _looks_ignored(rel, patterns):
            continue
        paths.append(p)

    entries: list[MycodeFileEntry] = []
    for path in paths:
        rel = path.relative_to(root_abs).as_posix()
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "other")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            entries.append(MycodeFileEntry(path=rel, language=language, line_count=0))
            continue
        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        if language == "python":
            symbols, imports = _scan_python(text)
        else:
            symbols = _scan_with_regex(language, text)
            imports = []
        entries.append(
            MycodeFileEntry(
                path=rel,
                language=language,
                line_count=line_count,
                symbols=symbols,
                imports=imports,
            )
        )

    return MycodeScanDigest(
        root=str(root_abs),
        files=entries,
        ignored=list(patterns),
    )
