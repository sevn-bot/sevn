"""Prefixed ULIDs (D1)."""

from __future__ import annotations

import hashlib
import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    """Return ``prefix`` plus a 26-character Crockford ULID."""
    return prefix + _ulid()


def stable_id(prefix: str, *parts: str) -> str:
    """``prefix`` plus 26 Crockford characters derived from ``parts``.

    The same parts always give the same id, so a retried write finds the row
    the first attempt made instead of adding another.
    """
    digest = hashlib.sha256("\x1f".join(parts).encode()).digest()
    value = int.from_bytes(digest[:17], "big") >> 6
    chars: list[str] = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return prefix + "".join(reversed(chars))


def _ulid() -> str:
    millis = int(time.time() * 1000) & ((1 << 48) - 1)
    value = (millis << 80) | int.from_bytes(secrets.token_bytes(10), "big")
    chars: list[str] = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))
