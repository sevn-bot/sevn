#!/usr/bin/env python3
"""Gate: ``Telegram Menu.html`` structure matches live ``/config`` keyboards.

Compares rendered keyboards from :mod:`sevn.gateway.menu.menu` to the developer
catalog in ``about-sevn.bot/Telegram Menu.html``. With ``--scaffold``, inserts
WIP/TODO ``btn(...)`` and section stubs for missing rows (never overwrites prose).

Module: scripts.check_telegram_menu_docs
Depends: argparse, json, pathlib, re, sys

Exports:
    DocGap — one structural mismatch record.
    build_docs_gap_report — machine-readable drift snapshot.
    collect_doc_gaps — compute missing sections, buttons, and root tiles.
    main — CLI entry.
    scaffold_dev_catalog — write stubs into dev HTML.

Examples:
    >>> from pathlib import Path
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.telegram_menu_catalog import (  # noqa: E402
    DEV_TELEGRAM_HTML,
    catalog_has_live_button,
    dev_norm_for_callback,
    norm_menu_label,
    parse_dev_root_tiles,
    parse_dev_telegram_menu_catalog,
    sections_block_bounds,
)
from scripts.telegram_menu_snapshot import (  # noqa: E402
    LiveButton,
    LiveSection,
    collect_live_config_menu,
)

REPO = _REPO
DOCS_GAP_REPORT = REPO / "reports" / "telegram-menu-docs-gap.json"

__all__ = [
    "DocGap",
    "build_docs_gap_report",
    "collect_doc_gaps",
    "main",
    "scaffold_dev_catalog",
]


@dataclass(frozen=True)
class DocGap:
    """One structural mismatch between live menu and dev catalog."""

    kind: str
    section_id: str
    detail: str
    callback_data: str | None = None
    label: str | None = None


def _registry_notes(callback_data: str) -> str | None:
    """Return registry ``notes`` for one callback when matched.

    Args:
        callback_data (str): Live inline callback payload.

    Returns:
        str | None: Spec notes when the registry matches.

    Examples:
        >>> _registry_notes("cfg:nav:home") is None or isinstance(_registry_notes("cfg:nav:home"), str)
        True
    """
    from sevn.gateway.menu.menu_registry import match_menu_button_spec

    spec = match_menu_button_spec(callback_data)
    if spec is None or not spec.notes:
        return None
    return spec.notes.strip()


def _stable_catalog_label(btn: LiveButton) -> str:
    """Choose a catalog ``btn("...")`` label from a live button.

    Args:
        btn (LiveButton): Live keyboard row.

    Returns:
        str: Stable label without live-only suffix noise.

    Examples:
        >>> _stable_catalog_label(LiveButton("Regen ✅", "cfg:x", True))
        'Regen'
    """
    norm = dev_norm_for_callback(btn.callback_data)
    if norm:
        if norm == "dm policy cycle":
            return "DM policy cycle"
        if norm == "notify policy cycle":
            return "Notify policy cycle"
        if norm == "λ-rlm enabled":
            return "λ-RLM enabled"
        return " ".join(part.capitalize() for part in norm.split())
    text = btn.label.strip().lstrip("🚧📋🔒 ")
    text = re.sub(r"\s*✅\s*$", "", text)
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    text = re.sub(r"^[^\w]+", "", text, flags=re.UNICODE).strip()
    return text or btn.label


def collect_doc_gaps(
    *,
    html_path: Path | None = None,
    live: dict[str, LiveSection] | None = None,
) -> tuple[list[DocGap], list[DocGap]]:
    """Compare live keyboards to the developer catalog.

    Args:
        html_path (Path | None): Dev catalog path; defaults to :data:`DEV_TELEGRAM_HTML`.
        live (dict[str, LiveSection] | None): Live snapshot; built when omitted.

    Returns:
        tuple[list[DocGap], list[DocGap]]: Hard violations and orphan warnings.

    Examples:
        >>> hard, _warn = collect_doc_gaps()
        >>> isinstance(hard, list)
        True
    """
    path = html_path or DEV_TELEGRAM_HTML
    catalog = parse_dev_telegram_menu_catalog(path, sanitize=False)
    root_tiles = {sid for sid, _ in parse_dev_root_tiles(path)}
    menu = live if live is not None else collect_live_config_menu()

    hard: list[DocGap] = []
    warnings: list[DocGap] = []

    for section_id, live_sec in menu.items():
        if section_id not in root_tiles:
            hard.append(
                DocGap(
                    kind="missing_root_tile",
                    section_id=section_id,
                    detail=f"ROOT_TILES missing [{section_id!r}, {live_sec.tile_label!r}]",
                ),
            )
        dev_sec = catalog.get(section_id)
        if dev_sec is None:
            hard.append(
                DocGap(
                    kind="missing_section",
                    section_id=section_id,
                    detail=f"SECTIONS.{section_id} block missing",
                ),
            )
            continue
        dev_buttons = list(dev_sec.get("buttons") or [])
        for btn in live_sec.buttons:
            if not catalog_has_live_button(
                dev_buttons,
                btn.label,
                callback_data=btn.callback_data,
            ):
                hard.append(
                    DocGap(
                        kind="missing_button",
                        section_id=section_id,
                        detail=f"no btn() for {btn.label!r}",
                        callback_data=btn.callback_data,
                        label=btn.label,
                    ),
                )
        live_norms: set[str] = set()
        for b in live_sec.buttons:
            live_norms.add(norm_menu_label(b.label))
            cb_norm = dev_norm_for_callback(b.callback_data)
            if cb_norm:
                live_norms.add(cb_norm)
        for row in dev_buttons:
            norm = str(row.get("norm", ""))
            if (
                norm
                and norm not in live_norms
                and not any(norm in ln or ln in norm for ln in live_norms)
            ):
                warnings.append(
                    DocGap(
                        kind="orphan_catalog_button",
                        section_id=section_id,
                        detail=f"catalog btn {row.get('label')!r} has no live keyboard row",
                        label=str(row.get("label")),
                    ),
                )

    catalog_ids = set(catalog)
    for sid in catalog_ids - set(menu):
        warnings.append(
            DocGap(
                kind="orphan_catalog_section",
                section_id=sid,
                detail=f"SECTIONS.{sid} not in _CONFIG_ROOT_TILES",
            ),
        )

    return hard, warnings


def _escape_js(s: str) -> str:
    """Escape a string for embedding in a JS ``btn(...)`` literal.

    Args:
        s (str): Plain text.

    Returns:
        str: Escaped text safe inside double quotes.

    Examples:
        >>> _escape_js('say "hi"')
        'say \\"hi\\"'
    """
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _section_stub(section_id: str, live_sec: LiveSection) -> str:
    """Format a new ``SECTIONS.<id>`` block with TODO prose.

    Args:
        section_id (str): Config section slug.
        live_sec (LiveSection): Live tile metadata.

    Returns:
        str: JavaScript object snippet to insert before ``};``.

    Examples:
        >>> "TODO: section short" in _section_stub("logs", LiveSection("logs", "📜 Logs", "cfg:section:logs", ()))
        True
    """
    title = live_sec.tile_label.split(" ", 1)[-1] if " " in live_sec.tile_label else section_id
    return (
        f"      {section_id}: {{\n"
        f'        title: "{_escape_js(title)}",\n'
        '        status: "WIP",\n'
        '        short: "TODO: section short",\n'
        '        long: "TODO: section long",\n'
        "        buttons: [\n"
        "        ],\n"
        "      },\n"
    )


def _button_stub(btn: LiveButton) -> str:
    """Format one ``btn(...)`` stub with TODO prose.

    Args:
        btn (LiveButton): Live keyboard row.

    Returns:
        str: JavaScript ``btn`` call snippet.

    Examples:
        >>> "TODO: short" in _button_stub(LiveButton("Regen", "cfg:x", True))
        True
    """
    label = _stable_catalog_label(btn)
    notes = _registry_notes(btn.callback_data)
    short = f"TODO: short ({notes})" if notes else "TODO: short"
    long_text = f"TODO: long ({btn.callback_data})"
    return (
        f'          btn("{_escape_js(label)}", "WIP",\n'
        f'            "{_escape_js(short)}",\n'
        f'            "{_escape_js(long_text)}"),\n'
    )


def _insert_root_tile(text: str, section_id: str, tile_label: str) -> str:
    """Append one ``ROOT_TILES`` entry when missing.

    Args:
        text (str): Full dev HTML file.
        section_id (str): Section slug.
        tile_label (str): Visible root tile label.

    Returns:
        str: Updated HTML.

    Examples:
        >>> html = 'const ROOT_TILES = [\\n      ["session", "S"],\\n    ];'
        >>> '["logs",' in _insert_root_tile(html, "logs", "📜 Logs")
        True
    """
    marker = "const ROOT_TILES = ["
    start = text.find(marker)
    if start < 0:
        return text
    close = text.find("\n    ];", start)
    if close < 0:
        return text
    block = text[start:close]
    if f'["{section_id}",' in block:
        return text
    insert = f'\n      ["{section_id}", "{tile_label}"],'
    return text[:close] + insert + text[close:]


def _append_button_to_section(text: str, section_id: str, btn: LiveButton) -> str:
    """Append one ``btn(...)`` stub inside an existing section.

    Args:
        text (str): Full dev HTML file.
        section_id (str): Section slug.
        btn (LiveButton): Live keyboard row to document.

    Returns:
        str: Updated HTML when a new stub was added; otherwise unchanged.

    Examples:
        >>> html = 'logs: { title: "L", status: "WIP", short: "s", long: "l", buttons: [ ], },'
        >>> _append_button_to_section(html, "logs", LiveButton("X", "cfg:logs:x", True))
        'logs: { title: "L", status: "WIP", short: "s", long: "l", buttons: [ ], },'
    """
    pattern = re.compile(
        rf"(\s+{re.escape(section_id)}:\s*\{{[\s\S]*?buttons:\s*\[)([\s\S]*?)(\n\s+\],)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return text
    body = match.group(2)
    stub = _button_stub(btn)
    if stub.strip() in body:
        return text
    new_body = body.rstrip() + "\n" + stub
    return text[: match.start(2)] + new_body + text[match.end(2) :]


def scaffold_dev_catalog(
    *,
    html_path: Path | None = None,
    live: dict[str, LiveSection] | None = None,
) -> int:
    """Insert WIP/TODO stubs into dev HTML for structural gaps.

    Args:
        html_path (Path | None): Dev catalog path; defaults to :data:`DEV_TELEGRAM_HTML`.
        live (dict[str, LiveSection] | None): Live snapshot; built when omitted.

    Returns:
        int: Number of stubs inserted.

    Examples:
        >>> scaffold_dev_catalog(html_path=Path("/nonexistent"))  # doctest: +SKIP
        0
    """
    path = html_path or DEV_TELEGRAM_HTML
    if not path.is_file():
        return 0
    hard, _ = collect_doc_gaps(html_path=path, live=live)
    if not hard:
        return 0
    text = path.read_text(encoding="utf-8")
    inserted = 0
    menu = live if live is not None else collect_live_config_menu()

    missing_sections = [g for g in hard if g.kind == "missing_section"]
    for gap in missing_sections:
        live_sec = menu.get(gap.section_id)
        if live_sec is None:
            continue
        bounds = sections_block_bounds(text)
        if bounds is None:
            continue
        _, end = bounds
        stub = _section_stub(gap.section_id, live_sec)
        if f"{gap.section_id}:" not in text:
            text = text[:end] + stub + text[end:]
            inserted += 1
            bounds = sections_block_bounds(text)
            if bounds is None:
                break
            _, end = bounds

    for gap in hard:
        if gap.kind == "missing_root_tile":
            live_sec = menu.get(gap.section_id)
            if live_sec is None:
                continue
            new_text = _insert_root_tile(text, gap.section_id, live_sec.tile_label)
            if new_text != text:
                text = new_text
                inserted += 1

    if inserted:
        path.write_text(text, encoding="utf-8")

    hard, _ = collect_doc_gaps(html_path=path, live=live)
    text = path.read_text(encoding="utf-8")
    for gap in hard:
        if gap.kind != "missing_button" or not gap.callback_data:
            continue
        live_sec = menu.get(gap.section_id)
        if live_sec is None:
            continue
        btn = next(
            (b for b in live_sec.buttons if b.callback_data == gap.callback_data),
            None,
        )
        if btn is None:
            continue
        new_text = _append_button_to_section(text, gap.section_id, btn)
        if new_text != text:
            text = new_text
            inserted += 1

    if inserted:
        path.write_text(text, encoding="utf-8")
    return inserted


def build_docs_gap_report(
    *,
    html_path: Path | None = None,
) -> dict[str, Any]:
    """Build machine-readable docs drift snapshot.

    Args:
        html_path (Path | None): Dev catalog path; defaults to :data:`DEV_TELEGRAM_HTML`.

    Returns:
        dict[str, Any]: Report payload for ``reports/telegram-menu-docs-gap.json``.

    Examples:
        >>> report = build_docs_gap_report()
        >>> "violations" in report
        True
    """
    hard, warnings = collect_doc_gaps(html_path=html_path)
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "catalog_path": str((html_path or DEV_TELEGRAM_HTML).relative_to(REPO)),
        "hard_violation_count": len(hard),
        "warning_count": len(warnings),
        "violations": [asdict(g) for g in hard],
        "warnings": [asdict(g) for g in warnings],
    }


def main(argv: list[str] | None = None) -> int:
    """Run docs drift check and optional scaffold.

    Args:
        argv (list[str] | None): CLI args; ``--scaffold`` writes stubs.

    Returns:
        int: ``0`` when no hard violations remain after optional scaffold.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description="Telegram Menu.html structure sync gate")
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Insert WIP/TODO stubs for missing sections, buttons, and ROOT_TILES",
    )
    args = parser.parse_args(argv)

    if args.scaffold:
        n = scaffold_dev_catalog()
        if n:
            print(f"telegram-menu-docs-scaffold: inserted {n} stub(s)", file=sys.stderr)

    report = build_docs_gap_report()
    DOCS_GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DOCS_GAP_REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    hard = int(report["hard_violation_count"])
    warn = int(report["warning_count"])
    print(
        f"telegram-menu-docs-check: {hard} violation(s), {warn} warning(s) "
        f"-> {DOCS_GAP_REPORT.relative_to(REPO)}",
        file=sys.stderr,
    )
    for gap in report["violations"]:
        print(
            f"  [{gap['kind']}] {gap['section_id']}: {gap['detail']}"
            + (f" ({gap['callback_data']})" if gap.get("callback_data") else ""),
            file=sys.stderr,
        )
    if hard:
        print("Run: make telegram-menu-docs-scaffold", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
