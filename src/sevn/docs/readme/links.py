"""Relative markdown link and anchor resolution for README checks.

Module: sevn.docs.readme.links
Depends: pathlib, re

Exports:
    validate_markdown_links — fail when relative links or anchors do not resolve.
    readme_relative_href — POSIX href from a README output path to a repo target.

Examples:
    >>> from pathlib import Path
    >>> errs = validate_markdown_links("[x](README.md)", Path("docs/readmes/x.md"), Path("."))
    >>> isinstance(errs, list)
    True
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_INLINE_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_REF_DEF = re.compile(r"^\[[^\]]+\]:\s+(\S+)", re.MULTILINE)
_REF_USE = re.compile(r"\[[^\]]+\]\[([^\]]+)\]")
_ANCHOR_NAME = re.compile(
    r'<a\s+(?:name|id)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)

# Gitignored local-only trees (CLAUDE.md "Git safety"). READMEs may link into
# them ("when present"); on CI runners and fresh clones the tree is absent, so
# such links are skipped rather than reported broken. They are still validated
# on operator checkouts where the tree exists.
_LOCAL_ONLY_TREES = ("specs", "plan", "prd", "examples", "prompts")


def readme_relative_href(
    *,
    readme_output: str,
    target: str,
    repo_root: Path,
    directory: bool = False,
    line: int | None = None,
) -> str:
    """Return a POSIX markdown href from a README file to a repo target.

        Args:
    readme_output (str): Manifest ``output`` path for the emitting README.
    target (str): Repo-relative path to the link target.
    repo_root (Path): Repository root.
    directory (bool): When true, ensure the href ends with ``/``.
    line (int | None): Optional 1-based source line for ``#L<line>`` fragments.

        Returns:
            str: File-relative href suitable for markdown link targets.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> readme = td / "docs/readmes/gateway.md"
            >>> readme.parent.mkdir(parents=True)
            >>> _ = readme.write_text("# Gateway\\n", encoding="utf-8")
            >>> spec = td / "about-sevn.bot/specs/17-gateway.md"
            >>> spec.parent.mkdir(parents=True)
            >>> _ = spec.write_text("# Spec\\n", encoding="utf-8")
            >>> readme_relative_href(
            ...     readme_output="docs/readmes/gateway.md",
            ...     target="about-sevn.bot/specs/17-gateway.md",
            ...     repo_root=td,
            ... )
            '../../about-sevn.bot/specs/17-gateway.md'
    """
    repo_root = repo_root.resolve()
    readme_dir = (repo_root / readme_output).resolve().parent
    target_path = (repo_root / target).resolve()
    if directory and (
        target_path.is_file() or (not target_path.exists() and not target.endswith("/"))
    ):
        target_path = target_path.parent
    href = Path(os.path.relpath(target_path, readme_dir)).as_posix()
    if directory and not href.endswith("/"):
        href += "/"
    if line is not None:
        href = f"{href}#L{int(line)}"
    return href


def validate_markdown_links(
    markdown: str,
    readme_path: Path,
    repo_root: Path,
) -> list[str]:
    """Return errors for unresolved relative links and anchors.

        Args:
    markdown (str): README body.
    readme_path (Path): Absolute path to the README file.
    repo_root (Path): Repository root for path resolution.

        Returns:
            list[str]: Human-readable link errors; empty when all resolve.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> readme = td / "docs/readmes/demo.md"
            >>> readme.parent.mkdir(parents=True)
            >>> _ = readme.write_text("# Demo\\n", encoding="utf-8")
            >>> _ = (td / "README.md").write_text("# Root\\n", encoding="utf-8")
            >>> validate_markdown_links("[root](../../README.md)", readme, td)
            []
    """
    repo_root = repo_root.resolve()
    readme_path = readme_path.resolve()
    readme_dir = readme_path.parent
    targets: list[str] = []

    for match in _INLINE_LINK.finditer(markdown):
        targets.append(match.group(1).strip())
    for match in _REF_DEF.finditer(markdown):
        targets.append(match.group(1).strip())
    for match in _REF_USE.finditer(markdown):
        label = match.group(1).strip()
        def_match = re.search(rf"^\[{re.escape(label)}\]:\s+(\S+)", markdown, re.MULTILINE)
        if def_match:
            targets.append(def_match.group(1).strip())

    errors: list[str] = []
    seen: set[str] = set()
    for raw in targets:
        if not raw or raw in seen:
            continue
        seen.add(raw)
        err = _validate_one_link(raw, readme_dir=readme_dir, repo_root=repo_root)
        if err:
            errors.append(err)
    return errors


def _validate_one_link(raw: str, *, readme_dir: Path, repo_root: Path) -> str | None:
    """Validate one link target.

        Args:
    raw (str): Raw URL from markdown.
    readme_dir (Path): Directory containing the README.
    repo_root (Path): Repository root.

        Returns:
            str | None: Error message when invalid; ``None`` when ok.

        Examples:
            >>> _validate_one_link("https://example.com", readme_dir=Path("."), repo_root=Path(".")) is None
            True
    """
    lowered = raw.lower()
    if lowered.startswith(("http://", "https://", "mailto:")):
        return None
    if raw.startswith("#"):
        return None

    path_part, _, anchor = raw.partition("#")
    if not path_part:
        return None

    if _skip_local_only_tree_link(path_part, repo_root=repo_root):
        return None

    candidate = _resolve_link_target(path_part, readme_dir=readme_dir, repo_root=repo_root)
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return f"link escapes repo root: {raw!r}"

    if not candidate.is_file() and not candidate.is_dir():
        try:
            top = candidate.relative_to(repo_root).parts[0]
        except (ValueError, IndexError):
            top = ""
        if top in _LOCAL_ONLY_TREES and not (repo_root / top).is_dir():
            return None
        return f"broken link: {raw!r} (missing {path_part})"

    if (
        anchor
        and candidate.is_file()
        and not (re.fullmatch(r"L\d+", anchor) and candidate.suffix == ".py")
        and not _anchor_exists(candidate.read_text(encoding="utf-8"), anchor)
    ):
        return f"broken anchor: {raw!r}"
    return None


def _resolve_link_target(path_part: str, *, readme_dir: Path, repo_root: Path) -> Path:
    """Resolve a relative link against the README's own directory only.

        Args:
    path_part (str): Path portion of a markdown link (no anchor).
    readme_dir (Path): Directory containing the README.
    repo_root (Path): Repository root (unused; kept for call-site stability).

        Returns:
            Path: Resolved target path.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> target = td / "src/a.py"
            >>> target.parent.mkdir(parents=True)
            >>> _ = target.write_text("x\\n", encoding="utf-8")
            >>> resolved = _resolve_link_target(
            ...     "../../src/a.py",
            ...     readme_dir=td / "docs/readmes",
            ...     repo_root=td,
            ... )
            >>> resolved.name
            'a.py'
    """
    _ = repo_root
    return (readme_dir / path_part).resolve()


def _skip_local_only_tree_link(path_part: str, *, repo_root: Path) -> bool:
    """Return True when a repo-root local-only tree link should be skipped.

        Args:
    path_part (str): Path portion of a markdown link (no anchor).
    repo_root (Path): Repository root.

        Returns:
            bool: True when the link targets a gitignored tree absent on this clone.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> _skip_local_only_tree_link("specs/17-gateway.md", repo_root=td)
            True
    """
    normalized = path_part.replace("\\", "/").lstrip("./")
    first = normalized.split("/", maxsplit=1)[0]
    if first not in _LOCAL_ONLY_TREES:
        return False
    return not (repo_root / first).is_dir()


def _anchor_exists(text: str, anchor: str) -> bool:
    """Return True when ``anchor`` exists in ``text``.

        Args:
    text (str): Target document body.
    anchor (str): Anchor id (without ``#``).

        Returns:
            bool: True when the anchor resolves.

        Examples:
            >>> _anchor_exists('<a name="readme-top"></a>\\n', "readme-top")
            True
    """
    normalized = anchor.strip().lower()
    for match in _ANCHOR_NAME.finditer(text):
        if match.group(1).strip().lower() == normalized:
            return True
    return any(_slugify_heading(match.group(1)) == normalized for match in _HEADING.finditer(text))


def _slugify_heading(text: str) -> str:
    """GitHub-style heading slug for anchor matching.

        Args:
    text (str): Heading text without ``#`` markers.

        Returns:
            str: Lowercase slug.

        Examples:
            >>> _slugify_heading("Quick start (TL;DR)")
            'quick-start-tldr'
    """
    slug = re.sub(r"[^\w\s-]", "", text.strip().lower())
    slug = re.sub(r"\s+", "-", slug)
    return slug.strip("-")
