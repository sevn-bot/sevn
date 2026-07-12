"""Parse and match ``about-sevn.bot/Mission Control.html`` against the live tab registry.

Module: scripts.mission_control_catalog
Depends: pathlib, re

Exports:
    catalog_has_live_tab — whether dev catalog documents one live tab.
    groups_block_bounds — slice bounds for the GROUPS object.
    match_dev_tab — map live tab label to catalog row.
    norm_tab_label — normalize tab text for lookup.
    parse_dev_group_nav — group nav entries from dev HTML.
    parse_dev_mission_control_catalog — group and tab metadata from dev HTML.
    sanitize_user_text — strip internal doc references.
    unescape_js_string — unescape JS string literals.
    user_tab_long — user-facing long description from dev copy.

Examples:
    >>> from pathlib import Path
    >>> norm_tab_label("Providers & LLMs")
    'providers & llms'
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

REPO = _REPO
DEV_MISSION_HTML = REPO / "about-sevn.bot" / "Mission Control.html"

_DEV_GROUP_META_RE = re.compile(
    r"([\w-]+):\s*\{\s*\n\s*title:\s*\"([^\"]+)\",\s*\n\s*status:\s*\"([^\"]+)\",\s*\n\s*short:\s*\"((?:[^\"\\]|\\.)*)\",\s*\n\s*long:\s*\"((?:[^\"\\]|\\.)*)\"",
    re.MULTILINE,
)
_DEV_TAB_RE = re.compile(
    r"TAB\(\"([^\"]+)\",\s*\"([^\"]+)\",\s*\n\s*\"((?:[^\"\\]|\\.)*)\",\s*\n\s*\"((?:[^\"\\]|\\.)*)\"",
    re.MULTILINE,
)
_GROUP_NAV_RE = re.compile(r'\["([\w-]+)",\s*"([^"]+)"\]')
_SPEC_STRIP_RE = re.compile(r"\([^)]*specs/[^)]*\)|`specs/[^`]+`", re.I)
_FORBIDDEN_MARKERS: tuple[str, ...] = ("src/sevn", "plan/", "prd/", "specs/")
_JARGON_SENTENCE_RE = re.compile(
    r"\b(WIRED_SLUGS|tab_registry|POST_V1_PLACEHOLDER|build_nav_payload)\b",
    re.IGNORECASE,
)

_DEV_STATUS_USER: dict[str, str] = {
    "Ready": "Available",
    "WIP": "Coming soon",
    "Stub": "Coming soon",
    "Not Started": "Not yet available",
}

__all__ = [
    "DEV_MISSION_HTML",
    "catalog_has_live_tab",
    "groups_block_bounds",
    "match_dev_tab",
    "norm_tab_label",
    "parse_dev_group_nav",
    "parse_dev_mission_control_catalog",
    "sanitize_user_text",
    "unescape_js_string",
    "user_tab_long",
]


def unescape_js_string(text: str) -> str:
    """Unescape a JavaScript string literal body.

    Args:
        text (str): Raw captured string.

    Returns:
        str: Plain text for HTML display.

    Examples:
        >>> unescape_js_string('line one\\n\\nline two')
        'line one\\n\\nline two'
    """
    return text.replace("\\n", "\n").replace('\\"', '"').strip()


def sanitize_user_text(text: str) -> str:
    """Strip internal doc references from user-visible copy.

    Args:
        text (str): Raw description text.

    Returns:
        str: Sanitized plain text.

    Examples:
        >>> sanitize_user_text("Memory (`specs/15-memory-lcm.md`).")
        'Memory.'
    """
    cleaned = _SPEC_STRIP_RE.sub("", text)
    for marker in _FORBIDDEN_MARKERS:
        if marker in cleaned.lower():
            return cleaned.split(".")[0].strip() + "."
    return " ".join(cleaned.split())


def norm_tab_label(label: str) -> str:
    """Normalize a tab label for catalog lookup.

    Args:
        label (str): Visible Mission Control tab name.

    Returns:
        str: Lowercase key with punctuation normalized.

    Examples:
        >>> norm_tab_label("Canvas (OpenUI)")
        'canvas (openui)'
    """
    text = label.strip()
    text = re.sub(r"\s+", " ", text)
    return text.casefold().strip()


def user_tab_long(raw: str, *, fallback: str) -> str:
    """Turn a developer long description into user-facing copy.

    Args:
        raw (str): Long description from the developer catalog.
        fallback (str): Short description when long text is too technical.

    Returns:
        str: Sanitized paragraph suitable for the help preview.

    Examples:
        >>> user_tab_long("Inspect live traces.", fallback="Traces.")
        'Inspect live traces.'
    """
    text = unescape_js_string(raw)
    text = sanitize_user_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n\n", " "))
    kept = [s for s in sentences if s and not _JARGON_SENTENCE_RE.search(s)]
    merged = " ".join(kept).strip()
    if len(merged) < 40:
        return fallback if len(fallback) >= len(merged) else merged or fallback
    return merged


def groups_block_bounds(text: str) -> tuple[int, int] | None:
    """Return start/end indices of the ``GROUPS`` object body in dev HTML.

    Args:
        text (str): Full ``Mission Control.html`` file contents.

    Returns:
        tuple[int, int] | None: ``(start, end)`` slice into ``text``, or ``None``.

    Examples:
        >>> bounds = groups_block_bounds('const GROUPS = {\\n      a: {}\\n    };')
        >>> bounds is not None
        True
    """
    start = text.find("const GROUPS = {")
    if start < 0:
        return None
    end = text.find("\n    };", start)
    if end < 0:
        return None
    return start, end


def parse_dev_mission_control_catalog(
    path: Path | None = None,
    *,
    sanitize: bool = True,
) -> dict[str, dict[str, Any]]:
    """Parse group and tab descriptions from ``Mission Control.html``.

    Args:
        path (Path | None): Catalog file; defaults to :data:`DEV_MISSION_HTML`.
        sanitize (bool): When ``True``, strip jargon for user-facing fields.

    Returns:
        dict[str, dict[str, Any]]: Group id → metadata and tab rows.

    Examples:
        >>> cat = parse_dev_mission_control_catalog()
        >>> "core" in cat or not DEV_MISSION_HTML.is_file()
        True
    """
    html_path = path or DEV_MISSION_HTML
    if not html_path.is_file():
        return {}
    text = html_path.read_text(encoding="utf-8")
    bounds = groups_block_bounds(text)
    if bounds is None:
        return {}
    _, end = bounds
    start = text.find("const GROUPS = {")
    block = text[start:end]
    groups: dict[str, dict[str, Any]] = {}
    for match in _DEV_GROUP_META_RE.finditer(block):
        gid, title, status, short, long_desc = match.groups()
        tabs: list[dict[str, str]] = []
        gid_pos = match.start()
        next_group = _DEV_GROUP_META_RE.search(block, match.end())
        group_body = block[gid_pos : next_group.start() if next_group else len(block)]
        for tab_match in _DEV_TAB_RE.finditer(group_body):
            label, tab_status, tab_short, tab_long = tab_match.groups()
            short_u = (
                sanitize_user_text(unescape_js_string(tab_short))
                if sanitize
                else unescape_js_string(tab_short)
            )
            long_u = (
                user_tab_long(tab_long, fallback=short_u)
                if sanitize
                else unescape_js_string(tab_long)
            )
            tabs.append(
                {
                    "label": label,
                    "norm": norm_tab_label(label),
                    "status": _DEV_STATUS_USER.get(tab_status, "Coming soon"),
                    "short": short_u,
                    "long": long_u,
                },
            )
        short_raw = unescape_js_string(short)
        long_raw = unescape_js_string(long_desc)
        groups[gid] = {
            "title": title,
            "status": _DEV_STATUS_USER.get(status, "Coming soon"),
            "short": sanitize_user_text(short_raw) if sanitize else short_raw,
            "long": user_tab_long(long_raw, fallback=sanitize_user_text(short_raw))
            if sanitize
            else long_raw,
            "tabs": tabs,
        }
    return groups


def parse_dev_group_nav(path: Path | None = None) -> list[tuple[str, str]]:
    """Parse ``GROUP_NAV`` entries from dev HTML.

    Args:
        path (Path | None): Catalog file; defaults to :data:`DEV_MISSION_HTML`.

    Returns:
        list[tuple[str, str]]: ``(group_id, nav_label)`` pairs in file order.

    Examples:
        >>> nav = parse_dev_group_nav()
        >>> not nav or nav[0][0]
        True
    """
    html_path = path or DEV_MISSION_HTML
    if not html_path.is_file():
        return []
    text = html_path.read_text(encoding="utf-8")
    start = text.find("const GROUP_NAV = [")
    if start < 0:
        return []
    end = text.find("];", start)
    if end < 0:
        return []
    block = text[start:end]
    return [(m.group(1), m.group(2)) for m in _GROUP_NAV_RE.finditer(block)]


def match_dev_tab(
    dev_tabs: list[dict[str, str]],
    live_label: str,
) -> dict[str, str] | None:
    """Find a developer-catalog tab row for one live tab label.

    Args:
        dev_tabs (list[dict[str, str]]): Parsed catalog rows for one group.
        live_label (str): Label from the live tab registry.

    Returns:
        dict[str, str] | None: Matching catalog row when found.

    Examples:
        >>> row = match_dev_tab(
        ...     [{"norm": "overview", "short": "x", "long": "y", "status": "Available"}],
        ...     "Overview",
        ... )
        >>> row["short"]
        'x'
    """
    key = norm_tab_label(live_label)
    for row in dev_tabs:
        if row.get("norm") == key:
            return row
    for row in dev_tabs:
        norm = str(row.get("norm", ""))
        if norm and (norm in key or key in norm):
            return row
    return None


def catalog_has_live_tab(
    dev_tabs: list[dict[str, str]],
    live_label: str,
) -> bool:
    """Return whether the dev catalog documents one live tab.

    Args:
        dev_tabs (list[dict[str, str]]): Parsed catalog rows for one group.
        live_label (str): Label from the live tab registry.

    Returns:
        bool: ``True`` when a matching ``TAB(...)`` row exists.

    Examples:
        >>> catalog_has_live_tab([{"norm": "overview", "label": "Overview"}], "Overview")
        True
    """
    return match_dev_tab(dev_tabs, live_label) is not None
