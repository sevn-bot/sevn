"""Tests for the ``gateway.output.tier_b_answer_mode`` config (PROBLEMS.md Priority 2)."""

from __future__ import annotations

import pytest

from sevn.config.defaults import TIER_B_ANSWER_MODE_DEFAULT
from sevn.config.workspace_config import (
    GatewayConfig,
    GatewayOutputConfig,
    WorkspaceConfig,
    tier_b_answer_mode,
)


def test_default_when_cfg_is_none() -> None:
    assert tier_b_answer_mode(None) == TIER_B_ANSWER_MODE_DEFAULT


def test_default_when_gateway_unset() -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    assert tier_b_answer_mode(cfg) == TIER_B_ANSWER_MODE_DEFAULT


def test_default_when_output_unset() -> None:
    cfg = WorkspaceConfig(
        schema_version=1, gateway=GatewayConfig(token="${SECRET:keychain:sevn.gateway.token}")
    )
    assert tier_b_answer_mode(cfg) == TIER_B_ANSWER_MODE_DEFAULT


@pytest.mark.parametrize("mode", ["stream", "two_message_finally"])
def test_explicit_mode_propagates(mode: str) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        gateway=GatewayConfig(
            output=GatewayOutputConfig(tier_b_answer_mode=mode),  # type: ignore[arg-type]
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
    )
    assert tier_b_answer_mode(cfg) == mode


def test_invalid_mode_rejected_at_validation() -> None:
    """Pydantic should reject anything outside the literal set at construction."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GatewayOutputConfig(tier_b_answer_mode="bogus")  # type: ignore[arg-type]
