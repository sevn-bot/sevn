#!/usr/bin/env python3
"""Bundled ``canvas`` skill — compose a card grid for ``openui_render``.

Module: sevn.data.bundled_skills.core.canvas.scripts.compose_cards
Depends: argparse, sevn.lcm.script_cli, sevn.ui.openui.canvas_compose

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_error, write_ok
from sevn.ui.openui.canvas_compose import (
    build_openui_payload,
    cards_fallback_text,
    compose_cards_html,
    parse_json_list,
)


def main() -> int:
    """Run card grid compose CLI.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--cards",
        required=True,
        help='JSON array of {"title": "...", "body": "..."} objects',
    )
    parser.add_argument("--output", choices=("live", "screenshot", "pdf"), default="live")
    args = parser.parse_args()
    try:
        cards_raw = parse_json_list(args.cards)
        cards: list[dict[str, str]] = []
        for item in cards_raw:
            if not isinstance(item, dict):
                msg = "each card must be a JSON object"
                raise ValueError(msg)
            cards.append({str(k): str(v) for k, v in item.items()})
    except (ValueError, TypeError) as exc:
        write_error(code="VALIDATION_ERROR", error=str(exc))
        return 1
    html_fragment = compose_cards_html(args.title, cards)
    fallback = cards_fallback_text(args.title, cards)
    payload = build_openui_payload(
        html_fragment=html_fragment,
        fallback_text=fallback,
        title=args.title,
        output=args.output,
    )
    write_ok(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
