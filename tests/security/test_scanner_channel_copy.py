"""Tests for canonical scanner user copy (``specs/09-security-scanner.md`` §6)."""

from __future__ import annotations

from sevn.security.scanner_channel_copy import INBOUND_BLOCK_NOTICE, WEBAPP_FEEDBACK_SUBMIT_BLOCKED


def test_inbound_block_notice_is_stable_product_copy() -> None:
    assert "security" in INBOUND_BLOCK_NOTICE.casefold()
    assert len(INBOUND_BLOCK_NOTICE) < 200


def test_feedback_submit_error_is_non_echoing() -> None:
    assert WEBAPP_FEEDBACK_SUBMIT_BLOCKED
    assert "{" not in WEBAPP_FEEDBACK_SUBMIT_BLOCKED
