"""Relative markdown link and anchor resolution for README checks.

Module: sevn.docs.readme.links
Depends: pathlib, re

Exports:
    validate_markdown_links — fail when relative links or anchors do not resolve.

Examples:
    >>> from pathlib import Path
    >>> errs = validate_markdown_links("[x](README.md)", Path("docs/readmes/x.md"), Path("."))
    >>> isinstance(errs, list)
    True
"""

from __future__ import annotations

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
        and not _anchor_exists(candidate.read_text(encoding="utf-8"), anchor)
    ):
        return f"broken anchor: {raw!r}"
    return None


def _resolve_link_target(path_part: str, *, readme_dir: Path, repo_root: Path) -> Path:
    """Resolve a relative link against readme dir then repo root.

        Args:
    path_part (str): Path portion of a markdown link (no anchor).
    readme_dir (Path): Directory containing the README.
    repo_root (Path): Repository root.

        Returns:
            Path: Best-effort resolved target path.

        Examples:
            >>> import tempfile
            >>> td = Path(tempfile.mkdtemp())
            >>> target = td / "src/a.py"
            >>> target.parent.mkdir(parents=True)
            >>> _ = target.write_text("x\\n", encoding="utf-8")
            >>> _resolve_link_target("src/a.py", readme_dir=td / "docs", repo_root=td).name
            'a.py'
    """
    from_readme = (readme_dir / path_part).resolve()
    from_root = (repo_root / path_part).resolve()
    for candidate in (from_readme, from_root):
        if candidate.is_file() or candidate.is_dir():
            return candidate
    return from_root


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
