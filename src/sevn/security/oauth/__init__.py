"""Codex (ChatGPT subscription) OAuth for sevn LLM transports (W0 scaffold).

Module: sevn.security.oauth
Depends: sevn.security.oauth.{constants,design,credential,pkce,authorize,callback,token_client}

Exports:
    LOCKED_DECISIONS - W0 ratified D1-D7 decision summaries.
    CodexOAuthCredential — credential blob at ``oauth.openai`` (D2).
    oauth_openai_secret_alias — canonical ``oauth.openai`` alias helper.
    CODEX_* / OAUTH_* constants — OAuth and Responses transport endpoints.
    PkcePair, generate_pkce_pair — PKCE scaffold (W2).
    AuthorizationFlow, build_authorization_flow — authorize URL scaffold (W2).
    OAuthCallbackServer, start_local_callback_server — callback scaffold (D5, W2).
    TokenExchangeResult, exchange_authorization_code, refresh_access_token,
        extract_account_id — token client scaffold (W2/W3).

W0 locked design (see ``design.LOCKED_DECISIONS``):
    D1 auth_mode selector, D2 oauth.openai blob, D3 proxy refresh, D4 back-compat,
    D5 headless fallback, D6 CLI/MC/onboarding surfaces, D7 direct Responses HTTP transport.
"""

from __future__ import annotations

from sevn.security.oauth.authorize import AuthorizationFlow, build_authorization_flow
from sevn.security.oauth.callback import OAuthCallbackServer, start_local_callback_server
from sevn.security.oauth.constants import (
    CODEX_JWT_AUTH_CLAIM,
    CODEX_OAUTH_AUTHORIZE_URL,
    CODEX_OAUTH_CALLBACK_HOST,
    CODEX_OAUTH_CALLBACK_PATH,
    CODEX_OAUTH_CALLBACK_PORT,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_ORIGINATOR,
    CODEX_OAUTH_REDIRECT_URI,
    CODEX_OAUTH_SCOPE,
    CODEX_OAUTH_TOKEN_URL,
    CODEX_RESPONSES_BASE_URL,
    CODEX_RESPONSES_PATH,
    OAUTH_OPENAI_SECRET_ALIAS,
)
from sevn.security.oauth.credential import CodexOAuthCredential, oauth_openai_secret_alias
from sevn.security.oauth.design import LOCKED_DECISIONS
from sevn.security.oauth.pkce import PkcePair, generate_pkce_pair
from sevn.security.oauth.token_client import (
    TokenExchangeResult,
    exchange_authorization_code,
    extract_account_id,
    refresh_access_token,
)

__all__ = [
    "CODEX_JWT_AUTH_CLAIM",
    "CODEX_OAUTH_AUTHORIZE_URL",
    "CODEX_OAUTH_CALLBACK_HOST",
    "CODEX_OAUTH_CALLBACK_PATH",
    "CODEX_OAUTH_CALLBACK_PORT",
    "CODEX_OAUTH_CLIENT_ID",
    "CODEX_OAUTH_ORIGINATOR",
    "CODEX_OAUTH_REDIRECT_URI",
    "CODEX_OAUTH_SCOPE",
    "CODEX_OAUTH_TOKEN_URL",
    "CODEX_RESPONSES_BASE_URL",
    "CODEX_RESPONSES_PATH",
    "LOCKED_DECISIONS",
    "OAUTH_OPENAI_SECRET_ALIAS",
    "AuthorizationFlow",
    "CodexOAuthCredential",
    "OAuthCallbackServer",
    "PkcePair",
    "TokenExchangeResult",
    "build_authorization_flow",
    "exchange_authorization_code",
    "extract_account_id",
    "generate_pkce_pair",
    "oauth_openai_secret_alias",
    "refresh_access_token",
    "start_local_callback_server",
]
