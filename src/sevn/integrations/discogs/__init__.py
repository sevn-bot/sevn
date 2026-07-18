"""Discogs REST API integration helpers (OAuth setup for Telegram).

Module: sevn.integrations.discogs
Depends: sevn.integrations.discogs.oauth

Exports:
    DiscogsOAuthError — typed OAuth handshake failure.
    begin_oauth — request token + authorize URL.
    complete_oauth — exchange verifier for access token pair.
"""

from __future__ import annotations

from sevn.integrations.discogs.oauth import (
    DiscogsOAuthError,
    begin_oauth,
    complete_oauth,
)

__all__ = [
    "DiscogsOAuthError",
    "begin_oauth",
    "complete_oauth",
]
