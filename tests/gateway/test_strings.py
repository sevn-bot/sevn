"""Stable English gateway copy (`specs/17-gateway.md` §10.6)."""

from __future__ import annotations

import sevn.gateway.util.strings as strings


def test_gateway_string_constants_non_empty() -> None:
    for name in (
        "BLOCKED_INBOUND_USER_MESSAGE",
        "SCANNER_UNAVAILABLE_USER_MESSAGE",
        "VOICE_INBOUND_REJECTED_TOO_LARGE",
        "VOICE_INBOUND_REJECTED_TOO_LONG",
        "STEER_NOT_AVAILABLE_V1",
        "STEER_ACK_V1",
        "STEER_USAGE_V1",
        "STEER_NOT_OWNER_V1",
        "STEER_BUFFER_FULL_V1",
        "CALLBACK_GENERIC_TOAST_ACK",
        "CALLBACK_AUTH_BLOCKED_TOAST",
    ):
        val = getattr(strings, name)
        assert isinstance(val, str)
        assert len(val.strip()) > 0


def test_stable_module_attribute_names() -> None:
    """Identifiers remain importable for dispatcher and router wiring."""

    again = __import__("sevn.gateway.util.strings", fromlist=["*"])
    assert again.BLOCKED_INBOUND_USER_MESSAGE is strings.BLOCKED_INBOUND_USER_MESSAGE


def test_blocked_inbound_user_message_scanner_unavailable() -> None:
    from sevn.gateway.util.strings import (
        SCANNER_UNAVAILABLE_USER_MESSAGE,
        blocked_inbound_user_message,
    )
    from sevn.security.llm_guard_scanner import BlockReason

    msg = blocked_inbound_user_message(reasons=(BlockReason.scanner_unavailable,))
    assert msg == SCANNER_UNAVAILABLE_USER_MESSAGE
    assert "proxy" in msg.lower()


def test_dispatcher_callback_auth_toast_matches_strings_module() -> None:
    from sevn.gateway.commands.dispatcher import CommandDispatcher

    assert (
        CommandDispatcher().callback_auth_blocked_user_toast()
        is strings.CALLBACK_AUTH_BLOCKED_TOAST
    )
