"""sevn-native CDP browser automator (native engine; no Playwright/WebDriver).

A pure-Python async Chrome DevTools Protocol engine that drives host Chrome: one
browser-level WebSocket with flattened ``Target.setAutoAttach`` session routing,
synthetic input events, and recipes for common sites. Reuses the shipped
``sevn.skills.browser_session`` discovery/spawn/registry layer.

Module: sevn.browser
Depends: sevn.browser.cdp

Exports:
    HAS_CDP — whether the optional ``websockets`` dependency is importable.

Examples:
    >>> HAS_CDP in (True, False)
    True
"""

from __future__ import annotations

from sevn.browser.cdp.protocol import HAS_CDP

__all__ = ["HAS_CDP"]
