"""About-docs validation gate (schema, drift, references, index).

Module: sevn.docs.about.check
Depends: pathlib, pydantic, sevn.docs.about.refs, sevn.docs.about.extract,
    sevn.docs.about.index, sevn.docs.about.loader, sevn.docs.readme.fingerprint

Exports:
    check_about_docs — return human-readable issue strings (empty means pass).

Examples:
    >>> from pathlib import Path
    >>> check_about_docs(Path("."))  # doctest: +SKIP
    []
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from sevn.docs.about.extract import compute_doc_fingerprint
from sevn.docs.about.index import index_path, render_index
from sevn.docs.about.loader import load_doc
from sevn.docs.about.refs import find_violations, is_allowed, load_allowlist
from sevn.docs.readme.fingerprint import expand_source_globs

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.docs.about.model import AboutDoc


def _iter_doc_paths(repo_root: Path) -> list[Path]:
    """Return markdown doc paths under ``about-sevn.bot/{prd,specs}/``.

    Args:
        repo_root (Path): Repository root.

    Returns:
        list[Path]: Doc paths excluding ``README.md`` index files.

    Examples:
        >>> _iter_doc_paths.__name__
        '_iter_doc_paths'
    """
    paths: list[Path] = []
    for subdir in ("prd", "specs"):
        directory = repo_root / "about-sevn.bot" / subdir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "README.md":
                continue
            paths.append(path)
    return paths


def _collect_id_refs(doc: AboutDoc) -> list[tuple[str, str]]:
    """Return ``(field_name, doc_id)`` pairs referenced from one doc.

    Args:
        doc (AboutDoc): Loaded frontmatter.

    Returns:
        list[tuple[str, str]]: Field label and referenced id.

    Examples:
        >>> from datetime import date
        >>> from sevn.docs.about.model import AboutDoc
        >>> d = AboutDoc(
        ...     id="spec-17-gateway",
        ...     kind="spec",
        ...     title="Gateway",
        ...     status="done",
        ...     owner="Alex",
        ...     summary="Turn spine.",
        ...     last_updated=date(2026, 6, 19),
        ...     parent_prd="prd-01-main",
        ...     sources=["src/sevn/gateway/**"],
        ...     related=["spec-18-channel-telegram"],
        ... )
        >>> any(field == "related" for field, _ in _collect_id_refs(d))
        True
    """
    refs: list[tuple[str, str]] = []
    for item in doc.related:
        refs.append(("related", item))
    for item in doc.depends_on:
        refs.append(("depends_on", item))
    for item in doc.specs:
        refs.append(("specs", item))
    if doc.parent_prd is not None:
        refs.append(("parent_prd", doc.parent_prd))
    return refs


def _is_optional_operator_path(path: str) -> bool:
    """Return whether ``path`` refers to gitignored operator-only kit content.

    Public CI clones omit trees such as ``wave-orchestrator/``; about-docs must
    not fail when those globs or interface files are absent on disk.

    Args:
        path (str): Source glob or repo-relative interface file path.

    Returns:
        bool: True when the path is optional operator-only content.

    Examples:
        >>> _is_optional_operator_path("wave-orchestrator/src/waveorch/cli.py")
        True
        >>> _is_optional_operator_path("src/sevn/gateway/agent_turn.py")
        False
    """
    return path.startswith("wave-orchestrator/")


def _check_sources_and_interfaces(
    repo_root: Path,
    doc: AboutDoc,
    allowlist: list[str],
) -> list[str]:
    """Validate ``sources`` globs and ``interfaces`` file paths.

    Args:
        repo_root (Path): Repository root.
        doc (AboutDoc): Loaded document.
        allowlist (list[str]): Parsed ``allowed-refs.txt`` patterns.

    Returns:
        list[str]: Issue strings for this document.

    Examples:
        >>> _check_sources_and_interfaces.__name__
        '_check_sources_and_interfaces'
    """
    issues: list[str] = []
    for pattern in doc.sources:
        if not is_allowed(pattern.rstrip("/"), allowlist) and not is_allowed(
            f"{pattern.rstrip('/')}/**", allowlist
        ):
            issues.append(f"{doc.id}: source glob not in allowlist: {pattern}")
            continue
        if not expand_source_globs(repo_root, [pattern]):
            if _is_optional_operator_path(pattern):
                continue
            issues.append(f"{doc.id}: source glob resolves to no files: {pattern}")
    for iface in doc.interfaces:
        if not is_allowed(iface.file, allowlist):
            issues.append(f"{doc.id}: interface file not in allowlist: {iface.file}")
            continue
        candidate = repo_root / iface.file
        if not candidate.is_file():
            if _is_optional_operator_path(iface.file):
                continue
            issues.append(f"{doc.id}: interface file missing: {iface.file}")
    return issues


def _check_fingerprint(repo_root: Path, doc: AboutDoc) -> list[str]:
    """Validate stored ``fingerprint`` against current ``sources`` digest.

    Args:
        repo_root (Path): Repository root.
        doc (AboutDoc): Loaded document.

    Returns:
        list[str]: Drift issue strings.

    Examples:
        >>> _check_fingerprint.__name__
        '_check_fingerprint'
    """
    if not doc.sources:
        return []
    expected = compute_doc_fingerprint(repo_root, list(doc.sources))
    if doc.fingerprint is None:
        return [f"{doc.id}: missing fingerprint (run about-docs extract)"]
    if doc.fingerprint != expected:
        return [f"{doc.id}: stale fingerprint (run about-docs extract)"]
    return []


def _check_index_files(repo_root: Path, loaded: dict[str, AboutDoc]) -> list[str]:
    """Verify generated index README files match :func:`render_index` output.

    Args:
        repo_root (Path): Repository root.
        loaded (dict[str, AboutDoc]): Loaded documents keyed by id.

    Returns:
        list[str]: Index drift issue strings.

    Examples:
        >>> _check_index_files.__name__
        '_check_index_files'
    """
    if not loaded:
        return []
    docs = list(loaded.values())
    issues: list[str] = []
    for kind in ("prd", "spec"):
        kind_docs = [doc for doc in docs if doc.kind == kind]
        if not kind_docs:
            continue
        expected = render_index(docs, kind)
        path = index_path(repo_root, kind)
        if not path.is_file():
            issues.append(
                f"{path.relative_to(repo_root).as_posix()}: missing index (run about-docs index)"
            )
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            rel = path.relative_to(repo_root).as_posix()
            issues.append(f"{rel}: stale index (run about-docs index)")
    return issues


def check_about_docs(repo_root: Path) -> list[str]:
    """Validate about-docs under ``repo_root`` and return issue strings.

    Checks schema validation, source resolution, fingerprint drift, reference
    allowlist + must-resolve, doc-id existence, and index freshness.

    Args:
        repo_root (Path): Repository root containing ``about-sevn.bot/``.

    Returns:
        list[str]: Issue strings; empty list means pass.

    Examples:
        >>> check_about_docs.__name__
        'check_about_docs'
    """
    repo_root = repo_root.resolve()
    issues: list[str] = []
    loaded: dict[str, AboutDoc] = {}

    allowlist_file = repo_root / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    allowlist = load_allowlist(allowlist_file) if allowlist_file.is_file() else []

    for path in _iter_doc_paths(repo_root):
        try:
            doc, _body = load_doc(path)
        except (OSError, ValueError, ValidationError) as exc:
            rel = path.relative_to(repo_root).as_posix()
            issues.append(f"{rel}: {exc}")
            continue
        loaded[doc.id] = doc
        if allowlist:
            issues.extend(_check_sources_and_interfaces(repo_root, doc, allowlist))
        issues.extend(_check_fingerprint(repo_root, doc))

    known_ids = set(loaded)
    for doc_id, doc in loaded.items():
        _ = doc_id
        for field_name, ref_id in _collect_id_refs(doc):
            if ref_id not in known_ids:
                issues.append(f"unknown {field_name} id: {ref_id}")

    for path in _iter_doc_paths(repo_root):
        if not allowlist_file.is_file():
            break
        rel = path.relative_to(repo_root).as_posix()
        for lineno, ref in find_violations(path, allowlist_file, repo_root):
            issues.append(f"{rel}:{lineno}: disallowed or missing file-path reference: {ref}")

    issues.extend(_check_index_files(repo_root, loaded))
    return issues
