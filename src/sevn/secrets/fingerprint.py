"""Stable fingerprints for operator CLI confirmation (`specs/06-secrets.md` §2.6).

Module: sevn.secrets.fingerprint
Depends: hashlib

Exports:
    fingerprint_sha256_hex — SHA-256 digest of UTF-8 secret (hex string).
"""

from __future__ import annotations

import hashlib


def fingerprint_sha256_hex(secret: str) -> str:
    """Return lowercase SHA-256 hex of ``secret`` encoded as UTF-8.

    Args:
        secret (str): Plaintext credential (never log or echo).

    Returns:
        str: 64-character lowercase hex digest.

    Examples:
        >>> len(fingerprint_sha256_hex("x"))
        64
        >>> fingerprint_sha256_hex("a") == fingerprint_sha256_hex("a")
        True
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
