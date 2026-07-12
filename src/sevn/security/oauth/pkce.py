"""PKCE pair generation for Codex OAuth (W2).

Module: sevn.security.oauth.pkce
Depends: none

Exports:
    PkcePair — verifier/challenge tuple for S256 PKCE.
    generate_pkce_pair — create a PKCE verifier and S256 challenge.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PkcePair:
    """PKCE verifier and S256 code challenge."""

    verifier: str
    challenge: str


def _s256_challenge(verifier: str) -> str:
    """Return base64url(SHA256(verifier)) without padding.

    Args:
        verifier (str): PKCE code verifier.

    Returns:
        str: S256 ``code_challenge`` value.

    Examples:
        >>> _s256_challenge("abc")
        '...'
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def generate_pkce_pair() -> PkcePair:
    """Generate a PKCE verifier/challenge pair (S256).

    Returns:
        PkcePair: Verifier and matching ``code_challenge`` for authorize URL.

    Examples:
        >>> pair = generate_pkce_pair()
        >>> len(pair.verifier) >= 43
        True
        >>> pair.challenge == _s256_challenge(pair.verifier)
        True
    """
    verifier = secrets.token_urlsafe(32)
    return PkcePair(verifier=verifier, challenge=_s256_challenge(verifier))
