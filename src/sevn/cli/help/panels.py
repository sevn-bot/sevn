"""Mission Control eight-group ``rich_help_panel`` SSOT for the root CLI (D11).

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

# Mirrors ``sevn.ui.dashboard.tab_registry.DASHBOARD_GROUPS`` group labels.
PANEL_ORDER: tuple[str, ...] = (
    "Core",
    "Observability",
    "Agent",
    "Knowledge",
    "Self-improve",
    "Evolution",
    "Ops",
    "Surfaces",
)

ROOT_COMMAND_PANELS: dict[str, str] = {
    "about-docs": "Ops",
    "agent": "Core",
    "channels": "Observability",
    "completion": "Ops",
    "config": "Ops",
    "dashboard": "Core",
    "deploy": "Ops",
    "doctor": "Core",
    "export-secrets": "Ops",
    "gateway": "Ops",
    "gh": "Evolution",
    "guide": "Ops",
    "gui": "Surfaces",
    "improve": "Self-improve",
    "logs": "Observability",
    "memory": "Knowledge",
    "message": "Core",
    "models": "Agent",
    "migrate": "Ops",
    "onboard": "Surfaces",
    "openwiki": "Agent",
    "pairing": "Ops",
    "providers": "Ops",
    "proxy": "Ops",
    "readme": "Ops",
    "remove": "Ops",
    "secrets": "Ops",
    "second-brain": "Knowledge",
    "sessions": "Core",
    "shell-history": "Ops",
    "skills": "Agent",
    "sync": "Ops",
    "tools": "Agent",
    "telegram-test": "Surfaces",
    "traces": "Observability",
    "tracing": "Observability",
    "tunnel": "Ops",
    "turn-bundle": "Observability",
    "unboard": "Ops",
    "uninstall": "Ops",
    "update": "Ops",
    "upgrade": "Ops",
    "usage": "Observability",
    "version": "Ops",
    "voice": "Agent",
}


def panel_for(command: str) -> str:
    """Return the Mission Control help panel for a root command name.

    Args:
        command (str): Root Typer command or group name (e.g. ``doctor``).

    Returns:
        str: Panel label from ``PANEL_ORDER``.

    Examples:
        >>> panel_for("doctor")
        'Core'
        >>> panel_for("logs")
        'Observability'
        >>> panel_for("unknown-cmd")
        'Ops'
    """
    return ROOT_COMMAND_PANELS.get(command, "Ops")


def _panel_value(raw: object, *, command: str) -> str:
    """Normalize a Typer ``rich_help_panel`` value to a panel label string.

    Args:
        raw (object): ``TyperInfo.rich_help_panel`` value.
        command (str): Root command name for SSOT fallback.

    Returns:
        str: Panel label.

    Examples:
        >>> _panel_value("Core", command="doctor")
        'Core'
        >>> _panel_value(None, command="doctor")
        'Core'
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
