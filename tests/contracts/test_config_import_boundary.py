"""Import-layer checks for ``sevn.config`` (``specs/01-system-overview.md`` §2.3).

Config loading must stay import-light: it does not pull ``gateway``, ``channels``,
or ``agent`` trees when importing the public loader surface.
"""

from __future__ import annotations

import importlib
import sys


def test_config_loader_does_not_load_agent_gateway_or_channels() -> None:
    """``sevn.config.loader`` stays off the agent/gateway/channel graphs."""
    before = set(sys.modules)
    importlib.import_module("sevn.config.loader")

    loaded = {m for m in sys.modules if m not in before}
    forbidden = {
        m for m in loaded if m.startswith(("sevn.agent.", "sevn.gateway.", "sevn.channels."))
    }
    assert not forbidden, f"unexpected imports: {sorted(forbidden)}"
