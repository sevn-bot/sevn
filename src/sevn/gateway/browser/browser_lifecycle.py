"""Gateway browser teardown hooks without static ``sevn.skills`` imports.

``session_manager`` is reachable from ``sevn.channels``; import-linter forbids a
transitive channels → skills chain. Browser close helpers therefore load
``sevn.skills.browser_session`` via :func:`importlib.import_module` at call time.

Module: sevn.gateway.browser.browser_lifecycle
Depends: importlib

Exports:
    close_browser_for_rotate — Best-effort browser close after ``/new`` rotate.

Examples:
    >>> close_browser_for_rotate.__name__
    'close_browser_for_rotate'
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


def close_browser_for_rotate(content_root: Path, session_id: str) -> Any:
    """Close the sevn-managed browser for a rotated-away session id.

    Args:
        content_root (Path): Workspace content root holding browser registry.
        session_id (str): Prior ``gateway_sessions.session_id`` being rotated.

    Returns:
        Any: ``CloseBrowserResult`` from ``browser_session.close_browser_session``.

    Examples:
        >>> close_browser_for_rotate.__name__
        'close_browser_for_rotate'
    """
    browser_session = importlib.import_module("sevn.skills.browser_session")
    return browser_session.close_browser_session(content_root, session_id)
