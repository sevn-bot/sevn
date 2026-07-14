"""Wave 4 onboarding / hygiene tests (P10, P13-P16)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.agent.grounding import (
    apply_file_delivery_grounding_guard,
    asserts_ungrounded_claims,
)
from sevn.agent.triager.models import Intent
from sevn.agent.triager.run import (
    _deterministic_triage_fallback_from_raw,
    _synthetic_schema_fallback,
)
from sevn.config.defaults import TRIAGER_PYDANTIC_OUTPUT_RETRIES
from sevn.gateway.onboarding.first_session import _is_user_md_placeholder_value
from sevn.gateway.session_manager import SessionManager
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.workspace.layout import WorkspaceLayout
from sevn.workspace.layout_validate import validate_workspace_layout_at_boot
from tests.gateway.test_agent_turn_escalation import _CapturingTraceSink, _memory_conn


def test_triager_pydantic_output_retries_lowered() -> None:
    assert TRIAGER_PYDANTIC_OUTPUT_RETRIES == 1


def test_synthetic_schema_fallback_sensible_defaults() -> None:
    fb = _synthetic_schema_fallback(turn_id="w4")
    assert fb.intent == Intent.NEW_REQUEST
    assert fb.confidence >= 0.5
    assert fb.first_message.strip()


def test_deterministic_triage_fallback_parses_json() -> None:
    raw = json.dumps(
        {
            "intent": "NEW_REQUEST",
            "complexity": "B",
            "first_message": "On it.",
            "tools": ["read"],
            "skills": [],
            "mcp_servers_required": [],
            "confidence": 0.82,
            "requires_vision": False,
            "requires_document": False,
            "disregard": False,
        },
    )
    parsed = _deterministic_triage_fallback_from_raw(raw, turn_id="w4")
    assert parsed is not None
    assert parsed.intent == Intent.NEW_REQUEST
    assert parsed.tools == ["read"]


def test_agent_placeholder_treated_as_bootstrap_placeholder() -> None:
    assert _is_user_md_placeholder_value("_ask in next turn_")


def test_profile_save_claim_blocked_without_write() -> None:
    _out, blocked = apply_file_delivery_grounding_guard(
        "Profile saved to USER.md.",
        successful_tools_called=frozenset(),
    )
    assert blocked


def test_ungrounded_fetch_prose_no_longer_flagged() -> None:
    """W3.1: local-first/ollama fetch prose is not an ungrounded-claims signal."""
    assert not asserts_ungrounded_claims("OpenClaw is local-first and fetched 2026 from Ollama.")


def test_regen_target_carries_suggested_tier() -> None:
    mgr = SessionManager(_memory_conn())
    mgr.set_regen_target(
        "s1",
        user_text="do the pdf",
        origin_turn_id="t1",
        edit_message_id=42,
        suggested_tier="C",
    )
    taken = mgr.take_regen_target("s1")
    assert taken is not None
    assert taken[3] == "C"


@pytest.mark.asyncio
async def test_list_registry_includes_gated_tool_status(tmp_path: Path) -> None:
    executor, tool_set = build_session_registry(
        registry_version=9,
        workspace_root=tmp_path,
    )
    ctx = ToolContext(
        session_id="sess-w4",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=tool_set.registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )
    raw = await executor.dispatch(ctx, ToolCall(name="list_registry", arguments={}))
    data = json.loads(raw)["data"]
    assert "gated_tools" in data
    assert "sandbox_exec" in data["gated_tools"]
    assert data["gated_tools"]["sandbox_exec"]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_page_content_save_to_writes_file(tmp_path: Path) -> None:
    from sevn.tools.web import get_page_content_tool

    html = "<html><body><p>Hello wiki</p></body></html>"
    fetch_payload = {
        "text": html,
        "status_code": 200,
        "content_type": "text/html",
        "truncated": False,
    }
    ctx = ToolContext(
        session_id="sess-save",
        workspace_path=tmp_path,
        workspace_id="wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        artifact_output_prefix="out/sess-save",
    )
    with patch(
        "sevn.tools.web._proxy_web_fetch",
        new=AsyncMock(return_value=(None, fetch_payload)),
    ):
        raw = await get_page_content_tool(
            ctx,
            url="https://example.com/page",
            save_to="fetched/page.md",
        )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    assert envelope["data"]["saved_path"] == "out/sess-save/fetched/page.md"
    assert (tmp_path / "out" / "sess-save" / "fetched" / "page.md").is_file()


@pytest.mark.asyncio
async def test_layout_optional_dirs_not_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    for name in (".sevn", "logs", "skills"):
        (root / name).mkdir()
    for name in (
        "AGENTS.md",
        "sevn.bot.md",
        "IDENTITY.md",
        "MEMORY.md",
        "SOUL.md",
        "TOOLS.md",
        "USER.md",
        "WORKSPACE.md",
    ):
        (root / name).write_text("x", encoding="utf-8")
    layout = WorkspaceLayout(root / "sevn.json", root)
    trace = _CapturingTraceSink()
    result = await validate_workspace_layout_at_boot(layout=layout, trace=trace)
    assert "memory" in result.missing_dirs
    assert trace.events[-1].kind == "workspace.layout_ok"
