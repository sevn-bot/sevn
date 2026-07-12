"""Live ``/config`` keyboard snapshot for docs gates and the about-site build.

Module: scripts.telegram_menu_snapshot
Depends: dataclasses, sevn.config.workspace_config, sevn.gateway.menu

Exports:
    LiveButton — one inline button from a rendered keyboard.
    LiveSection — one ``/config`` section tile and its action buttons.
    collect_live_config_menu — snapshot all sections from code.
    default_docs_workspace — workspace fixture for documentation gates.

Examples:
    >>> menu = collect_live_config_menu()
    >>> "session" in menu
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.telegram_menu_catalog import is_final_action_button

from sevn.config.workspace_config import WorkspaceConfig

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "LiveButton",
    "LiveSection",
    "collect_live_config_menu",
    "default_docs_workspace",
]

_NAV_SKIP_TEXT = frozenset({"◀ Back", "🏠 Home", "❌ Close"})


@dataclass(frozen=True)
class LiveButton:
    """One action button from a rendered ``/config`` section keyboard."""

    label: str
    callback_data: str
    is_final: bool


@dataclass(frozen=True)
class LiveSection:
    """One root ``/config`` section and its documented action buttons."""

    section_id: str
    tile_label: str
    section_callback: str
    buttons: tuple[LiveButton, ...]


def default_docs_workspace() -> WorkspaceConfig:
    """Workspace used when building menu snapshots for documentation gates.

    Returns:
        WorkspaceConfig: Schema v1 with a Mission Control URL so URL rows render.

    Examples:
        >>> ws = default_docs_workspace()
        >>> ws.web_ui is not None
        True
    """
    return WorkspaceConfig.minimal(
        web_ui={"url": "https://app.example/mission-control"},
    )


def collect_live_config_menu(
    workspace: WorkspaceConfig | None = None,
    *,
    content_root: Path | None = None,
) -> dict[str, LiveSection]:
    """Snapshot live ``/config`` section keyboards from gateway builders.

    Args:
        workspace (WorkspaceConfig | None): Parsed workspace; defaults to
            :func:`default_docs_workspace`.
        content_root (Path | None): Unused; reserved for shortcuts parity with
            :mod:`scripts.check_telegram_menu`.

    Returns:
        dict[str, LiveSection]: Section id → live section snapshot.

    Examples:
        >>> menu = collect_live_config_menu()
        >>> menu["session"].buttons
        ()
    """
    _ = content_root
    from sevn.gateway.menu import _CONFIG_ROOT_TILES, build_config_menu_keyboard

    ws = workspace if workspace is not None else default_docs_workspace()
    out: dict[str, LiveSection] = {}
    for tile_label, section_id, section_cb in _CONFIG_ROOT_TILES:
        kb = build_config_menu_keyboard(ws, section=section_id)  # type: ignore[arg-type]
        buttons: list[LiveButton] = []
        for row in kb.get("inline_keyboard", []):
            for btn in row:
                text = str(btn.get("text", ""))
                cb = btn.get("callback_data")
                if not text or not isinstance(cb, str):
                    continue
                if cb.startswith(("cfg:nav:", "cfg:section:help")):
                    continue
                if text in _NAV_SKIP_TEXT:
                    continue
                clean = text.lstrip("🚧📋🔒 ").strip()
                buttons.append(
                    LiveButton(
                        label=clean,
                        callback_data=cb,
                        is_final=is_final_action_button(cb),
                    ),
                )
        out[section_id] = LiveSection(
            section_id=section_id,
            tile_label=tile_label,
            section_callback=section_cb,
            buttons=tuple(buttons),
        )
    return out
