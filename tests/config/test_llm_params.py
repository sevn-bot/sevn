"""Tests for per-agent LLM call config (`src/sevn/config/llm_params.py`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.defaults import MINIMAX_MAX_OUTPUT_TOKENS, TIER_B_MAX_OUTPUT_TOKENS
from sevn.config.llm_params import (
    AGENT_NAMES,
    LLM_PARAMS_FILENAME,
    LLM_PARAMS_SCHEMA_VERSION,
    SamplingParams,
    builtin_llm_params_doc,
    load_or_create_llm_params_doc,
    resolve_effective_max_output_tokens,
    resolve_llm_params,
    resolve_llm_params_max_output_tokens,
    resolve_llm_request_params,
    resolve_reasoning_request,
    set_agent_model_max_output_tokens,
    validate_llm_params_doc,
)
from sevn.config.workspace_config import WorkspaceConfig


def _write_workspace(tmp_path: Path, doc: dict) -> Path:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_builtin_doc_is_valid_and_covers_all_agents() -> None:
    doc = builtin_llm_params_doc()
    validate_llm_params_doc(doc)
    assert doc["schema_version"] == LLM_PARAMS_SCHEMA_VERSION
    for agent in AGENT_NAMES:
        assert agent in doc
        assert doc[agent]["max_output_tokens"] >= 1
        assert doc[agent]["reasoning"] == {"enabled": False, "type": "adaptive"}
        assert doc[agent]["model_overrides"]["minimax/*"]["max_output_tokens"] == (
            MINIMAX_MAX_OUTPUT_TOKENS
        )
    assert "minimax_thinking" not in doc["tier_b"]


def test_lcm_default_preserved() -> None:
    assert resolve_llm_params("lcm", "openai:gpt-4o").temperature == pytest.approx(0.2)


def test_non_minimax_agents_default_deterministic() -> None:
    for agent in ("triager", "tier_b", "tier_cd", "guard", "dreaming", "user_model"):
        assert resolve_llm_params(agent, "openai:gpt-4o").temperature == pytest.approx(0.0)


def test_minimax_defaults_applied_to_anthropic_request() -> None:
    kwargs = resolve_llm_request_params("tier_b", "minimax/MiniMax-M2", "anthropic")
    assert kwargs == {"temperature": 1.0, "top_p": 0.95, "top_k": 40}


def test_minimax_max_output_tokens_default() -> None:
    assert (
        resolve_llm_params_max_output_tokens("tier_b", "minimax/MiniMax-M2")
        == MINIMAX_MAX_OUTPUT_TOKENS
    )
    assert (
        resolve_llm_params_max_output_tokens("tier_b", "openai:gpt-4o") == TIER_B_MAX_OUTPUT_TOKENS
    )


def test_resolve_reasoning_default_off() -> None:
    assert resolve_reasoning_request("tier_b", "minimax/MiniMax-M2") is None
    assert resolve_reasoning_request("triager", "minimax/MiniMax-M2") is None


def test_validate_reasoning_on_triager_allowed() -> None:
    validate_llm_params_doc({"triager": {"reasoning": {"enabled": False, "type": "adaptive"}}})


def test_validate_legacy_minimax_thinking_still_accepted() -> None:
    validate_llm_params_doc(
        {"tier_b": {"minimax_thinking": {"enabled": False, "type": "adaptive"}}}
    )


def test_validate_reasoning_budget_requires_enabled_type() -> None:
    with pytest.raises(ValueError, match="budget_tokens requires"):
        validate_llm_params_doc(
            {
                "tier_b": {
                    "reasoning": {
                        "enabled": True,
                        "type": "adaptive",
                        "budget_tokens": 1024,
                    }
                }
            }
        )


def test_minimax_defaults_for_every_agent() -> None:
    for agent in AGENT_NAMES:
        sp = resolve_llm_params(agent, "minimax/MiniMax-M2")
        assert (sp.temperature, sp.top_p, sp.top_k) == (1.0, 0.95, 40)


def test_seed_dropped_on_anthropic() -> None:
    sp = SamplingParams(temperature=1.0, top_p=0.95, top_k=40, seed=99)
    out = sp.as_request_kwargs("anthropic")
    assert "seed" not in out
    assert out == {"temperature": 1.0, "top_p": 0.95, "top_k": 40}


def test_top_k_dropped_on_chat_completions() -> None:
    sp = SamplingParams(temperature=0.0, top_p=0.9, top_k=40, seed=7)
    out = sp.as_request_kwargs("chat_completions")
    assert "top_k" not in out
    assert out == {"temperature": 0.0, "top_p": 0.9, "seed": 7}


def test_seed_fallback_only_when_transport_accepts() -> None:
    cc = resolve_llm_request_params("triager", "openai:gpt-4o", "chat_completions", seed=42)
    assert cc["seed"] == 42
    an = resolve_llm_request_params("triager", "minimax/MiniMax-M2", "anthropic", seed=42)
    assert "seed" not in an


def test_workspace_seed_wins_over_caller_seed(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {"triager": {"seed": 99}})
    cc = resolve_llm_request_params(
        "triager", "openai:gpt-4o", "chat_completions", content_root=root, seed=42
    )
    assert cc["seed"] == 99


def test_workspace_per_agent_block_overrides_builtin(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {"tier_b": {"temperature": 0.55}})
    sp = resolve_llm_params("tier_b", "openai:gpt-4o", content_root=root)
    assert sp.temperature == pytest.approx(0.55)


def test_workspace_model_override_wins_over_agent_block(tmp_path: Path) -> None:
    doc = {
        "tier_b": {
            "temperature": 0.55,
            "model_overrides": {"openai:gpt-4o": {"temperature": 0.11, "top_p": 0.8}},
        }
    }
    root = _write_workspace(tmp_path, doc)
    sp = resolve_llm_params("tier_b", "openai:gpt-4o", content_root=root)
    assert sp.temperature == pytest.approx(0.11)
    assert sp.top_p == pytest.approx(0.8)


def test_workspace_minimax_glob_override(tmp_path: Path) -> None:
    doc = {
        "tier_b": {
            "temperature": 0.0,
            "model_overrides": {"minimax/*": {"temperature": 0.7, "top_p": 0.9, "top_k": 20}},
        }
    }
    root = _write_workspace(tmp_path, doc)
    kwargs = resolve_llm_request_params(
        "tier_b", "minimax/MiniMax-M2", "anthropic", content_root=root
    )
    assert kwargs == {"temperature": 0.7, "top_p": 0.9, "top_k": 20}


def test_effective_max_output_tokens_min_sevn_and_llm_params(tmp_path: Path) -> None:
    root = _write_workspace(
        tmp_path,
        {
            "tier_b": {
                "max_output_tokens": 8192,
                "model_overrides": {"minimax/*": {"max_output_tokens": 6000}},
            }
        },
    )
    ws = WorkspaceConfig.minimal(
        gateway={
            "token": "${SECRET:keychain:sevn.gateway.token}",
            "budget": {"tier_b_max_output_tokens": 5000},
        }
    )
    assert (
        resolve_effective_max_output_tokens("tier_b", "minimax/MiniMax-M2", ws, content_root=root)
        == 5000
    )
    ws_high = WorkspaceConfig.minimal(
        gateway={
            "token": "${SECRET:keychain:sevn.gateway.token}",
            "budget": {"tier_b_max_output_tokens": 20000},
        },
    )
    assert (
        resolve_effective_max_output_tokens(
            "tier_b", "minimax/MiniMax-M2", ws_high, content_root=root
        )
        == 6000
    )


def test_effective_max_output_tokens_without_workspace_uses_defaults(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {"guard": {"max_output_tokens": 512}})
    assert (
        resolve_effective_max_output_tokens("guard", "openai:gpt-4o", None, content_root=root)
        == 256
    )


def test_missing_workspace_file_falls_back_to_builtin(tmp_path: Path) -> None:
    sp = resolve_llm_params("lcm", "openai:gpt-4o", content_root=tmp_path)
    assert sp.temperature == pytest.approx(0.2)


def test_invalid_workspace_file_falls_back_to_builtin(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text("{not json", encoding="utf-8")
    sp = resolve_llm_params("lcm", "openai:gpt-4o", content_root=tmp_path)
    assert sp.temperature == pytest.approx(0.2)


def test_validate_rejects_unknown_top_level_key() -> None:
    with pytest.raises(ValueError, match="unknown top-level key"):
        validate_llm_params_doc({"bogus_agent": {"temperature": 0.0}})


def test_validate_rejects_out_of_range_top_p() -> None:
    with pytest.raises(ValueError, match="top_p must be within"):
        validate_llm_params_doc({"tier_b": {"top_p": 1.5}})


def test_validate_rejects_non_int_top_k() -> None:
    with pytest.raises(ValueError, match="top_k must be an integer"):
        validate_llm_params_doc({"tier_b": {"top_k": 0.5}})


def test_validate_rejects_bad_override_block() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        validate_llm_params_doc({"tier_b": {"model_overrides": {"x": 5}}})


def test_validate_rejects_invalid_max_output_tokens() -> None:
    with pytest.raises(ValueError, match="max_output_tokens must be >= 1"):
        validate_llm_params_doc({"tier_b": {"max_output_tokens": 0}})


def test_set_agent_model_max_output_tokens_agent_block(tmp_path: Path) -> None:
    path = set_agent_model_max_output_tokens(
        tmp_path,
        agent="tier_b",
        max_output_tokens=8192,
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    validate_llm_params_doc(doc)
    assert doc["tier_b"]["max_output_tokens"] == 8192
    assert (
        resolve_llm_params_max_output_tokens("tier_b", "openai:gpt-4o", content_root=tmp_path)
        == 8192
    )


def test_set_agent_model_max_output_tokens_model_override(tmp_path: Path) -> None:
    root = _write_workspace(tmp_path, {"tier_b": {"temperature": 0.0}})
    path = set_agent_model_max_output_tokens(
        root,
        agent="tier_b",
        max_output_tokens=6000,
        model_id="minimax/*",
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["tier_b"]["temperature"] == 0.0
    assert doc["tier_b"]["model_overrides"]["minimax/*"]["max_output_tokens"] == 6000
    assert (
        resolve_llm_params_max_output_tokens("tier_b", "minimax/MiniMax-M2", content_root=root)
        == 6000
    )


def test_load_or_create_llm_params_doc_seeds_builtin(tmp_path: Path) -> None:
    doc = load_or_create_llm_params_doc(tmp_path)
    assert doc["schema_version"] == LLM_PARAMS_SCHEMA_VERSION
    assert "triager" in doc


def test_set_agent_model_max_output_tokens_rejects_unknown_agent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        set_agent_model_max_output_tokens(tmp_path, agent="bogus", max_output_tokens=100)
