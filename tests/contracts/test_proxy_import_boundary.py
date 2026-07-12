"""Import-layer checks for ``sevn.proxy`` (``specs/01-system-overview.md`` §2.3).

The egress proxy must remain a leaf: it does not import ``agent``, ``gateway``,
or ``channels`` packages.
"""

from __future__ import annotations

import importlib
import sys


def test_proxy_app_does_not_load_agent_gateway_or_channels() -> None:
    """``sevn.proxy.app`` stays isolated from agent/gateway/channel graphs."""
    before = set(sys.modules)
    importlib.import_module("sevn.proxy.app")

    loaded = {m for m in sys.modules if m not in before}
    forbidden = {
        m for m in loaded if m.startswith(("sevn.agent.", "sevn.gateway.", "sevn.channels."))
    }
    assert not forbidden, f"unexpected imports: {sorted(forbidden)}"
