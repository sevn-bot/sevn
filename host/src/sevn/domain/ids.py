"""Prefixed ULIDs (D1)."""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    """Return ``prefix`` plus a 26-character Crockford ULID."""
    return prefix + _ulid()


def _ulid() -> str:
    millis = int(time.time() * 1000) & ((1 << 48) - 1)
    value = (millis << 80) | int.from_bytes(secrets.token_bytes(10), "big")
    chars: list[str] = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))
