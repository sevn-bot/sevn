"""Telegram ``/config`` eight-group ``rich_help_panel`` SSOT for the root CLI.

Module: sevn.cli.help.panels
Depends: typer

Exports:
    panel_for — resolve help panel for a root command.
    apply_root_panels — assign panels on root Typer command/group metadata.
    iter_root_click_commands — introspect root command panels.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer

# Mirrors ``_CONFIG_ROOT_TILES`` group labels in ``menu.py``.
PANEL_ORDER: tuple[str, ...] = (
    "Chat",
    "Agent",
    "Skills & Tools",
    "Memory",
    "Access",
    "Health",
    "Deployment",
    "Help",
)

ROOT_COMMAND_PANELS: dict[str, str] = {
    "about-docs": "Help",
    "acp": "Chat",
    "agent": "Agent",
    "browser": "Skills & Tools",
    "capabilities": "Health",
    "channels": "Chat",
    "completion": "Help",
    "config": "Deployment",
    "dashboard": "Deployment",
    "db": "Health",
    "deploy": "Deployment",
    "doctor": "Health",
    "export-secrets": "Access",
    "gateway": "Deployment",
    "gh": "Skills & Tools",
    "guide": "Help",
    "gui": "Deployment",
    "improve": "Agent",
    "logs": "Health",
    "memory": "Memory",
    "message": "Chat",
    "migrate": "Deployment",
    "models": "Agent",
    "onboard": "Deployment",
    "openwiki": "Memory",
    "pairing": "Access",
    "providers": "Access",
    "proxy": "Deployment",
    "readme": "Help",
    "remove": "Deployment",
    "secrets": "Access",
    "second-brain": "Memory",
    "sessions": "Chat",
    "shell-history": "Help",
    "skills": "Skills & Tools",
    "subagents": "Agent",
    "sync": "Deployment",
    "tools": "Skills & Tools",
    "traces": "Health",
    "tracing": "Health",
    "tunnel": "Deployment",
    "turn-bundle": "Health",
    "unboard": "Deployment",
    "uninstall": "Deployment",
    "update": "Deployment",
    "upgrade": "Deployment",
    "usage": "Health",
    "version": "Help",
    "voice": "Chat",
}


def panel_for(command: str) -> str:
    """Return the Mission Control help panel for a root command name.

    Args:
        command (str): Root Typer command or group name (e.g. ``doctor``).

    Returns:
        str: Panel label from ``PANEL_ORDER``.

    Examples:
        >>> panel_for("doctor")
        'Health'
        >>> panel_for("sessions")
        'Chat'
        >>> panel_for("unknown-cmd")
        'Help'
    """
    return ROOT_COMMAND_PANELS.get(command, "Help")


def _panel_value(raw: object, *, command: str) -> str:
    """Normalize a Typer ``rich_help_panel`` value to a panel label string.

    Args:
        raw (object): ``TyperInfo.rich_help_panel`` value.
        command (str): Root command name for SSOT fallback.

    Returns:
        str: Panel label.

    Examples:
        >>> _panel_value("Health", command="doctor")
        'Health'
        >>> _panel_value(None, command="doctor")
        'Health'
    """
    if isinstance(raw, str) and raw:
        return raw
    return panel_for(command)


def apply_root_panels(app: typer.Typer) -> None:
    """Assign ``rich_help_panel`` on every root Typer command and group.

    Args:
        app (typer.Typer): Fully registered root CLI application.

    Examples:
        >>> import typer
        >>> apply_root_panels(typer.Typer())
    """
    for cmd_info in app.registered_commands:
        name = cmd_info.name or ""
        cmd_info.rich_help_panel = panel_for(name)
    for group_info in app.registered_groups:
        name = group_info.name or ""
        group_info.rich_help_panel = panel_for(name)


def iter_root_click_commands(app: typer.Typer) -> Iterator[tuple[str, str]]:
    """Yield ``(command_name, rich_help_panel)`` for each root Typer registration.

    Args:
        app (typer.Typer): Root CLI application (panels applied).

    Yields:
        tuple[str, str]: Command name and panel label.

    Returns:
        Iterator[tuple[str, str]]: Root command names with panel labels.

    Examples:
        >>> import typer
        >>> list(iter_root_click_commands(typer.Typer()))
        []
    """
    for cmd_info in sorted(app.registered_commands, key=lambda item: item.name or ""):
        name = cmd_info.name or ""
        yield name, _panel_value(cmd_info.rich_help_panel, command=name)
    for group_info in sorted(app.registered_groups, key=lambda item: item.name or ""):
        name = group_info.name or ""
        yield name, _panel_value(group_info.rich_help_panel, command=name)
