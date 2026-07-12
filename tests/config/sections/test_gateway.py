"""Gateway section parse-time cross-field validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import parse_workspace_config


def test_gateway_intro_max_output_tokens_within_budget_ok() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "token": "${SECRET:keychain:sevn.gateway.token}",
                "first_session_intro": {"max_output_tokens": 2048},
                "budget": {"tier_b_max_output_tokens": 4096},
            },
        },
    )
    assert cfg.gateway is not None
    assert cfg.gateway.first_session_intro is not None
    assert cfg.gateway.first_session_intro.max_output_tokens == 2048


def test_gateway_intro_max_output_tokens_exceeds_budget_fails() -> None:
    with pytest.raises(
        ValidationError,
        match=r"gateway\.first_session_intro\.max_output_tokens",
    ):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                    "first_session_intro": {"max_output_tokens": 16000},
                    "budget": {"tier_b_max_output_tokens": 4096},
                },
            },
        )


def test_gateway_queue_mode_accepts_multi() -> None:
    """``gateway.queue_mode`` gains ``multi`` (`specs/36-sub-agents.md` D6)."""
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "token": "${SECRET:keychain:sevn.gateway.token}",
                "queue_mode": "multi",
            },
        },
    )
    assert cfg.gateway is not None
    assert cfg.gateway.queue_mode == "multi"


def test_gateway_queue_mode_rejects_unknown_literal() -> None:
    with pytest.raises(ValidationError, match="queue_mode"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                    "queue_mode": "bogus",
                },
            },
        )
