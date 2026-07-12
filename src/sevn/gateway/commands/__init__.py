"""Gateway-owned slash commands and callback dispatch scaffold.

Module: sevn.gateway.commands
Depends: sevn.gateway.commands.dispatcher

Exports:
    CommandDispatcher — pre-LLM short-circuit entrypoint (`specs/17-gateway.md` §2.4).
"""

from __future__ import annotations

from sevn.gateway.commands.dispatcher import CommandDispatcher

__all__ = ["CommandDispatcher"]
