from __future__ import annotations

"""Shared interaction helpers for bundled ``playwright-browser`` scripts.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._interact
Depends: _timing

Exports:
    prepare_element — scroll into view and optional human pause.
    human_click — click with optional human pacing.
    human_fill — fill or type with optional human pacing.
"""

from typing import Any

from _timing import human_pause, human_typing_delay_ms


async def prepare_element(
    page: Any,
    selector: str,
    *,
    human: bool = False,
) -> Any:
    """Scroll ``selector`` into view and optionally pause before interaction.

    Args:
        page (Any): Playwright ``Page``.
        selector (str): CSS selector for the target element.
        human (bool): When ``True``, random pre-action pause.

    Returns:
        Any: Playwright ``Locator`` (``.first``).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(prepare_element)
        True
    """
    loc = page.locator(selector).first
    await loc.scroll_into_view_if_needed(timeout=30_000)
    if human:
        await human_pause(page)
    return loc


async def human_click(
    page: Any,
    selector: str,
    *,
    human: bool = False,
) -> None:
    """Click ``selector`` after scroll-into-view and optional human pause.

    Args:
        page (Any): Playwright ``Page``.
        selector (str): CSS selector.
        human (bool): Random pre/post click pauses when ``True``.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(human_click)
        True
    """
    await prepare_element(page, selector, human=human)
    await page.click(selector, timeout=30_000)
    if human:
        await human_pause(page, min_ms=120, max_ms=350)


async def human_fill(
    page: Any,
    selector: str,
    text: str,
    *,
    human: bool = False,
) -> None:
    """Fill or type into ``selector`` with optional human-like keystrokes.

    Args:
        page (Any): Playwright ``Page``.
        selector (str): CSS selector.
        text (str): Value to enter.
        human (bool): Type with random per-key delay instead of instant fill.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(human_fill)
        True
    """
    loc = await prepare_element(page, selector, human=human)
    if human:
        await loc.click(timeout=30_000)
        await page.keyboard.type(text, delay=human_typing_delay_ms())
    else:
        await loc.fill(text, timeout=30_000)
