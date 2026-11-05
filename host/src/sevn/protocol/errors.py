"""Session scopes and WebSocket close codes (D6, D7, D12)."""

from __future__ import annotations

from typing import Literal

type Scope = Literal["owner", "member", "read_only"]

CLOSE_UNAUTHORIZED = 4001
CLOSE_VERSION = 4002
CLOSE_REVOKED = 4003
CLOSE_SLOW = 4008

REASON_UNAUTHORIZED = "unauthorized"
REASON_VERSION = "update sevn: host speaks 1..1"
REASON_REVOKED = "revoked"
REASON_SLOW = "slow consumer"

_RANK: dict[str, int] = {"read_only": 0, "member": 1, "owner": 2}

# Plan 0055 D12 (operator, 2026-11-02): ``member`` = ``owner`` for now. This mapping is the
# only place that says so; to narrow ``member`` later, drop its entry here. Stored scopes are
# untouched: devices, ``session.scope`` and ``devices.self`` still say ``member``, and the D1
# owner-ticket and D2 last-owner rules read the stored value, not this mapping.
_EFFECTIVE: dict[str, str] = {"member": "owner"}


def effective_scope(have: str) -> str:
    """The scope a session's method checks run with (D12)."""
    return _EFFECTIVE.get(have, have)


def scope_allows(have: str, need: Scope | None) -> bool:
    """Whether a session with scope ``have`` may call a method declared ``need``.

    ``read_only`` is refused every owner- and member-scoped method; an unknown scope is
    refused every scoped method; ``member`` currently passes as ``owner`` (D12).
    """
    if need is None:
        return True
    return _RANK.get(effective_scope(have), -1) >= _RANK[need]
