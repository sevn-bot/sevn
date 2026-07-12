"""Parse and match ``about-sevn.bot/Telegram Menu.html`` against live menu labels.

Module: scripts.telegram_menu_catalog
Depends: pathlib, re

Exports:
    catalog_has_live_button — whether dev catalog documents one live button.
    dev_norm_for_callback — callback → catalog norm key.
    is_final_action_button — terminal action vs submenu opener.
    match_dev_button — map live label to catalog row.
    norm_menu_label — normalize button text for lookup.
    parse_dev_root_tiles — root tile ids from dev HTML.
    parse_dev_telegram_menu_catalog — section and button metadata from dev HTML.
    sanitize_user_text — strip internal doc references.
    sections_block_bounds — slice bounds for the SECTIONS object.
    unescape_js_string — unescape JS string literals.
    user_menu_long — user-facing long description from dev copy.

Examples:
    >>> from pathlib import Path
    >>> norm_menu_label("Regen ✅")
    'regen'
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
DEV_TELEGRAM_HTML = REPO / "about-sevn.bot" / "Telegram Menu.html"

_DEV_SECTION_META_RE = re.compile(
    r"(\w+):\s*\{\s*\n\s*title:\s*\"([^\"]+)\",\s*\n\s*status:\s*\"([^\"]+)\",\s*\n\s*short:\s*\"((?:[^\"\\]|\\.)*)\",\s*\n\s*long:\s*\"((?:[^\"\\]|\\.)*)\"",
    re.MULTILINE,
)
_DEV_BTN_RE = re.compile(
    r"btn\(\"([^\"]+)\",\s*\"([^\"]+)\",\s*\n\s*\"((?:[^\"\\]|\\.)*)\",\s*\n\s*\"((?:[^\"\\]|\\.)*)\"",
    re.MULTILINE,
)
_ROOT_TILE_RE = re.compile(r'\["(\w+)",\s*"([^"]+)"\]')
_SPEC_STRIP_RE = re.compile(r"\([^)]*specs/[^)]*\)|`specs/[^`]+`", re.I)
_FORBIDDEN_MARKERS: tuple[str, ...] = ("src/sevn", "plan/", "prd/", "specs/")
_JARGON_SENTENCE_RE = re.compile(
    r"\b(cfg:|mutate_|_reload|MenuFormHandler|callback_data|spec_id|_READY_SPEC_IDS)\b",
    re.IGNORECASE,
)

_DEV_STATUS_USER: dict[str, str] = {
    "Ready": "Available",
    "WIP": "Coming soon",
    "Stub": "Coming soon",
    "Not Started": "Not yet available",
}

_LABEL_PREFIX_NORM: tuple[tuple[str, str], ...] = (
    ("dm policy", "dm policy cycle"),
    ("notify policy", "notify policy cycle"),
    ("λ-rlm", "λ-rlm enabled"),
    ("trace redaction", "trace redaction"),
)

_CALLBACK_DEV_NORM: tuple[tuple[str, str], ...] = (
    ("cfg:toggle:channels.telegram.dm_policy:", "dm policy cycle"),
    ("cfg:toggle:channels.telegram.telegram_notify_policy:", "notify policy cycle"),
    ("cfg:toggle:executors.tier_cd.lambda_rlm.enabled:", "λ-rlm enabled"),
    ("cfg:logs:tail:gateway:", "tail gateway"),
    ("cfg:logs:tail:proxy:", "tail proxy"),
    ("form:logs:grep", "grep logs"),
    ("cfg:logs:traces:", "recent traces"),
    ("form:logs:span_id", "trace by id"),
    ("cfg:logs:toggle_redaction", "trace redaction"),
    ("cfg:logs:toggle_logfire", "logfire export: on/off"),
    ("cfg:logs:deployment_id", "deployment id"),
    ("cfg:toggle:tracing.redaction.enabled:", "trace redaction"),
)

__all__ = [
    "catalog_has_live_button",
    "dev_norm_for_callback",
    "is_final_action_button",
    "match_dev_button",
    "norm_menu_label",
    "parse_dev_root_tiles",
    "parse_dev_telegram_menu_catalog",
    "sanitize_user_text",
    "sections_block_bounds",
    "unescape_js_string",
    "user_menu_long",
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


def norm_menu_label(label: str) -> str:
    """Normalize a menu button label for catalog lookup.

    Args:
        label (str): Visible Telegram button text.

    Returns:
        str: Lowercase key with emoji and suffix noise removed.

    Examples:
        >>> norm_menu_label("🚧 Queue: cancel (→ steer)")
        'queue: cancel'
    """
    text = label.strip().lstrip("🚧📋🔒 ").strip()
    text = re.sub(r"^[^\w]+", "", text, flags=re.UNICODE)
    text = re.sub(r"\s*✅\s*$", "", text)
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    text = text.replace("↔", " ").replace("->", " ")
    return re.sub(r"\s+", " ", text).casefold().strip()


def dev_norm_for_callback(callback_data: str) -> str | None:
    """Map a live callback to a developer-catalog button norm key.

    Args:
        callback_data (str): Telegram inline callback payload.

    Returns:
        str | None: Catalog norm when a prefix mapping exists.

    Examples:
        >>> dev_norm_for_callback("cfg:logs:tail:gateway:0")
        'tail gateway'
    """
    for prefix, norm in _CALLBACK_DEV_NORM:
        if callback_data.startswith(prefix) or callback_data == prefix:
            return norm
    return None


def is_final_action_button(callback_data: str) -> bool:
    """Return whether a button performs an action instead of opening a submenu.

    Args:
        callback_data (str): Telegram inline callback payload.

    Returns:
        bool: ``True`` when the button is a terminal action in the live bot.

    Examples:
        >>> is_final_action_button("cfg:toggle:channels.telegram.reply_keyboard.enabled:true")
        True
        >>> is_final_action_button("cfg:models:page:triager:0")
        False
    """
    return not (
        callback_data.startswith(("form:", "cfg:models:page:"))
        or callback_data in {"act:gateway:restart", "act:proxy:restart"}
    )


def user_menu_long(raw: str, *, fallback: str) -> str:
    """Turn a developer long description into user-facing copy.

    Args:
        raw (str): Long description from the developer menu catalog.
        fallback (str): Short description when long text is too technical.

    Returns:
        str: Sanitized paragraph suitable for the help preview.

    Examples:
        >>> user_menu_long("Show or hide Regen.", fallback="Toggle Regen.")
        'Show or hide Regen.'
    """
    text = unescape_js_string(raw)
    text = sanitize_user_text(text)
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n\n", " "))
    kept = [s for s in sentences if s and not _JARGON_SENTENCE_RE.search(s)]
    merged = " ".join(kept).strip()
    if len(merged) < 40:
        return fallback if len(fallback) >= len(merged) else merged or fallback
    return merged


def sections_block_bounds(text: str) -> tuple[int, int] | None:
    """Return start/end indices of the ``SECTIONS`` object body in dev HTML.

    Args:
        text (str): Full ``Telegram Menu.html`` file contents.

    Returns:
        tuple[int, int] | None: ``(start, end)`` slice into ``text``, or ``None``.

    Examples:
        >>> bounds = sections_block_bounds('const SECTIONS = {\\n      a: {}\\n    };')
        >>> bounds is not None
        True
    """
    start = text.find("const SECTIONS = {")
    if start < 0:
        return None
    end = text.find("\n    };", start)
    if end < 0:
        return None
    return start, end


def parse_dev_telegram_menu_catalog(
    path: Path | None = None,
    *,
    sanitize: bool = True,
) -> dict[str, dict[str, Any]]:
    """Parse section and button descriptions from ``Telegram Menu.html``.

    Args:
        path (Path | None): Catalog file; defaults to :data:`DEV_TELEGRAM_HTML`.
        sanitize (bool): When ``True``, strip jargon for user-facing fields.

    Returns:
        dict[str, dict[str, Any]]: Section id → metadata and button rows.

    Examples:
        >>> cat = parse_dev_telegram_menu_catalog()
        >>> "session" in cat
        True
    """
    html_path = path or DEV_TELEGRAM_HTML
    if not html_path.is_file():
        return {}
    text = html_path.read_text(encoding="utf-8")
    bounds = sections_block_bounds(text)
    if bounds is None:
        return {}
    _, end = bounds
    start = text.find("const SECTIONS = {")
    block = text[start:end]
    sections: dict[str, dict[str, Any]] = {}
    for match in _DEV_SECTION_META_RE.finditer(block):
        sid, title, status, short, long_desc = match.groups()
        buttons: list[dict[str, str]] = []
        sid_pos = match.start()
        next_section = _DEV_SECTION_META_RE.search(block, match.end())
        section_body = block[sid_pos : next_section.start() if next_section else len(block)]
        for btn_match in _DEV_BTN_RE.finditer(section_body):
            label, btn_status, btn_short, btn_long = btn_match.groups()
            short_u = (
                sanitize_user_text(unescape_js_string(btn_short))
                if sanitize
                else unescape_js_string(btn_short)
            )
            long_u = (
                user_menu_long(btn_long, fallback=short_u)
                if sanitize
                else unescape_js_string(btn_long)
            )
            buttons.append(
                {
                    "label": label,
                    "norm": norm_menu_label(label),
                    "status": _DEV_STATUS_USER.get(btn_status, "Coming soon"),
                    "short": short_u,
                    "long": long_u,
                },
            )
        short_raw = unescape_js_string(short)
        long_raw = unescape_js_string(long_desc)
        sections[sid] = {
            "title": title,
            "status": _DEV_STATUS_USER.get(status, "Coming soon"),
            "short": sanitize_user_text(short_raw) if sanitize else short_raw,
            "long": user_menu_long(long_raw, fallback=sanitize_user_text(short_raw))
            if sanitize
            else long_raw,
            "buttons": buttons,
        }
    return sections


def parse_dev_root_tiles(path: Path | None = None) -> list[tuple[str, str]]:
    """Parse ``ROOT_TILES`` entries from dev HTML.

    Args:
        path (Path | None): Catalog file; defaults to :data:`DEV_TELEGRAM_HTML`.

    Returns:
        list[tuple[str, str]]: ``(section_id, tile_label)`` pairs in file order.

    Examples:
        >>> tiles = parse_dev_root_tiles()
        >>> any(sid == "session" for sid, _ in tiles)
        True
    """
    html_path = path or DEV_TELEGRAM_HTML
    if not html_path.is_file():
        return []
    text = html_path.read_text(encoding="utf-8")
    start = text.find("const ROOT_TILES = [")
    if start < 0:
        return []
    end = text.find("];", start)
    if end < 0:
        return []
    block = text[start:end]
    return [(m.group(1), m.group(2)) for m in _ROOT_TILE_RE.finditer(block)]


def match_dev_button(
    dev_buttons: list[dict[str, str]],
    live_label: str,
    *,
    callback_data: str | None = None,
) -> dict[str, str] | None:
    """Find a developer-catalog button row for one live keyboard label.

    Args:
        dev_buttons (list[dict[str, str]]): Parsed catalog rows for one section.
        live_label (str): Label from the live keyboard builder.
        callback_data (str | None): Optional callback for dynamic-label fallback.

    Returns:
        dict[str, str] | None: Matching catalog row when found.

    Examples:
        >>> row = match_dev_button(
        ...     [{"norm": "regen", "short": "x", "long": "y", "status": "Available"}],
        ...     "Regen",
        ... )
        >>> row["short"]
        'x'
    """
    key = norm_menu_label(live_label)
    for row in dev_buttons:
        if row.get("norm") == key:
            return row
    cb_norm = dev_norm_for_callback(callback_data) if callback_data else None
    if cb_norm:
        for row in dev_buttons:
            if row.get("norm") == cb_norm:
                return row
    for prefix, target in _LABEL_PREFIX_NORM:
        if key.startswith(prefix):
            for row in dev_buttons:
                if row.get("norm") == target:
                    return row
    for row in dev_buttons:
        norm = str(row.get("norm", ""))
        if norm and (norm in key or key in norm):
            return row
    return None


def catalog_has_live_button(
    dev_buttons: list[dict[str, str]],
    live_label: str,
    *,
    callback_data: str | None = None,
) -> bool:
    """Return whether the dev catalog documents one live keyboard button.

    Args:
        dev_buttons (list[dict[str, str]]): Parsed catalog rows for one section.
        live_label (str): Label from the live keyboard builder.
        callback_data (str | None): Optional callback for dynamic-label fallback.

    Returns:
        bool: ``True`` when a matching ``btn(...)`` row exists.

    Examples:
        >>> catalog_has_live_button([{"norm": "regen", "label": "Regen"}], "Regen ✅")
        True
    """
    return match_dev_button(dev_buttons, live_label, callback_data=callback_data) is not None
