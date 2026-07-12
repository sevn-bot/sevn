"""Shared helpers for sevn browser recipes: errors, egress, human-handoff.

Module: sevn.browser.recipes.base
Depends: urllib.parse

Exports:
    RecipeError — recipe-level failure raised by site recipes.
    host_allowed — suffix match of a host against an egress allowlist.
    validate_egress — enforce a recipe's egress allowlist on a URL.
    human_required — build a HUMAN_REQUIRED handoff payload (2FA/QR/CAPTCHA).
    recipe_write_allowed — per-recipe write kill-switch (default opt-in, D8).
    require_write_allowed — raise when write ops are disabled for a recipe.

Examples:
    >>> host_allowed("web.telegram.org", allowlist=("telegram.org",))
    True
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class RecipeError(RuntimeError):
    """A site recipe could not complete (login required, egress, handoff, …)."""


def host_allowed(host: str, *, allowlist: tuple[str, ...]) -> bool:
    """Return whether ``host`` equals or is a subdomain of an allowlisted suffix.

    Args:
        host (str): URL hostname.
        allowlist (tuple[str, ...]): Permitted host suffixes.

    Returns:
        bool: ``True`` when the host matches an allowlisted suffix.

    Examples:
        >>> host_allowed("web.telegram.org", allowlist=("telegram.org",))
        True
        >>> host_allowed("evil.example", allowlist=("telegram.org",))
        False
    """
    normalized = (host or "").lower().rstrip(".")
    if not normalized:
        return False
    return any(
        normalized == suffix.lower() or normalized.endswith(f".{suffix.lower()}")
        for suffix in allowlist
    )


def validate_egress(url: str, *, allowlist: tuple[str, ...]) -> str:
    """Validate ``url`` against a recipe egress allowlist.

    Args:
        url (str): Target URL.
        allowlist (tuple[str, ...]): Permitted host suffixes.

    Returns:
        str: The stripped URL when allowed.

    Raises:
        RecipeError: When the scheme/host is invalid or outside the allowlist.

    Examples:
        >>> validate_egress("https://web.telegram.org/k/", allowlist=("telegram.org",))
        'https://web.telegram.org/k/'
    """
    text = (url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"invalid url: {url!r}"
        raise RecipeError(msg)
    if not host_allowed(parsed.hostname or "", allowlist=allowlist):
        msg = f"host {parsed.hostname!r} is outside the recipe egress allowlist (EGRESS_BLOCKED)"
        raise RecipeError(msg)
    return text


def human_required(reason: str, *, screenshot: str | None = None, url: str = "") -> dict[str, Any]:
    """Build a ``HUMAN_REQUIRED`` handoff payload (2FA/QR/CAPTCHA) — no secrets.

    Args:
        reason (str): Short, non-sensitive description of what the operator must do.
        screenshot (str | None): Optional workspace-relative screenshot path.
        url (str): Optional current page URL for context.

    Returns:
        dict[str, Any]: Handoff payload with ``human_required: True``.

    Examples:
        >>> human_required("scan the QR code")["human_required"]
        True
    """
    payload: dict[str, Any] = {"human_required": True, "reason": reason, "code": "HUMAN_REQUIRED"}
    if screenshot:
        payload["screenshot"] = screenshot
    if url:
        payload["url"] = url
    return payload


def recipe_write_allowed(recipe: str, *, browser_tools: dict[str, Any] | None = None) -> bool:
    """Return whether write ops are enabled for ``recipe`` (default off per D8).

    Args:
        recipe (str): Recipe key (``gmail``, ``youtube``, ``social``, …).
        browser_tools (dict[str, Any] | None): ``tools.browser`` section from config.

    Returns:
        bool: ``True`` when ``tools.browser.<recipe>.allow_write`` is truthy.

    Examples:
        >>> recipe_write_allowed("gmail")
        False
        >>> recipe_write_allowed("gmail", browser_tools={"gmail": {"allow_write": True}})
        True
    """
    if not browser_tools:
        return False
    section = browser_tools.get(recipe)
    return bool(isinstance(section, dict) and section.get("allow_write") is True)


def require_write_allowed(recipe: str, *, browser_tools: dict[str, Any] | None = None) -> None:
    """Raise when write ops are disabled for ``recipe``.

    Args:
        recipe (str): Recipe key.
        browser_tools (dict[str, Any] | None): ``tools.browser`` section from config.

    Returns:
        None

    Raises:
        RecipeError: When the per-recipe write kill-switch is off.

    Examples:
        >>> require_write_allowed("gmail")  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        RecipeError: gmail write ops disabled — set tools.browser.gmail.allow_write=true (EGRESS_BLOCKED)
    """
    if not recipe_write_allowed(recipe, browser_tools=browser_tools):
        msg = (
            f"{recipe} write ops disabled — set tools.browser.{recipe}.allow_write=true "
            "(EGRESS_BLOCKED)"
        )
        raise RecipeError(msg)


__all__ = [
    "RecipeError",
    "host_allowed",
    "human_required",
    "recipe_write_allowed",
    "require_write_allowed",
    "validate_egress",
]
