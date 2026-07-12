"""Frozen ``dispatcher_state.kind`` vocabulary (`specs/17-gateway.md`).

Module: sevn.gateway.commands.dispatcher_kinds
Depends: typing

Exports:
    DispatcherKind — allowed ``dispatcher_state.kind`` literals.
    ALL_DISPATCHER_KINDS — frozenset of every allowed kind string.
Examples:
    >>> "menu" in ALL_DISPATCHER_KINDS
    True
    >>> "typo" in ALL_DISPATCHER_KINDS
    False
"""

from __future__ import annotations

from typing import Literal

DispatcherKind = Literal[
    "menu",
    "toggle",
    "prompt",
    "skill",
    "action",
    "scene",
    "form",
    "secret_wizard",
    "plan_approval",
    "callback_overflow",
    "webapp_share",
    "webapp_feedback",
    "webapp_viewer",
]

ALL_DISPATCHER_KINDS: frozenset[str] = frozenset(
    {
        "menu",
        "toggle",
        "prompt",
        "skill",
        "action",
        "scene",
        "form",
        "secret_wizard",
        "plan_approval",
        "callback_overflow",
        "webapp_share",
        "webapp_feedback",
        "webapp_viewer",
    }
)

__all__ = ["ALL_DISPATCHER_KINDS", "DispatcherKind"]
