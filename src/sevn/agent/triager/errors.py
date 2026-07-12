"""Triager-specific failures (`specs/13-rlm-triager.md` §6).

Module: sevn.agent.triager.errors
Depends: sevn.config.errors

``TriagerUnavailable`` is re-exported from :mod:`sevn.config.errors` so that
config-layer model resolution can raise it without forcing an
``sevn.proxy → sevn.agent`` import edge (import-linter contract "Proxy is a leaf").

Exports:
    TriagerUnknownToolAbort — unknown tool/skill/MCP id under abort policy.
"""

from __future__ import annotations

from sevn.config.errors import TriagerUnavailable

__all__ = ["TriagerUnavailable", "TriagerUnknownToolAbort"]


class TriagerUnknownToolAbort(TriagerUnavailable):
    """Raised when ``triager.on_unknown_named_tool == "abort"`` and the model emits unknown ids."""
