"""Session scopes and WebSocket close codes (D6, D7, D12)."""

from __future__ import annotations

from typing import Literal

type Scope = Literal["owner", "member", "read_only"]

CLOSE_UNAUTHORIZED = 4001
CLOSE_VERSION = 4002
CLOSE_SLOW = 4008

REASON_UNAUTHORIZED = "unauthorized"
REASON_VERSION = "update sevn: host speaks 1..1"
REASON_SLOW = "slow consumer"

_RANK: dict[str, int] = {"read_only": 0, "member": 1, "owner": 2}


def scope_allows(have: str, need: Scope | None) -> bool:
    """Owner-only methods refuse member and read_only sessions."""
    if need is None:
        return True
    return _RANK.get(have, -1) >= _RANK[need]
