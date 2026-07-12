from __future__ import annotations

"""Human-like timing helpers for bundled ``playwright-browser`` scripts.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._timing
Depends: random, typing

Exports:
    human_pause — random pre-action delay via ``page.wait_for_timeout``.
    human_typing_delay_ms — per-keystroke delay for ``keyboard.type``.
    add_human_arg — register ``--human`` on an ``ArgumentParser``.
"""

import argparse
import random
from typing import Any

DEFAULT_HUMAN_MIN_MS = 250
DEFAULT_HUMAN_MAX_MS = 900
DEFAULT_TYPING_MIN_MS = 35
DEFAULT_TYPING_MAX_MS = 110


async def human_pause(
    page: Any,
    *,
    min_ms: int = DEFAULT_HUMAN_MIN_MS,
    max_ms: int = DEFAULT_HUMAN_MAX_MS,
) -> int:
    """Sleep a random interval to mimic human pacing between actions.

    Args:
        page (Any): Playwright ``Page`` exposing ``wait_for_timeout``.
        min_ms (int): Lower bound inclusive.
        max_ms (int): Upper bound inclusive.

    Returns:
        int: Chosen delay in milliseconds.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(human_pause)
        True
    """
    lo = min(min_ms, max_ms)
    hi = max(min_ms, max_ms)
    delay = random.randint(lo, hi)
    await page.wait_for_timeout(delay)
    return delay


def human_typing_delay_ms(
    *,
    min_ms: int = DEFAULT_TYPING_MIN_MS,
    max_ms: int = DEFAULT_TYPING_MAX_MS,
) -> int:
    """Return a random per-keystroke delay for ``keyboard.type``.

    Args:
        min_ms (int): Lower bound inclusive.
        max_ms (int): Upper bound inclusive.

    Returns:
        int: Delay in milliseconds.

    Examples:
        >>> 35 <= human_typing_delay_ms() <= 110
        True
    """
    lo = min(min_ms, max_ms)
    hi = max(min_ms, max_ms)
    return random.randint(lo, hi)


def add_human_arg(parser: argparse.ArgumentParser) -> None:
    """Register ``--human`` for random pauses and typing delays.

    Args:
        parser (argparse.ArgumentParser): Parser to extend.

    Returns:
        None

    Examples:
        >>> p = argparse.ArgumentParser()
        >>> add_human_arg(p)
        >>> any(action.dest == "human" for action in p._actions)
        True
    """
    parser.add_argument(
        "--human",
        action="store_true",
        help="Random pause before interaction and human-like typing delays.",
    )
