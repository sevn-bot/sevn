"""TwexAPI (https://docs.twexapi.io/) client for the Social Media Manager specialist.

Module: sevn.integrations.twexapi
Depends: sevn.integrations.twexapi.client, sevn.integrations.twexapi.config

Exports:
    TwexApiError — typed TwexAPI failure.
    TwexApiClient — Bearer-auth HTTP client for TwexAPI REST endpoints.
    TwexApiSettings — resolved workspace settings for TwexAPI.
    load_twexapi_settings — parse ``skills.social_media_manager`` TwexAPI block.
    resolve_twexapi_api_key — resolve plaintext API key.
"""

from __future__ import annotations

from sevn.integrations.twexapi.client import TwexApiClient, TwexApiError
from sevn.integrations.twexapi.config import (
    TwexApiSettings,
    load_twexapi_settings,
    resolve_twexapi_api_key,
)

__all__ = [
    "TwexApiClient",
    "TwexApiError",
    "TwexApiSettings",
    "load_twexapi_settings",
    "resolve_twexapi_api_key",
]
