"""Async Chrome DevTools Protocol transport for the sevn browser engine.

Module: sevn.browser.cdp
Depends: sevn.browser.cdp.connection, sevn.browser.cdp.protocol, sevn.browser.cdp.session

Exports:
    CDPConnection — one browser-level WebSocket with id/Future correlation + event bus.
    CDPSession — a ``sessionId``-bound view that routes commands to one target.
    CDPError — protocol-level error reply wrapper.
    HAS_CDP — whether ``websockets`` is importable.

Examples:
    >>> from sevn.browser.cdp import HAS_CDP
    >>> HAS_CDP in (True, False)
    True
"""

from __future__ import annotations

from sevn.browser.cdp.connection import CDPConnection
from sevn.browser.cdp.protocol import HAS_CDP, CDPError
from sevn.browser.cdp.session import CDPSession

__all__ = ["HAS_CDP", "CDPConnection", "CDPError", "CDPSession"]
