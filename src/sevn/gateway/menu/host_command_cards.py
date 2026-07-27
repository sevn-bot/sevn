"""Copy-paste host-only command cards for Telegram /config (D17).

Module: sevn.gateway.menu.host_command_cards
Depends: html, pathlib, sevn.config.sevn_repo, sevn.config.workspace_config

Exports:
    has_bound_source_checkout — whether a sevn.bot git checkout is bound.
    render_host_command_card — HTML card with exact shell command (no subprocess).
"""

from __future__ import annotations

import html
from pathlib import Path

from sevn.config.my_sevn import resolve_my_sevn_repo_path
from sevn.config.workspace_config import WorkspaceConfig

_HOST_CARD_DEFAULT_WHY = "Run this in your shell — the gateway cannot execute it here."


def has_bound_source_checkout(
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
) -> bool:
    """Return whether a sevn.bot source checkout is bound to this install.

    Used to hide Help > Developer when no checkout is configured (W8.3).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        content_root (Path | None): Operator workspace content root.

    Returns:
        bool: ``True`` when ``my_sevn.repo_path`` resolves to a valid checkout.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> has_bound_source_checkout(WorkspaceConfig.minimal(), None)
        False
    """
    _ = content_root
    checkout = resolve_my_sevn_repo_path(workspace)
    return checkout is not None and checkout.is_dir()


async def render_host_command_card(command: str, *, why: str | None = None) -> str:
    """Build an HTML Telegram message with a copy-paste ``<pre>`` block (D17).

    Never invokes a subprocess — the card is the entire action surface.

    Args:
        command (str): Exact shell command the operator should paste.
        why (str | None): One-sentence reason; defaults to the standard host-only copy.

    Returns:
        str: HTML body suitable for ``parse_mode=HTML``.

    Examples:
        >>> import asyncio
        >>> card = asyncio.run(render_host_command_card("sevn onboard", why="Host only."))
        >>> "<pre>" in card and "sevn onboard" in card
        True
    """
    reason = (why or _HOST_CARD_DEFAULT_WHY).strip()
    escaped_cmd = html.escape(command.strip(), quote=False)
    escaped_why = html.escape(reason, quote=False)
    return f"{escaped_why}\n\n<pre>{escaped_cmd}</pre>"


__all__ = ["has_bound_source_checkout", "render_host_command_card"]
