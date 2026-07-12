"""Internal wiki link extraction and resolution (OKF + Obsidian wikilinks).

Module: sevn.second_brain.links
Depends: pathlib, re

Exports:
    iter_internal_link_targets — yield wikilink and OKF markdown link targets from body text.
    resolve_wiki_target — map a link target to an existing wiki-relative ``.md`` path.
    index_line_targets — extract catalog targets from one index bullet line.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]]+)?(?:\|[^\]]+)?\]\]")
_OKF_MD_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]+)?\)")


def _normalise_wikilink_target(target: str) -> str:
    """Return wiki-relative ``.md`` path for a wikilink stem or path.

    Args:
        target (str): Raw wikilink target from ``[[…]]``.

    Returns:
        str: Normalised relative path ending in ``.md`` (may be empty).

    Examples:
        >>> _normalise_wikilink_target("foo")
        'foo.md'
    """
    t = target.strip()
    if not t:
        return t
    return t if t.endswith(".md") else f"{t}.md"


def _normalise_okf_target(target: str, *, source_rel: str) -> str | None:
    """Return wiki-relative ``.md`` path for an OKF markdown link target.

    Args:
        target (str): Raw markdown link target.
        source_rel (str): Source page path for relative resolution.

    Returns:
        str | None: Wiki-relative ``.md`` path, or ``None`` when external/invalid.

    Examples:
        >>> _normalise_okf_target("/foo.md", source_rel="bar.md")
        'foo.md'
    """
    t = target.strip()
    if not t or not t.endswith(".md"):
        return None
    if t.startswith(("http://", "https://", "mailto:")):
        return None
    if t.startswith("/"):
        return t.lstrip("/")
    if t.startswith(("./", "../")):
        base = PurePosixPath(source_rel).parent if source_rel else PurePosixPath(".")
        rel = posixpath.normpath(str(PurePosixPath(base, t)))
        if rel in {".", ""} or rel.startswith(".."):
            return None
        return rel
    return None


def iter_internal_link_targets(body: str) -> Iterable[tuple[str, str]]:
    """Yield ``(kind, target)`` pairs for internal links in ``body``.

    Kinds: ``wikilink`` (``[[…]]``) and ``okf_md`` (markdown ``[text](/path.md)`` or relative).

    Args:
        body (str): Markdown body text.

    Yields:
        tuple[str, str]: Link kind and raw target string.

    Returns:
        Iterable[tuple[str, str]]: Generator of link kind and target pairs.

    Examples:
        >>> list(iter_internal_link_targets("See [[foo]] and [bar](/baz.md)"))
        [('wikilink', 'foo'), ('okf_md', '/baz.md')]
    """
    for target in _WIKILINK.findall(body):
        yield ("wikilink", target.strip())
    for match in _OKF_MD_LINK.finditer(body):
        target = match.group(1).strip()
        if target.startswith(("/", "./", "../")):
            yield ("okf_md", target)


def resolve_wiki_target(
    kind: str,
    target: str,
    *,
    source_rel: str,
    by_rel: dict[str, Path],
) -> str | None:
    """Resolve a link target to an existing wiki-relative path when present.

    Args:
        kind (str): ``wikilink`` or ``okf_md``.
        target (str): Raw link target from :func:`iter_internal_link_targets`.
        source_rel (str): Wiki-relative path of the page containing the link.
        by_rel (dict[str, Path]): Map of wiki-relative paths to files under ``wiki/``.

    Returns:
        str | None: Resolved wiki-relative path when it exists in ``by_rel``; else ``None``.

    Examples:
        >>> from pathlib import Path
        >>> by = {"a.md": Path("a.md")}
        >>> resolve_wiki_target("wikilink", "a", source_rel="b.md", by_rel=by)
        'a.md'
    """
    if kind == "wikilink":
        wikilink_cand = _normalise_wikilink_target(target)
        return wikilink_cand if wikilink_cand in by_rel else None
    if kind == "okf_md":
        okf_cand = _normalise_okf_target(target, source_rel=source_rel)
        return okf_cand if okf_cand and okf_cand in by_rel else None
    return None


def index_line_targets(line: str) -> list[str]:
    """Extract wiki-relative ``.md`` paths referenced on one index/catalog line.

    Supports wikilinks, OKF bundle-relative links, and bare ``path/to/page.md`` tokens.

    Args:
        line (str): One line from ``index.md`` (bullet or table cell).

    Returns:
        list[str]: Normalised wiki-relative paths (may include missing targets).

    Examples:
        >>> index_line_targets("- [[ingests/foo]] — title")
        ['ingests/foo.md']
        >>> index_line_targets("- [Title](/concepts/bar.md) — summary")
        ['concepts/bar.md']
    """
    out: list[str] = []
    seen: set[str] = set()
    for kind, target in iter_internal_link_targets(line):
        if kind == "wikilink":
            rel = _normalise_wikilink_target(target)
        else:
            rel = _normalise_okf_target(target, source_rel="index.md") or ""
        if rel and rel not in seen:
            seen.add(rel)
            out.append(rel)
    cleaned = re.sub(r"^[-*]\s+", "", line.strip())
    if "|" in cleaned:
        cleaned = cleaned.split("|", maxsplit=1)[0].strip()
    token = cleaned.strip()
    if token.endswith(".md") and token not in seen and not token.startswith("["):
        seen.add(token)
        out.append(token)
    return out


__all__ = [
    "index_line_targets",
    "iter_internal_link_targets",
    "resolve_wiki_target",
]
