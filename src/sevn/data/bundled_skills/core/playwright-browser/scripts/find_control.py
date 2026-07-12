#!/usr/bin/env python3
from __future__ import annotations

"""Bundled ``playwright-browser`` skill — find a control by label, placeholder, role, or text.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts.find_control
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

from _controls import suggest_selector
from _pw_session import add_tab_arg, browser_session, wait_for_page_ready


async def _meta_from_locator(loc: Any) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        await loc.first.evaluate(
            """el => {
              const tag = el.tagName.toLowerCase();
              const lab = el.labels && el.labels.length
                ? (el.labels[0].innerText || '').trim().slice(0, 120)
                : '';
              const rect = el.getBoundingClientRect();
              const style = window.getComputedStyle(el);
              const visible = rect.width > 0 && rect.height > 0
                && style.visibility !== 'hidden' && style.display !== 'none';
              return {
                tag,
                type: el.type || '',
                id: el.id || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                aria_label: el.getAttribute('aria-label') || '',
                text: (el.innerText || el.textContent || '').trim().slice(0, 120),
                label: lab,
                required: !!el.required,
                disabled: !!el.disabled,
                visible,
              };
            }""",
        ),
    )


async def _try_locator(page: Any, loc: Any, *, method: str) -> dict[str, Any] | None:
    if await loc.count() == 0:
        return None
    meta = await _meta_from_locator(loc)
    if not meta.get("visible"):
        return None
    suggest = suggest_selector(meta)
    return {
        "found": True,
        "method": method,
        "suggest": suggest,
        **meta,
    }


async def find_control_on_page(
    page: Any,
    *,
    label: str | None = None,
    placeholder: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    """Resolve the first visible control matching the provided hints.

    Args:
        page (Any): Playwright ``Page``.
        label (str | None): Associated label text.
        placeholder (str | None): Input placeholder substring.
        role (str | None): ARIA role (``button``, ``textbox``, ``combobox``, …).
        name (str | None): HTML ``name`` attribute.
        text (str | None): Visible text for buttons/links.

    Returns:
        dict[str, object]: Match metadata or ``{found: false}``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(find_control_on_page)
        True
    """
    strategies: list[tuple[str, Any]] = []
    if label:
        strategies.append(("label", page.get_by_label(label, exact=False)))
    if placeholder:
        strategies.append(("placeholder", page.get_by_placeholder(placeholder, exact=False)))
    if role and text:
        strategies.append(("role", page.get_by_role(role, name=text, exact=False)))
    elif role:
        strategies.append(("role", page.get_by_role(role)))
    if name:
        escaped = name.replace('"', '\\"')
        strategies.append(
            (
                "name",
                page.locator(
                    f'input[name="{escaped}"], textarea[name="{escaped}"], select[name="{escaped}"]'
                ),
            ),
        )
    if text and not role:
        strategies.append(("text", page.get_by_text(text, exact=False)))

    for method, loc in strategies:
        hit = await _try_locator(page, loc, method=method)
        if hit is not None:
            return hit
    return {"found": False}


async def main() -> int:
    p = argparse.ArgumentParser(description="Find a visible control and return a selector hint.")
    add_tab_arg(p)
    p.add_argument("--label", default="", help="Associated label text")
    p.add_argument("--placeholder", default="", help="Input placeholder substring")
    p.add_argument("--role", default="", help="ARIA role (button, textbox, combobox, …)")
    p.add_argument("--name", default="", help="HTML name attribute")
    p.add_argument("--text", default="", help="Visible text (buttons/links)")
    args = p.parse_args()
    if not any(
        [
            args.label.strip(),
            args.placeholder.strip(),
            args.role.strip(),
            args.name.strip(),
            args.text.strip(),
        ],
    ):
        from _output import emit_error

        emit_error(
            "VALIDATION",
            "Provide at least one of --label, --placeholder, --role, --name, --text",
        )
        return 2

    async with browser_session(tab_target_id=args.tab) as page:
        await wait_for_page_ready(page)
        result = await find_control_on_page(
            page,
            label=args.label.strip() or None,
            placeholder=args.placeholder.strip() or None,
            role=args.role.strip() or None,
            name=args.name.strip() or None,
            text=args.text.strip() or None,
        )
    from _output import emit_ok

    emit_ok(result)
    return 0


def _entry() -> int:
    from _output import main_guard

    @main_guard  # type: ignore[untyped-decorator]
    def _run() -> int:
        return asyncio.run(main())

    return cast("int", _run())


if __name__ == "__main__":
    raise SystemExit(_entry())
