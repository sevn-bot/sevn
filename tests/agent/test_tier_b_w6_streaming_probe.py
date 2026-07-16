"""W6 — streaming/tool interleave mitigation (msg=7b8454)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.config.workspace_config import SecurityWorkspaceConfig, WorkspaceConfig
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy


def _openai_assistant_text(text: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        super().__init__(proxy_base_url="http://tier-b-w6.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return await self._fn(dict(request))


def _workspace(tmp: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=str(tmp),
        security=SecurityWorkspaceConfig(),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def _triage(*, tools: list[str] | None = None, skills: list[str] | None = None) -> TriageResult:
    return TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=tools or [],
        skills=skills or [],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )


# ---------------------------------------------------------------------------
# W6.1 / W6.2 — msg=7b8454 streaming + bound tools (mitigation B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_7b8454_bound_tools_disable_streaming_proactively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """msg=7b8454: bound registry tools disable progressive streaming before tool rounds."""
    from tests.agent.test_b_harness import _make_tick_executor

    info_records: list[str] = []
    consume_calls = 0

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    async def _patched_consume(*_args: object, **_kwargs: object) -> None:
        nonlocal consume_calls
        consume_calls += 1

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )
    monkeypatch.setattr(
        "sevn.agent.executors.b_harness._consume_model_request_stream",
        _patched_consume,
    )

    exe, tool_set = _make_tick_executor()

    async def _once(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Search complete.")

    transport = _ScriptedChatTransport(_once)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.PER_TOKEN),
    )
    sink_calls: list[str] = []

    async def _sink(text: str) -> None:
        sink_calls.append(text)

    outcome = await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-w6"),
        turn_id="t-w6",
        triage=_triage(tools=["search_in_file"]),
        incoming_text="find temperature mentions",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=4),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s-w6",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=tool_set.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-w6",
        ),
        streaming_sink=_sink,
        streaming_debounce_s=0.0,
    )

    disabled = [m for m in info_records if "streaming_disabled" in m]
    assert any("reason=bound_tools_or_skills" in m for m in disabled)
    assert consume_calls == 0
    assert sink_calls == []
    # W2 must-satisfy may fail a text-only bound-tool turn — W6 only asserts streaming gate.
    assert outcome.status in {"completed", "failed"}


@pytest.mark.asyncio
async def test_bound_skill_disables_streaming_proactively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """msg=62803d: bound ``browser-harness`` skill disables progressive streaming."""
    from tests.agent.test_b_harness import _make_tick_executor

    info_records: list[str] = []

    def _capture_info(message: str, *args: object, **kwargs: object) -> None:
        info_records.append(message.format(*args))

    monkeypatch.setattr(
        "sevn.agent.executors.b_harness.logger.info",
        _capture_info,
    )

    exe, tool_set = _make_tick_executor()

    async def _once(_req: dict[str, Any]) -> dict[str, Any]:
        return _openai_assistant_text("Screenshot queued.")

    transport = _ScriptedChatTransport(_once)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-test",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-test", regime=BudgetRegime.PER_TOKEN),
    )

    await run_b_turn(
        workspace=_workspace(tmp_path),
        session=SessionHandle(session_id="s-pw"),
        turn_id="t-pw",
        triage=_triage(tools=["run_skill_script", "send_file"], skills=["browser-harness"]),
        incoming_text="screenshot example.com",
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=4),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=ToolContext(
            session_id="s-pw",
            workspace_path=tmp_path,
            workspace_id="w",
            registry_version=tool_set.registry_version,
            trace=None,
            permissions=AllowAllPermissionPolicy(),
            turn_id="t-pw",
        ),
        streaming_sink=AsyncMock(),
        streaming_debounce_s=0.0,
    )

    disabled = [m for m in info_records if "streaming_disabled" in m]
    assert any("reason=bound_tools_or_skills" in m for m in disabled)
    assert any("browser-harness" in m for m in disabled)


# --- W1 RED (DP3): grounding + prompt alias drops (green after W5) ---


@pytest.mark.xfail(
    reason="green after W5: DP3 steer_for_browser_cdp_probe_failure rename", strict=False
)
def test_steer_for_browser_cdp_probe_failure_renamed() -> None:
    """DP3: grounding exports steer_for_browser_cdp_probe_failure; old name gone."""
    import sevn.agent.grounding as grounding

    assert hasattr(grounding, "steer_for_browser_cdp_probe_failure")
    assert "steer_for_browser_cdp_probe_failure" in grounding.__all__
    assert not hasattr(grounding, "steer_for_playwright_cdp_probe_failure")
    assert "steer_for_playwright_cdp_probe_failure" not in grounding.__all__
    msg = grounding.steer_for_browser_cdp_probe_failure()
    assert isinstance(msg, str)
    assert msg.strip()
    assert "CDP_UNREACHABLE" in msg


@pytest.mark.xfail(
    reason="green after W5: DP3 drop tier_b_playwright_browser_prompt alias", strict=False
)
def test_tier_b_playwright_browser_prompt_alias_removed() -> None:
    """DP3: deprecated tier_b_playwright_browser_prompt is gone from module + __all__."""
    import sevn.prompts.tier_b as tier_b

    assert not hasattr(tier_b, "tier_b_playwright_browser_prompt")
    assert "tier_b_playwright_browser_prompt" not in tier_b.__all__
    assert hasattr(tier_b, "tier_b_browser_tool_prompt")


@pytest.mark.xfail(reason="green after W5: DP3 drop PLAYWRIGHT_BROWSER_RULE alias", strict=False)
def test_playwright_browser_rule_alias_removed() -> None:
    """DP3: PLAYWRIGHT_BROWSER_RULE alias is removed; BROWSER_TOOL_RULE remains."""
    import sevn.prompts.triager as triager

    assert hasattr(triager, "BROWSER_TOOL_RULE")
    assert not hasattr(triager, "PLAYWRIGHT_BROWSER_RULE")
