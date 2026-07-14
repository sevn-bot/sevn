"""Branding helpers for Telegram ``/config`` tiles (`styles/sevn/style/logos`).

Module: sevn.gateway.menu.menu_branding
Depends: sevn.ui.style

Telegram inline keyboard buttons are text-only; the sevn.bot mark lives in
``logo-mark.svg`` (ASCII-style 7 mark on dark). Root tiles use the wordmark label.

Exports:
    config_sevn_bot_section_title — caption heading for the sevn.bot section.

Examples:
    >>> SEVN_BOT_ROOT_TILE_LABEL
    'sevn.bot'
    >>> SEVN_BOT_LOGO_REL.endswith('.svg')
    True
"""

from __future__ import annotations

SEVN_BOT_LOGO_REL = "logos/logo-mark.svg"
SEVN_BOT_ROOT_TILE_LABEL = "sevn.bot"


def config_sevn_bot_section_title() -> str:
    """Return the caption title for the sevn.bot ``/config`` section.

    Returns:
        str: Plain-text section heading.

    Examples:
        >>> config_sevn_bot_section_title()
        'sevn.bot'
    """
    return "sevn.bot"


__all__ = [
    "SEVN_BOT_LOGO_REL",
    "SEVN_BOT_ROOT_TILE_LABEL",
    "config_sevn_bot_section_title",
]
