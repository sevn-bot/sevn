"""Locked Codex OAuth design decisions (W0 gate — ``codex-oauth-subscription`` plan).

Module: sevn.security.oauth.design
Depends: none

This module records the ratified W0 decisions D1-D7 as importable documentation.
Implementation waves (W2-W5) must honour these contracts.

Exports:
    LOCKED_DECISIONS — mapping of decision id → summary string.

Decisions:
    D1 — ``providers.openai.auth_mode ∈ {api_key, oauth}`` (default ``api_key``).
         ``oauth`` resolves bearer from ``oauth.openai`` and routes to the Codex
         Responses transport with ``chatgpt-account-id`` / ``OpenAI-Beta`` /
         ``originator`` headers and ``store=false`` body contract.
    D2 — OAuth credential stored as JSON at secret alias ``oauth.openai`` via the
         existing secrets chain/cache; never in ``sevn.json``.
    D3 — Proxy refreshes access token before expiry under an async lock and persists
         rotated ``{access, refresh, expires}`` back to the store.
    D4 — When ``auth_mode`` is unset or ``api_key``, today's resolution path is unchanged.
    D5 — Local callback on ``127.0.0.1:1455``; headless / bind-failure falls back to
         printed authorize URL + pasted redirect URL/code.
    D6 — ``sevn providers oauth login/status/logout --provider openai``, Mission Control
         reauth, and onboarding "Sign in with ChatGPT" drive the real flow (W4).
    D7 — **Direct Responses HTTP transport** (opencode-plugin style) — **confirmed W0.2**.
         Rejected alternative: spawn Codex app-server subprocess (OpenClaw style); incompatible
         with sevn's HTTP egress-proxy architecture and adds native-runtime coupling.
"""

from __future__ import annotations

from typing import Final

LOCKED_DECISIONS: Final[dict[str, str]] = {
    "D1": (
        "providers.openai.auth_mode in {api_key, oauth}; default api_key; "
        "oauth routes to Codex Responses transport with subscription headers"
    ),
    "D2": "OAuth credential JSON blob at secret alias oauth.openai via secrets chain",
    "D3": "Proxy-owned refresh-before-expiry under async lock with token-sink persistence",
    "D4": "Unset or api_key auth_mode preserves today's api_key/bucket/env resolution",
    "D5": "Local callback 127.0.0.1:1455 with headless paste-redirect fallback",
    "D6": "CLI oauth login/status/logout, Mission Control reauth, onboarding wizard",
    "D7": (
        "Direct Responses HTTP transport to chatgpt.com/backend-api/codex/responses "
        "(not Codex app-server subprocess)"
    ),
}
