#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — list interactive controls with importance scores.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.list_controls
Depends: sevn.lcm.script_cli

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

import sys
from pathlib import Path

_bootstrap_dir = Path(__file__).resolve().parent / "_lib"
if str(_bootstrap_dir) not in sys.path:
    sys.path.insert(0, str(_bootstrap_dir))
import _bootstrap  # noqa: F401

import argparse
import asyncio
from typing import Any, cast

from _controls import enrich_controls
from _pw_session import add_tab_arg, browser_session, wait_for_page_ready

_LIST_CONTROLS_JS = """
() => {
  const max = 250;
  const q = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="textbox"], [role="combobox"], [role="tab"]';
  const nodes = Array.from(document.querySelectorAll(q)).slice(0, max);
  return nodes.map((el) => {
    const tag = el.tagName.toLowerCase();
    const id = el.id || '';
    const name = el.name || '';
    const type = el.type || '';
    const href = el.href || '';
    const role = el.getAttribute('role') || '';
    const aria = el.getAttribute('aria-label') || '';
    const placeholder = el.placeholder || '';
    const required = !!el.required;
    const disabled = !!el.disabled;
    const lab = el.labels && el.labels.length
      ? (el.labels[0].innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 120)
      : '';
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const visible = rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
    let text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
    let suggest = '';
    if (id && /^[A-Za-z][A-Za-z0-9_-]*$/.test(id)) suggest = '#' + id;
    else if (name && (tag === 'input' || tag === 'select' || tag === 'textarea'))
      suggest = tag + '[name="' + String(name).replace(/"/g, '\\\\"') + '"]';
    else if (placeholder)
      suggest = tag + '[placeholder="' + String(placeholder).replace(/"/g, '\\\\"') + '"]';
    return {
      tag, type, text, id, name, href, role, aria_label: aria,
      placeholder, label: lab, required, disabled, visible, suggest,
    };
  });
}
"""


def _filter_controls(
    rows: list[dict[str, Any]],
    *,
    visible_only: bool,
    forms_only: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if visible_only and not row.get("visible"):
            continue
        tag = str(row.get("tag") or "")
        if forms_only and tag not in {"input", "select", "textarea", "button"}:
            continue
        out.append(row)
    return out


async def main() -> int:
    p = argparse.ArgumentParser(description="List interactive page controls with selector hints.")
    add_tab_arg(p)
    p.add_argument(
        "--visible-only",
        action="store_true",
        help="Omit hidden or zero-size elements.",
    )
    p.add_argument(
        "--forms-only",
        action="store_true",
        help="Keep inputs, selects, textareas, and submit buttons only.",
    )
    args = p.parse_args()

    async with browser_session(tab_target_id=args.tab) as page:
        await wait_for_page_ready(page)
        raw = await page.evaluate(_LIST_CONTROLS_JS)
        rows = raw if isinstance(raw, list) else []
        typed = [r for r in rows if isinstance(r, dict)]
        filtered = _filter_controls(
            typed,
            visible_only=args.visible_only,
            forms_only=args.forms_only,
        )
        controls = enrich_controls(filtered)
    from _output import emit_ok

    emit_ok({"controls": controls, "count": len(controls)})
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
