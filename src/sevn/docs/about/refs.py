"""File-path reference guard for about-docs published under ``about-sevn.bot/{prd,specs}/``.

Reads ``about-sevn.bot/_docsys/allowed-refs.txt`` (gitignore-style globs) and fails
when a doc cites a file-path reference outside the allowlist or that does not resolve
under the repository root. ``https://`` URLs and doc-``id`` links are always allowed.

Module: sevn.docs.about.refs
Depends: fnmatch, re, pathlib

Exports:
    load_allowlist — parse ``allowed-refs.txt`` patterns.
    is_allowed — gitignore-glob match for one repo-relative path.
    find_violations — return offending ``(lineno, ref)`` pairs for one doc file.

Examples:
    >>> load_allowlist.__name__
    'load_allowlist'
"""

from __future__ import annotations

import fnmatch
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_ID_PATTERN = re.compile(r"^(prd|spec)-\d{2}-[a-z0-9-]+$")
_LINK_TARGET_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def load_allowlist(path: Path) -> list[str]:
    """Parse ``allowed-refs.txt`` into gitignore-style glob patterns.

    Args:
        path (Path): Allowlist file path.

    Returns:
        list[str]: Non-empty patterns with ``#`` comments and blank lines removed.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp()) / "allowed-refs.txt"
        >>> _ = p.write_text("# comment\\nsrc/**\\n\\n", encoding="utf-8")
        >>> load_allowlist(p)
        ['src/**']
    """
    patterns: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            patterns.append(line)
    return patterns


def is_allowed(ref: str, allowlist: list[str]) -> bool:
    """Return whether ``ref`` matches any allowlist glob pattern.

    Args:
        ref (str): Repo-relative file path reference.
        allowlist (list[str]): Patterns from :func:`load_allowlist`.

    Returns:
        bool: ``True`` when any pattern matches using gitignore-style ``**`` rules.

    Examples:
        >>> is_allowed("src/sevn/gateway/agent_turn.py", ["src/**"])
        True
    """
    normalized = ref.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return any(_glob_match(normalized, pattern) for pattern in allowlist)


def _glob_match(path: str, pattern: str) -> bool:
    """Match one repo-relative path against a gitignore-style glob pattern.

    Args:
        path (str): Normalised repo-relative posix path.
        pattern (str): Allowlist glob pattern.

    Returns:
        bool: ``True`` when the path matches.

    Examples:
        >>> _glob_match("src/sevn/a.py", "src/**")
        True
    """
    normalised_pattern = pattern.replace("\\", "/").strip()
    if normalised_pattern.endswith("/**"):
        prefix = normalised_pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(f"{prefix}/")
    return fnmatch.fnmatch(path, normalised_pattern)


def _is_file_path_ref(ref: str) -> bool:
    """Return whether a markdown link target is a repo file-path reference.

    Args:
        ref (str): Raw markdown link target.

    Returns:
        bool: ``False`` for ``https://`` URLs and doc-``id`` links.

    Examples:
        >>> _is_file_path_ref("spec-17-gateway")
        False
    """
    token = ref.strip()
    if token.startswith(("https://", "http://")):
        return False
    return _ID_PATTERN.fullmatch(token) is None


def _extract_file_path_refs(text: str) -> list[tuple[int, str]]:
    """Return ``(lineno, ref)`` pairs for file-path markdown link targets.

    Args:
        text (str): Full markdown document text.

    Returns:
        list[tuple[int, str]]: One entry per file-path link target.

    Examples:
        >>> _extract_file_path_refs("[x](src/a.py)\\n")
        [(1, 'src/a.py')]
    """
    refs: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _LINK_TARGET_RE.finditer(line):
            target = match.group(1).strip()
            if _is_file_path_ref(target):
                refs.append((lineno, target))
    return refs


def find_violations(
    doc_file: Path,
    allowlist_file: Path,
    repo_dir: Path,
) -> list[tuple[int, str]]:
    """Return file-path reference violations for one about-doc markdown file.

    Args:
        doc_file (Path): Markdown doc to scan.
        allowlist_file (Path): ``allowed-refs.txt`` path.
        repo_dir (Path): Repository root used for must-resolve checks.

    Returns:
        list[tuple[int, str]]: Offending ``(lineno, ref)`` pairs; empty when clean.

    Examples:
        >>> find_violations.__name__
        'find_violations'
    """
    allowlist = load_allowlist(allowlist_file)
    try:
        text = doc_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[tuple[int, str]] = []
    for lineno, ref in _extract_file_path_refs(text):
        if not is_allowed(ref, allowlist):
            violations.append((lineno, ref))
            continue
        candidate = (repo_dir / ref).resolve()
        try:
            candidate.relative_to(repo_dir.resolve())
        except ValueError:
            violations.append((lineno, ref))
            continue
        if not candidate.is_file():
            violations.append((lineno, ref))
    return violations
