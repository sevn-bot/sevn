"""Channels section config tests (``busy_input_mode`` incl. ``multi``, D6)."""

from __future__ import annotations

from sevn.config.sections.channels import resolve_busy_input_mode
from sevn.config.workspace_config import parse_workspace_config


def test_resolve_busy_input_mode_per_channel_multi() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "channels": {"telegram": {"busy_input_mode": "multi"}},
        },
    )
    assert resolve_busy_input_mode(cfg.channels, "telegram", gateway_queue_mode="cancel") == "multi"


def test_resolve_busy_input_mode_gateway_fallback_multi() -> None:
    assert resolve_busy_input_mode(None, "telegram", gateway_queue_mode="multi") == "multi"


def test_resolve_busy_input_mode_per_channel_overrides_gateway_fallback() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "channels": {"telegram": {"busy_input_mode": "steer"}},
        },
    )
    assert resolve_busy_input_mode(cfg.channels, "telegram", gateway_queue_mode="multi") == "steer"
