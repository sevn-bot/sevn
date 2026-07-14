"""``gateway.first_session_intro`` config defaults and schema parity."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.config.defaults import (
    FIRST_SESSION_INTRO_MAX_OUTPUT_TOKENS,
    TIER_B_MAX_OUTPUT_TOKENS,
)
from sevn.config.workspace_config import (
    GatewayBudgetConfig,
    GatewayConfig,
    GatewayFirstSessionIntroConfig,
    WorkspaceConfig,
    parse_workspace_config,
)
from sevn.gateway.onboarding.first_session import first_session_intro_max_output_tokens

_SCHEMA = Path(__file__).resolve().parents[2] / "infra" / "sevn.schema.json"


def test_gateway_first_session_intro_defaults() -> None:
    cfg = GatewayFirstSessionIntroConfig()
    assert cfg.enabled is True
    assert cfg.max_output_tokens == FIRST_SESSION_INTRO_MAX_OUTPUT_TOKENS


def test_parse_workspace_first_session_intro_max_output_tokens() -> None:
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {
                "first_session_intro": {"max_output_tokens": 2048},
                "budget": {"tier_b_max_output_tokens": 20000},
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    assert first_session_intro_max_output_tokens(ws, model_id="openai:gpt-4o") == 2048


def test_intro_effective_cap_is_min_of_intro_and_tier_budget() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        gateway=GatewayConfig(
            first_session_intro=GatewayFirstSessionIntroConfig(max_output_tokens=2048),
            budget=GatewayBudgetConfig(tier_b_max_output_tokens=4096),
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
    )
    assert first_session_intro_max_output_tokens(ws, model_id="openai:gpt-4o") == 2048


def test_schema_defines_first_session_intro_max_output_tokens() -> None:
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    intro = schema["properties"]["gateway"]["properties"]["first_session_intro"]
    props = intro["properties"]
    assert props["max_output_tokens"]["default"] == FIRST_SESSION_INTRO_MAX_OUTPUT_TOKENS
    assert TIER_B_MAX_OUTPUT_TOKENS == 20000
