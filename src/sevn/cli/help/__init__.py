"""CLI help panels and narrative guides (`specs/23-cli.md`, D11).

Module: sevn.cli.help
Depends: sevn.cli.help.guide, sevn.cli.help.panels

Exports:
    apply_root_panels — assign Mission Control ``rich_help_panel`` groups on the root app.
    list_guide_topics — bundled ``sevn guide`` topic slugs.
    load_guide — load a guide markdown body by topic slug.
    panel_for — resolve the help panel name for a root command.
"""

from __future__ import annotations

from sevn.cli.help.guide import list_guide_topics, load_guide
from sevn.cli.help.panels import PANEL_ORDER, apply_root_panels, panel_for

__all__ = [
    "PANEL_ORDER",
    "apply_root_panels",
    "list_guide_topics",
    "load_guide",
    "panel_for",
]
