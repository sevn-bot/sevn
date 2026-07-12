"""Extractor guardrails (`specs/32-memory-honcho.md` §8)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sevn.config.llm_params import LLM_PARAMS_FILENAME
from sevn.memory.user_model.extractor import UserModelExtractor


class _FakeTransport:
    name = "chat_completions"
    last_request: dict[str, object] | None = None

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        self.last_request = dict(request)
        return {
            "choices": [
                {"message": {"content": '{"facts":[{"topic":"x","value":"y","confidence":"low"}]}'}}
            ]
        }

    async def stream(self, request: dict[str, object]):
        if False:
            yield {}

    def auth_header(self, model_id: str) -> dict[str, str]:
        return {}

    def tokens_used(self, response: dict[str, object]) -> tuple[int, int]:
        return (0, 0)

    def cache_breakpoints(
        self, prompt_segments: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        return list(prompt_segments)


def test_extractor_skips_llmignore_path() -> None:
    ex = UserModelExtractor(_FakeTransport())  # type: ignore[arg-type]
    out = asyncio.run(
        ex.extract_deltas(
            workspace_root=".",
            turn_user_text="read workspace/.llmignore/foo",
            active_session_id="s",
            model_id="gpt-4o-mini",
            deny_topic_patterns=[],
        ),
    )
    assert out == []


def test_extractor_parses_json_payload() -> None:
    ex = UserModelExtractor(_FakeTransport())  # type: ignore[arg-type]
    out = asyncio.run(
        ex.extract_deltas(
            workspace_root=".",
            turn_user_text="I prefer dark mode",
            active_session_id="s",
            model_id="gpt-4o-mini",
            deny_topic_patterns=[],
        ),
    )
    assert len(out) == 1
    assert out[0].topic == "x"


def test_extractor_uses_workspace_sampling_params(tmp_path: Path) -> None:
    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps({"user_model": {"temperature": 0.42}}),
        encoding="utf-8",
    )
    transport = _FakeTransport()
    ex = UserModelExtractor(transport)  # type: ignore[arg-type]
    asyncio.run(
        ex.extract_deltas(
            workspace_root=str(tmp_path),
            turn_user_text="I prefer dark mode",
            active_session_id="s",
            model_id="openai:gpt-4o-mini",
            deny_topic_patterns=[],
        ),
    )
    assert transport.last_request is not None
    assert transport.last_request["temperature"] == pytest.approx(0.42)
