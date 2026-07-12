"""W9 — config-surfaced thresholds and eval-only corpus locale cleanup."""

from __future__ import annotations

from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import (
    COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
    _should_clamp_cd_to_b,
    classify_greeting,
    is_strict_greeting_message,
)
from sevn.config.defaults import (
    DEFAULT_CASCADE_BUDGET_S,
    DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
    DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S,
    DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S,
)
from sevn.config.workspace_config import (
    GatewayBudgetConfig,
    GatewayConfig,
    TriagerWorkspaceConfig,
    WorkspaceConfig,
    cascade_budget_s,
    complexity_clamp_confidence_threshold,
    complexity_clamp_short_word_limit,
    parse_workspace_config,
    tier_b_executor_timeout_s,
    tier_cd_executor_timeout_s,
)
from sevn.gateway import agent_turn
from sevn.self_improve.eval.replay import strip_corpus_locale_prefix

_PINNED_THRESHOLDS: dict[str, float | int] = {
    "COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD": COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    "COMPLEXITY_CLAMP_SHORT_WORD_LIMIT": COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
    "TIER_B_EXECUTOR_TIMEOUT_S": agent_turn.TIER_B_EXECUTOR_TIMEOUT_S,
    "TIER_CD_EXECUTOR_TIMEOUT_S": agent_turn.TIER_CD_EXECUTOR_TIMEOUT_S,
    "CASCADE_BUDGET_S": agent_turn.CASCADE_BUDGET_S,
}


def test_w9_threshold_defaults_match_pinned_values() -> None:
    assert _PINNED_THRESHOLDS["COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD"] == 0.85
    assert _PINNED_THRESHOLDS["COMPLEXITY_CLAMP_SHORT_WORD_LIMIT"] == 6
    assert _PINNED_THRESHOLDS["TIER_B_EXECUTOR_TIMEOUT_S"] == 180.0
    assert _PINNED_THRESHOLDS["TIER_CD_EXECUTOR_TIMEOUT_S"] == 300.0
    assert _PINNED_THRESHOLDS["CASCADE_BUDGET_S"] == 270.0
    assert _PINNED_THRESHOLDS["CASCADE_BUDGET_S"] > _PINNED_THRESHOLDS["TIER_B_EXECUTOR_TIMEOUT_S"]


def test_w9_threshold_defaults_match_config_defaults_module() -> None:
    assert COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD == DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD
    assert COMPLEXITY_CLAMP_SHORT_WORD_LIMIT == DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT
    assert agent_turn.TIER_B_EXECUTOR_TIMEOUT_S == DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S
    assert agent_turn.TIER_CD_EXECUTOR_TIMEOUT_S == DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S
    assert agent_turn.CASCADE_BUDGET_S == DEFAULT_CASCADE_BUDGET_S


def test_w9_config_helpers_honor_sevn_json_overrides() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {
                "complexity_clamp_confidence_threshold": 0.9,
                "complexity_clamp_short_word_limit": 4,
            },
            "gateway": {
                "budget": {
                    "tier_b_executor_timeout_s": 120.0,
                    "tier_cd_executor_timeout_s": 240.0,
                    "cascade_budget_s": 200.0,
                },
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
        },
    )
    assert complexity_clamp_confidence_threshold(cfg) == 0.9
    assert complexity_clamp_short_word_limit(cfg) == 4
    assert tier_b_executor_timeout_s(cfg) == 120.0
    assert tier_cd_executor_timeout_s(cfg) == 240.0
    assert cascade_budget_s(cfg) == 200.0


def test_w9_complexity_clamp_respects_config_threshold() -> None:
    low = TriageResult.model_construct(
        intent=Intent.FOLLOWUP,
        complexity=ComplexityTier.C,
        first_message="ok",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.78,
        requires_vision=False,
        disregard=False,
    )
    assert _should_clamp_cd_to_b(
        low,
        current_message="all this needs to be fixed",
        confidence_threshold=0.85,
        short_word_limit=6,
    )
    assert not _should_clamp_cd_to_b(
        low,
        current_message="all this needs to be fixed",
        confidence_threshold=0.75,
        short_word_limit=6,
    )


def test_w9_production_greeting_ignores_corpus_locale_prefix() -> None:
    assert classify_greeting("[en] hello") is None
    assert is_strict_greeting_message("[en] hello") is False
    assert classify_greeting("hello") == "hello"


def test_w9_eval_harness_strips_corpus_locale_prefix() -> None:
    assert strip_corpus_locale_prefix("[en] hello") == "hello"
    assert strip_corpus_locale_prefix("[de] bonjour") == "bonjour"
    assert classify_greeting(strip_corpus_locale_prefix("[en] hello")) == "hello"


def test_w9_workspace_config_model_defaults() -> None:
    triager = TriagerWorkspaceConfig()
    budget = GatewayBudgetConfig()
    assert (
        triager.complexity_clamp_confidence_threshold
        == DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD
    )
    assert triager.complexity_clamp_short_word_limit == DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT
    assert budget.tier_b_executor_timeout_s == DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S
    assert budget.tier_cd_executor_timeout_s == DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S
    assert budget.cascade_budget_s == DEFAULT_CASCADE_BUDGET_S


def test_w9_none_workspace_uses_defaults() -> None:
    assert (
        complexity_clamp_confidence_threshold(None) == DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD
    )
    assert tier_b_executor_timeout_s(None) == DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S
    assert cascade_budget_s(None) == DEFAULT_CASCADE_BUDGET_S


def test_w9_gateway_config_nested_budget_override() -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        gateway=GatewayConfig(
            budget=GatewayBudgetConfig(tier_b_executor_timeout_s=99.0),
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
    )
    assert tier_b_executor_timeout_s(cfg) == 99.0
