from __future__ import annotations

"""Control discovery and scoring for bundled ``playwright-browser`` scripts.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._controls
Depends: typing

Exports:
    score_control — rank interactive elements by form relevance.
    suggest_selector — build a CSS hint from element metadata.
    enrich_controls — add scores and sort control rows.
"""

from typing import Any


def suggest_selector(meta: dict[str, Any]) -> str:
    """Build a CSS selector hint from element metadata.

    Args:
        meta (dict[str, Any]): ``id``, ``name``, ``tag``, ``type``, etc.

    Returns:
        str: Best-effort CSS selector or empty string.

    Examples:
        >>> suggest_selector({"id": "email", "tag": "input", "name": ""})
        '#email'
    """
    tag = str(meta.get("tag") or "")
    el_id = str(meta.get("id") or "")
    name = str(meta.get("name") or "")
    typ = str(meta.get("type") or "")
    if el_id and el_id[0].isalpha():
        return f"#{el_id}"
    if name and tag in {"input", "select", "textarea"}:
        escaped = name.replace('"', '\\"')
        if typ:
            return f'{tag}[name="{escaped}"][type="{typ}"]'
        return f'{tag}[name="{escaped}"]'
    placeholder = str(meta.get("placeholder") or "")
    if placeholder:
        escaped = placeholder.replace('"', '\\"')
        return f'{tag}[placeholder="{escaped}"]'
    aria = str(meta.get("aria_label") or "")
    if aria:
        escaped = aria.replace('"', '\\"')
        return f'[aria-label="{escaped}"]'
    return ""


def score_control(row: dict[str, Any]) -> int:
    """Rank an interactive element for form-filling priority.

    Args:
        row (dict[str, Any]): Control metadata from ``list_controls`` JS.

    Returns:
        int: Higher scores surface first in agent-facing lists.

    Examples:
        >>> score_control({"tag": "input", "type": "email", "required": True, "visible": True}) > 40
        True
    """
    score = 0
    tag = str(row.get("tag") or "")
    typ = str(row.get("type") or "").lower()
    if tag in {"input", "select", "textarea"}:
        score += 30
    if row.get("required"):
        score += 25
    if row.get("visible"):
        score += 15
    if row.get("disabled"):
        score -= 40
    if row.get("label") or row.get("placeholder") or row.get("aria_label"):
        score += 10
    if typ in {"email", "password", "tel", "date", "datetime-local", "time", "number"}:
        score += 12
    if typ in {"text", "search", "url"}:
        score += 8
    if typ in {"checkbox", "radio"}:
        score += 5
    if typ == "submit" or tag == "button":
        score += 4
    if tag == "a" and row.get("href"):
        score += 2
    return score


def enrich_controls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach ``importance`` scores and refresh ``suggest`` hints.

    Args:
        rows (list[dict[str, Any]]): Raw control rows from page JS.

    Returns:
        list[dict[str, Any]]: Rows sorted by descending ``importance``.

    Examples:
        >>> rows = enrich_controls([
        ...     {"tag": "button", "type": "submit", "visible": True},
        ...     {"tag": "input", "type": "email", "required": True, "visible": True},
        ... ])
        >>> rows[0]["tag"]
        'input'
    """
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if not item.get("suggest"):
            item["suggest"] = suggest_selector(item)
        item["importance"] = score_control(item)
        enriched.append(item)
    enriched.sort(key=lambda r: int(r.get("importance") or 0), reverse=True)
    return enriched
