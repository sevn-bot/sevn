"""Telegram file-link buttons: convert ``[📎 send: <path>]`` markers into tap buttons.

Tier-B is instructed (`sevn.agent.persona.tier_b_file_link_prompt`) to append a
marker like ``[📎 send: skills/index.md]`` on its own line whenever a workspace
file is referenced and the user might want it delivered. This module:

1. Scans outbound text for those markers,
2. Strips them out of the visible body, and
3. Returns an ``inline_keyboard`` row of "📎 Send <name>" buttons whose
   ``callback_data`` is ``sf:<path>`` (or a ``ds:`` overflow token when the
   path doesn't fit in Telegram's 64-byte ``callback_data`` cap).

The inbound side (``sevn.gateway.commands.file_link_callback_handler``)
recognises ``sf:`` callbacks and dispatches them directly to ``send_file``
without spending an LLM round.

Module: sevn.channels.telegram_file_links
Depends: re

Exports:
    extract_file_link_paths — list workspace paths from an outbound text.
    strip_file_link_markers — return ``text`` with all markers removed.
    build_file_link_keyboard — render Telegram inline keyboard rows for paths.
    parse_file_link_callback — extract the workspace path from a ``sf:`` callback.

Note:
    Module-level constants ``FILE_LINK_CALLBACK_PREFIX`` (callback_data prefix)
    and ``FILE_LINK_MARKER_RE`` (compiled marker regex) are part of the public
    API surface; they are simple assignments and intentionally not listed in
    ``Exports:`` per the checker's class/function inventory rules.
"""

from __future__ import annotations

import re
from typing import Final

FILE_LINK_CALLBACK_PREFIX: Final[str] = "sf:"

# Marker syntax: `[📎 send: <relative_path>]` on its own line (whitespace
# tolerated either side). The path captures anything up to the closing bracket,
# excluding embedded brackets / newlines.
FILE_LINK_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\[\s*(?:📎|\\xf0\\x9f\\x93\\x8e)\s*send\s*:\s*(?P<path>[^\[\]\n]+?)\s*\]",
)


def extract_file_link_paths(text: str) -> list[str]:
    """Return the unique workspace paths referenced by file-link markers in ``text``.

    Args:
        text (str): Outbound assistant text.

    Returns:
        list[str]: Paths in first-seen order. Empty when no markers match.

    Examples:
        >>> extract_file_link_paths("here [📎 send: a.md] and [📎 send: b.md]")
        ['a.md', 'b.md']
        >>> extract_file_link_paths("no marker here")
        []
    """
    seen: list[str] = []
    for match in FILE_LINK_MARKER_RE.finditer(text or ""):
        path = match.group("path").strip()
        if path and path not in seen:
            seen.append(path)
    return seen


def strip_file_link_markers(text: str) -> str:
    """Return ``text`` with all file-link markers removed.

    Args:
        text (str): Outbound assistant text.

    Returns:
        str: ``text`` with markers excised; trailing whitespace collapsed.

    Examples:
        >>> strip_file_link_markers("done [📎 send: a.md]")
        'done'
        >>> strip_file_link_markers("plain")
        'plain'
    """
    out = FILE_LINK_MARKER_RE.sub("", text or "")
    # Collapse trailing whitespace on each line + final blank lines.
    lines = [line.rstrip() for line in out.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _button_label(path: str) -> str:
    """Render a compact button label for ``path`` (file name only, with 📎).

    Args:
        path (str): Workspace-relative path.

    Returns:
        str: Button label ``"📎 Send <basename>"``.

    Examples:
        >>> _button_label("skills/index.md")
        '📎 Send index.md'
        >>> _button_label("a.txt")
        '📎 Send a.txt'
    """
    tail = path.rstrip("/").split("/")[-1] or path
    return f"📎 Send {tail}"


def build_file_link_keyboard(paths: list[str]) -> dict[str, list[list[dict[str, str]]]] | None:
    """Return a Telegram inline-keyboard markup with one button per path.

    Args:
        paths (list[str]): Workspace-relative paths.

    Returns:
        dict[str, list[list[dict[str, str]]]] | None: Markup with one button per
        row, or ``None`` when ``paths`` is empty.

    Examples:
        >>> mk = build_file_link_keyboard(["a.md"])
        >>> mk["inline_keyboard"][0][0]["callback_data"]
        'sf:a.md'
        >>> build_file_link_keyboard([]) is None
        True
    """
    if not paths:
        return None
    rows: list[list[dict[str, str]]] = []
    for path in paths:
        rows.append(
            [
                {
                    "text": _button_label(path),
                    "callback_data": f"{FILE_LINK_CALLBACK_PREFIX}{path}",
                },
            ],
        )
    return {"inline_keyboard": rows}


def parse_file_link_callback(data: str) -> str | None:
    """Return the workspace path encoded in a ``sf:<path>`` callback.

    Args:
        data (str): Raw ``callback_data`` from Telegram (already expanded
            through the ``ds:`` overflow store, if applicable).

    Returns:
        str | None: Workspace-relative path, or ``None`` when ``data`` is not
        a file-link callback.

    Examples:
        >>> parse_file_link_callback("sf:skills/index.md")
        'skills/index.md'
        >>> parse_file_link_callback("menu:home") is None
        True
    """
    if not isinstance(data, str) or not data.startswith(FILE_LINK_CALLBACK_PREFIX):
        return None
    path = data[len(FILE_LINK_CALLBACK_PREFIX) :].strip()
    return path or None


__all__ = [
    "FILE_LINK_CALLBACK_PREFIX",
    "FILE_LINK_MARKER_RE",
    "build_file_link_keyboard",
    "extract_file_link_paths",
    "parse_file_link_callback",
    "strip_file_link_markers",
]
