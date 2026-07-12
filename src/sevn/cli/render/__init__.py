"""Rich/Textual rendering helpers for operator CLI output (`specs/23-cli.md` §7).

Module: sevn.cli.render
Depends: sevn.cli.render.console, sevn.cli.render.sections, sevn.cli.render.tables,
    sevn.cli.render.tree

Exports:
    configure_render — set JSON/plain/color gating for the current CLI invocation.
    get_console — singleton Rich ``Console`` when ``is_rich()`` is True.
    is_rich — whether formatted output may use Rich/ANSI.
    plain_echo — always-plain stdout/stderr write.
    section — section banner for doctor-style reports.
    check_ok — passing severity row.
    check_warn — warning severity row.
    check_fail — failing severity row.
    check_info — informational follow-up row.
    render_table — Rich table or plain aligned columns.
    render_span_tree — nested span tree for traces (W6).
"""

from __future__ import annotations

from sevn.cli.render.console import configure_render, get_console, is_rich, plain_echo
from sevn.cli.render.sections import check_fail, check_info, check_ok, check_warn, section
from sevn.cli.render.tables import render_table
from sevn.cli.render.tree import render_span_tree

__all__ = [
    "check_fail",
    "check_info",
    "check_ok",
    "check_warn",
    "configure_render",
    "get_console",
    "is_rich",
    "plain_echo",
    "render_span_tree",
    "render_table",
    "section",
]
