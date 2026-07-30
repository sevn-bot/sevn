"""W8.5 — reasoning-effort routing with graceful provider fallback (#89 → W11)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.config.llm_params import LLM_PARAMS_FILENAME, resolve_reasoning_request


def test_non_minimax_reasoning_override_logs_and_omits_wire_param(
    tmp_path: Path,
) -> None:
    from loguru import logger as loguru_logger

    from sevn.config.llm_params import resolve_reasoning_for_turn

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="INFO")
    try:
        (tmp_path / LLM_PARAMS_FILENAME).write_text(
            json.dumps(
                {
                    "tier_b": {
                        "reasoning": {"enabled": True, "type": "enabled", "budget_tokens": 2048},
                    },
                }
            ),
            encoding="utf-8",
        )
        body = resolve_reasoning_for_turn(
            "tier_b",
            "anthropic/claude-sonnet-4-20250514",
            content_root=tmp_path,
            route_reasoning_effort="high",
        )
    finally:
        loguru_logger.remove(sink_id)
    assert body is None
    joined = " ".join(captured).lower()
    assert "reasoning" in joined
    assert "unsupported" in joined or "degrad" in joined or "skipped" in joined


def test_explicit_reasoning_effort_on_supported_minimax(tmp_path: Path) -> None:
    from sevn.config.llm_params import resolve_reasoning_for_turn

    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps({"tier_b": {"reasoning": {"enabled": True, "type": "adaptive"}}}),
        encoding="utf-8",
    )
    body = resolve_reasoning_for_turn(
        "tier_b",
        "minimax/MiniMax-M2.7",
        content_root=tmp_path,
        route_reasoning_effort="high",
    )
    assert body is not None
    assert body.get("type") in {"adaptive", "enabled"}


def test_triager_never_sends_reasoning_on_default_config() -> None:
    """Regression lock: triager stays excluded before and after W11."""
    assert resolve_reasoning_request("triager", "minimax/MiniMax-M2.7") is None


def test_triager_thinking_hygiene_covered_by_existing_suite() -> None:
    """W11 must keep ``tests/agent/test_tier_b_minimax_request_hygiene.py`` green."""
    from tests.agent import test_tier_b_minimax_request_hygiene as hygiene

    assert hasattr(hygiene, "test_triager_minimax_never_sends_thinking_even_when_config_enabled")
