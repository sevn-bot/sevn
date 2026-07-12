"""Playwright harness for Telegram Web K E2E against sevn.bot gateways.

Module: sevn_telegram_tester
Depends: playwright, pydantic-settings, loguru

Exports:
    NEEDS_LOGIN_EXIT_CODE — CLI exit when Telegram Web session is missing.
"""

from __future__ import annotations

NEEDS_LOGIN_EXIT_CODE = 7

__all__ = ["NEEDS_LOGIN_EXIT_CODE"]
