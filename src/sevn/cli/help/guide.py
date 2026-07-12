"""Bundled narrative guides for ``sevn guide [topic]`` (D11).

Module: sevn.cli.help.guide
Depends: importlib.resources, pathlib

Exports:
    list_guide_topics — sorted topic slugs.
    load_guide — markdown body for a topic.
    guide_title — display title from markdown.
"""

from __future__ import annotations

import re
from importlib import resources as importlib_resources
from pathlib import Path

_GUIDE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

GUIDE_TOPICS: tuple[str, ...] = (
    "agent-tools",
    "channels",
    "config",
    "doctor",
    "getting-started",
    "logs-traces",
    "usage",
)


def _guides_dir() -> Path:
    """Return the packaged ``cli_guides`` directory path.

    Returns:
        Path: Directory containing ``*.md`` guide files.

    Examples:
        >>> path = _guides_dir()
        >>> path.name == "cli_guides"
        True
    """
    root = importlib_resources.files("sevn.data") / "cli_guides"
    return Path(str(root))


def list_guide_topics() -> list[str]:
    """List bundled guide topic slugs.

    Returns:
        list[str]: Sorted topic slugs present on disk.

    Examples:
        >>> topics = list_guide_topics()
        >>> "getting-started" in topics
        True
    """
    directory = _guides_dir()
    if not directory.is_dir():
        return []
    found = sorted(path.stem for path in directory.glob("*.md") if _GUIDE_SLUG_RE.match(path.stem))
    return found or list(GUIDE_TOPICS)


def load_guide(topic: str) -> str:
    """Load a guide markdown body by topic slug.

    Args:
        topic (str): Guide filename stem (e.g. ``getting-started``).

    Returns:
        str: UTF-8 markdown body.

    Raises:
        FileNotFoundError: When no guide file exists for ``topic``.
        ValueError: When ``topic`` is not a safe slug.

    Examples:
        >>> body = load_guide("getting-started")
        >>> body.startswith("#")
        True
    """
    slug = topic.strip().lower()
    if not _GUIDE_SLUG_RE.match(slug):
        msg = f"invalid guide topic slug: {topic!r}"
        raise ValueError(msg)
    path = _guides_dir() / f"{slug}.md"
    if not path.is_file():
        msg = f"no guide for topic {slug!r}; run `sevn guide` to list topics"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def guide_title(topic: str, body: str) -> str:
    """Extract a display title from guide markdown.

    Args:
        topic (str): Topic slug fallback.
        body (str): Guide markdown body.

    Returns:
        str: First ``#`` heading or a title-cased slug.

    Examples:
        >>> guide_title("foo", "# Hello\\n\\nbody")
        'Hello'
    """
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return topic.replace("-", " ").title()
