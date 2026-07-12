"""Playwright test suites for the Telegram Web harness.

Module: sevn_telegram_tester.suites
Depends: sevn_telegram_tester.suites.session

Exports:
    run_session_suite — execute the eight-test session regression pack.
"""

from __future__ import annotations

from sevn_telegram_tester.suites.session import run_session_suite

__all__ = ["run_session_suite"]
