"""Shared keys for provider-native transcript persistence (D8).

Module: sevn.agent.provider_history_keys
Depends: (none)

Exports:
    PROVIDER_TURN_MESSAGES_KEY — ``extras_json`` / outbound metadata field name.
    SUCCESSFUL_TOOLS_KEY — gateway ``ok=true`` tool names for one assistant turn.
"""

from __future__ import annotations

PROVIDER_TURN_MESSAGES_KEY: str = "provider_turn_messages"
"""Key for Anthropic-shaped tier-B turn rows on assistant ``extras_json``."""

SUCCESSFUL_TOOLS_KEY: str = "successful_tools"
"""Key for tier-B tools that returned ``ok=true`` on assistant ``extras_json``."""

__all__ = ["PROVIDER_TURN_MESSAGES_KEY", "SUCCESSFUL_TOOLS_KEY"]
