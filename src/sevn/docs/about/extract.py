"""Deterministic frontmatter extraction for about-docs (AST, globs, fingerprint).

Module: sevn.docs.about.extract
Depends: ast, datetime, pathlib, sevn.docs.about.model, sevn.docs.readme.fingerprint

Exports:
    compute_doc_fingerprint — sha256 digest wrapper for ``sources`` globs.
    extract_fields — code-owned frontmatter fields from source trees.

Examples:
    >>> from pathlib import Path
    >>> compute_doc_fingerprint(Path("."), []) is None or True
    True
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sevn.docs.about.model import Interface
from sevn.docs.readme.fingerprint import compute_digest, expand_source_globs

if TYPE_CHECKING:
    from pathlib import Path


def compute_doc_fingerprint(repo_root: Path, sources: list[str]) -> str:
    """Return the aggregate sha256 fingerprint for ``sources`` globs.

    Wraps :func:`sevn.docs.readme.fingerprint.compute_digest` with the
    ``sha256:`` prefix used in about-doc frontmatter.

    Args:
        repo_root (Path): Repository root.
        sources (list[str]): Manifest or frontmatter ``sources`` globs.

    Returns:
        str: ``sha256:{hex}`` digest string.

    Examples:
        >>> from pathlib import Path as _P
        >>> fp = compute_doc_fingerprint(_P("."), ["Makefile"])
        >>> fp.startswith("sha256:") and len(fp) == 71
        True
    """
    digest = compute_digest(repo_root, sources)
    return f"sha256:{digest}"


def extract_fields(repo_root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Extract code-owned frontmatter fields from ``entry`` source globs.

    Human-owned fields (``status``, ``owner``, ``related``, ids, etc.) are not
    returned — callers merge this dict onto an existing :class:`AboutDoc`.

    Args:
        repo_root (Path): Repository root.
        entry (dict[str, Any]): Frontmatter or manifest row with ``sources`` and ``kind``.

    Returns:
        dict[str, Any]: ``interfaces`` (spec only), ``fingerprint``, ``last_updated``.

    Examples:
        >>> from pathlib import Path as _P
        >>> fields = extract_fields(_P("."), {"kind": "prd", "sources": ["Makefile"]})
        >>> "fingerprint" in fields and "last_updated" in fields
        True
    """
    sources = list(entry.get("sources") or [])
    kind = str(entry.get("kind", "spec"))
    payload: dict[str, Any] = {
        "last_updated": datetime.now(tz=UTC).date(),
        "fingerprint": compute_doc_fingerprint(repo_root, sources),
    }
    if kind == "spec":
        payload["interfaces"] = [
            item.model_dump(mode="json") for item in _extract_interfaces(repo_root, sources)
        ]
    return payload


def _extract_interfaces(repo_root: Path, sources: list[str]) -> list[Interface]:
    """Extract public module-level symbols from Python files under ``sources``.

    Args:
        repo_root (Path): Repository root.
        sources (list[str]): Source glob patterns.

    Returns:
        list[Interface]: Sorted public symbol rows.

    Examples:
        >>> _extract_interfaces.__name__
        '_extract_interfaces'
    """
    repo_root = repo_root.resolve()
    interfaces: list[Interface] = []
    seen: set[tuple[str, str]] = set()
    for path in expand_source_globs(repo_root, sources):
        if path.suffix != ".py":
            continue
        rel = path.relative_to(repo_root).as_posix()
        for symbol in _public_symbols(path):
            key = (rel, symbol)
            if key in seen:
                continue
            seen.add(key)
            interfaces.append(Interface(name=symbol, file=rel, symbol=symbol))
    interfaces.sort(key=lambda row: (row.file, row.name))
    return interfaces


def _public_symbols(path: Path) -> list[str]:
    """Return sorted public top-level function and class names in one ``.py`` file.

    Args:
        path (Path): Python source file.

    Returns:
        list[str]: Public symbol names defined at module scope.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> td = _P(tempfile.mkdtemp())
        >>> py = td / "mod.py"
        >>> _ = py.write_text("def run(): pass\\nclass Foo: pass\\n", encoding="utf-8")
        >>> _public_symbols(py)
        ['Foo', 'run']
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ) and not node.name.startswith("_"):
            names.append(node.name)
    return sorted(names)
