"""Register pytest markers for browser recipe tests."""

from __future__ import annotations

from typing import Any


def pytest_configure(config: Any) -> None:
    """Register live-gated markers before W2 adds them to pyproject.toml."""
    config.addinivalue_line(
        "markers",
        "telegram_menu_e2e: optional live Telegram /config menu walk "
        "(skipped unless SEVN_TELEGRAM_MENU_E2E=1)",
    )
