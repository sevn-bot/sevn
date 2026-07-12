"""HTML fragment builders for the bundled ``canvas`` skill (`specs/29-openui.md`).

Module: sevn.ui.openui.canvas_compose
Depends: html, json

Exports:
    escape_html — escape user text for OpenUI HTML fragments.
    build_openui_payload — assemble ``html`` + ``fallback_text`` + tool hint dict.
    compose_table_html — render a titled HTML table from column/row data.
    compose_cards_html — render a titled card grid from card dicts.
    table_fallback_text — plain-text fallback for table layouts.
    cards_fallback_text — plain-text fallback for card grids.
    parse_json_list — parse a JSON array CLI argument.

Examples:
    >>> from sevn.ui.openui.canvas_compose import compose_table_html
    >>> "Revenue" in compose_table_html("Q1", ["Metric", "Value"], [["Revenue", "10"]])
    True
"""

from __future__ import annotations

import html
from typing import Any


def escape_html(text: str) -> str:
    """Return HTML-escaped ``text`` for safe OpenUI fragments.

    Args:
        text (str): Raw user or agent text.

    Returns:
        str: Escaped string safe for HTML text nodes.

    Examples:
        >>> escape_html("<script>")
        '&lt;script&gt;'
    """
    return html.escape(text, quote=True)


def build_openui_payload(
    *,
    html_fragment: str,
    fallback_text: str,
    title: str | None = None,
    output: str = "live",
) -> dict[str, object]:
    """Build a payload the agent passes to native ``openui_render``.

    Args:
        html_fragment (str): Sanitiser-friendly HTML body.
        fallback_text (str): Plain-text fallback required by OpenUI.
        title (str | None, optional): Optional short title for channel adapters.
        output (str, optional): ``live``, ``screenshot``, or ``pdf``. Defaults to ``live``.

    Returns:
        dict[str, object]: ``html``, ``fallback_text``, and ``openui_render`` hint.

    Examples:
        >>> payload = build_openui_payload(html_fragment="<p>hi</p>", fallback_text="hi")
        >>> payload["openui_render"]["tool"]
        'openui_render'
    """
    arguments: dict[str, object] = {
        "html": html_fragment,
        "fallback_text": fallback_text,
        "output": output,
    }
    if title:
        arguments["title"] = title
    return {
        "html": html_fragment,
        "fallback_text": fallback_text,
        "openui_render": {
            "tool": "openui_render",
            "arguments": arguments,
        },
    }


def compose_table_html(
    title: str,
    columns: list[str],
    rows: list[list[str]],
) -> str:
    """Render a titled HTML table from column headers and row cells.

    Args:
        title (str): Table heading shown above the grid.
        columns (list[str]): Header labels.
        rows (list[list[str]]): Body rows aligned to ``columns`` width.

    Returns:
        str: HTML fragment using allowlisted table tags.

    Examples:
        >>> html_out = compose_table_html("Metrics", ["Name", "Value"], [["A", "1"]])
        >>> "<table" in html_out and "Metrics" in html_out
        True
    """
    head_cells = "".join(f"<th>{escape_html(col)}</th>" for col in columns)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{escape_html(str(cell))}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows)
    safe_title = escape_html(title)
    return (
        f'<div style="display:flex;flex-direction:column;gap:12px">'
        f"<h2>{safe_title}</h2>"
        f"<table><thead><tr>{head_cells}</tr></thead><tbody>{body}</tbody></table>"
        f"</div>"
    )


def compose_cards_html(title: str, cards: list[dict[str, str]]) -> str:
    """Render a responsive card grid from ``title`` + ``body`` dicts.

    Args:
        title (str): Section heading.
        cards (list[dict[str, str]]): Each card may include ``title`` and ``body`` keys.

    Returns:
        str: HTML fragment with a simple card grid layout.

    Examples:
        >>> out = compose_cards_html("Summary", [{"title": "A", "body": "one"}])
        >>> "Summary" in out and "one" in out
        True
    """
    card_nodes: list[str] = []
    for card in cards:
        card_title = escape_html(str(card.get("title", "")))
        card_body = escape_html(str(card.get("body", "")))
        card_nodes.append(
            '<div style="border:1px solid #ccc;border-radius:8px;padding:12px">'
            f"<b>{card_title}</b><p>{card_body}</p></div>",
        )
    grid = "".join(card_nodes)
    safe_title = escape_html(title)
    return (
        f'<div style="display:flex;flex-direction:column;gap:12px">'
        f"<h2>{safe_title}</h2>"
        f'<div style="display:grid;grid-template-columns:repeat(2, minmax(0,1fr));gap:12px">'
        f"{grid}</div></div>"
    )


def table_fallback_text(title: str, columns: list[str], rows: list[list[str]]) -> str:
    """Build a plain-text fallback for a table layout.

    Args:
        title (str): Table title.
        columns (list[str]): Header labels.
        rows (list[list[str]]): Body rows.

    Returns:
        str: Multi-line plain-text summary.

    Examples:
        >>> "Metric" in table_fallback_text("T", ["Metric"], [["A"]])
        True
    """
    lines = [title, " | ".join(columns)]
    for row in rows:
        lines.append(" | ".join(str(cell) for cell in row))
    return "\n".join(lines)


def cards_fallback_text(title: str, cards: list[dict[str, str]]) -> str:
    """Build a plain-text fallback for a card grid.

    Args:
        title (str): Section title.
        cards (list[dict[str, str]]): Card dicts with optional ``title`` / ``body``.

    Returns:
        str: Multi-line plain-text summary.

    Examples:
        >>> cards_fallback_text("S", [{"title": "A", "body": "b"}]).startswith("S")
        True
    """
    lines = [title]
    for card in cards:
        card_title = str(card.get("title", "")).strip()
        card_body = str(card.get("body", "")).strip()
        if card_title:
            lines.append(f"- {card_title}: {card_body}")
        else:
            lines.append(f"- {card_body}")
    return "\n".join(lines)


def parse_json_list(raw: str) -> list[Any]:
    """Parse a JSON array CLI argument.

    Args:
        raw (str): JSON text for a top-level array.

    Returns:
        list[Any]: Parsed list.

    Raises:
        ValueError: When JSON is invalid or not a list.

    Examples:
        >>> parse_json_list('[{"a": 1}]')[0]["a"]
        1
    """
    import json

    data = json.loads(raw)
    if not isinstance(data, list):
        msg = "expected JSON array"
        raise ValueError(msg)
    return data


__all__ = [
    "build_openui_payload",
    "cards_fallback_text",
    "compose_cards_html",
    "compose_table_html",
    "escape_html",
    "parse_json_list",
    "table_fallback_text",
]
