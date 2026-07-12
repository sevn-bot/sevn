"""OpenAI Codex OAuth constants (locked at W0 — ``codex-oauth-subscription`` plan).

Module: sevn.security.oauth.constants
Depends: none

Exports:
    CODEX_OAUTH_CLIENT_ID — public Codex OAuth client id (from ``openai/codex``).
    CODEX_OAUTH_AUTHORIZE_URL — authorization endpoint.
    CODEX_OAUTH_TOKEN_URL — token exchange / refresh endpoint.
    CODEX_OAUTH_REDIRECT_URI — registered redirect (localhost:1455).
    CODEX_OAUTH_SCOPE — identity scopes for the PKCE flow.
    CODEX_OAUTH_CALLBACK_HOST — bind address for the local callback server (D5).
    CODEX_OAUTH_CALLBACK_PORT — fixed redirect port per OpenAI registration.
    CODEX_OAUTH_CALLBACK_PATH — callback path segment.
    CODEX_OAUTH_ORIGINATOR — ``originator`` header/query value for Codex transport.
    CODEX_JWT_AUTH_CLAIM — JWT namespace for ``chatgpt_account_id``.
    CODEX_RESPONSES_BASE_URL — ChatGPT backend base for Codex Responses (D7 transport).
    CODEX_RESPONSES_PATH — Codex Responses API path (D7 transport).
    OAUTH_OPENAI_SECRET_ALIAS — secrets-chain alias for the credential blob (D2).

Locked decisions (W0 gate - see ``design.py`` and wave plan D1-D7):
    D7: direct Responses HTTP transport to ``CODEX_RESPONSES_*`` - not app-server subprocess.
"""

from __future__ import annotations

# OAuth PKCE flow (verified W0.1 against openai/codex + opencode-openai-codex-auth)
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"  # nosec B105 — OAuth endpoint URL
CODEX_OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
CODEX_OAUTH_SCOPE = "openid profile email offline_access"

CODEX_OAUTH_CALLBACK_HOST = "127.0.0.1"
CODEX_OAUTH_CALLBACK_PORT = 1455
CODEX_OAUTH_CALLBACK_PATH = "/auth/callback"

CODEX_OAUTH_ORIGINATOR = "codex_cli_rs"

CODEX_JWT_AUTH_CLAIM = "https://api.openai.com/auth"

# D7 — direct Responses HTTP transport (opencode-plugin style)
CODEX_RESPONSES_BASE_URL = "https://chatgpt.com/backend-api"
CODEX_RESPONSES_PATH = "/codex/responses"

# D2 — credential blob alias (no raw token in sevn.json)
OAUTH_OPENAI_SECRET_ALIAS = "oauth.openai"  # nosec B105 — secrets-chain alias, not a password
