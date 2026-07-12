"""Wave W6 readiness: web errors, PDF fallback, terminal streaming."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.terminal import (
    MAX_TERMINAL_TIMEOUT_S,
    _run_sync,
    reset_terminal_store_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_terminal() -> None:
    reset_terminal_store_for_tests()
    yield
    reset_terminal_store_for_tests()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="w6-sess",
        workspace_path=workspace,
        workspace_id="w6-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _ = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_web_fetch_proxy_unset_suggests_serp(
    ctx: ToolContext, executor: ToolExecutor
) -> None:
    with patch("sevn.tools.web._resolve_process_egress", return_value=(None, None, None)):
        raw = await executor.dispatch(
            ctx,
            ToolCall(name="web_fetch", arguments={"url": "https://example.com"}),
        )
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == ToolResultCode.PERMISSION_DENIED.value
    assert "serp" in env["error"].lower()
    assert env.get("data", {}).get("fallback_tool") == "serp"


@pytest.mark.asyncio
async def test_web_search_brave_key_missing(ctx: ToolContext) -> None:
    """Missing Brave key auto-answers via serp; the error surfaces only when serp can't run."""

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 503, {"detail": "brave not configured"}

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
        patch(
            "sevn.tools.web._serp_search_sync",
            return_value=[{"title": "T", "href": "https://x", "body": "D"}],
        ),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="news")

    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["provider"] == "serp"
    assert env["data"]["fallback_from"] == "web_search"
    assert "brave" in env["data"]["fallback_reason"].lower()

    # Without ddgs the original PERMISSION_DENIED envelope is preserved.
    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
        patch("sevn.tools.web._HAS_DDGS", False),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="news")

    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == ToolResultCode.PERMISSION_DENIED.value
    assert "brave" in env["error"].lower()
    assert env.get("data", {}).get("fallback_tool") == "serp"


@pytest.mark.asyncio
async def test_load_tool_web_search_includes_readiness(
    ctx: ToolContext, executor: ToolExecutor
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="load_tool", arguments={"name": "web_search"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    readiness = env["data"].get("readiness")
    assert isinstance(readiness, dict)
    assert readiness.get("status") == "needs_key"
    assert "serp" in str(readiness.get("note", "")).lower()


def test_pdf_fpdf2_fallback_renders_table() -> None:
    from sevn.pdf.fallback_render import render_pdf_fpdf2_fallback

    md = "# Report\n\n| Col A | Col B |\n|---|---|\n| 1 | 2 |\n\nFooter text"
    blob = render_pdf_fpdf2_fallback(markdown=md)
    assert blob is not None
    assert blob.startswith(b"%PDF")


def test_pdf_fpdf2_fallback_renders_em_dash() -> None:
    from sevn.pdf.fallback_render import render_pdf_fpdf2_fallback

    blob = render_pdf_fpdf2_fallback(markdown="Intro \u2014 body with smart \u201cquotes\u201d")
    assert blob is not None
    assert blob.startswith(b"%PDF")
    assert len(blob) > 100


def test_pdf_fpdf2_fallback_renders_cjk_without_crash() -> None:
    from sevn.pdf.fallback_render import render_pdf_fpdf2_fallback

    blob = render_pdf_fpdf2_fallback(markdown="# Title\n\n\u4e2d\u6587\u5185\u5bb9")
    assert blob is not None
    assert blob.startswith(b"%PDF")
    assert len(blob) > 100


def test_pdf_render_falls_back_when_weasyprint_empty() -> None:
    from sevn.pdf.render import render_pdf_bytes

    with patch("sevn.pdf.render.rasterise_pdf_bytes", return_value=b""):
        ok, result = render_pdf_bytes(markdown="# Hello\n\nWorld")
    assert ok is True
    assert isinstance(result, bytes)
    assert result.startswith(b"%PDF")


def test_run_sync_returns_partial_on_timeout() -> None:
    child = MagicMock()
    child.before = "partial-output"
    import pexpect

    def _always_timeout(*args: object, **kwargs: object) -> int:
        raise pexpect.exceptions.TIMEOUT("timed out")

    child.expect.side_effect = _always_timeout

    output, timed_out = _run_sync(child=child, command="sleep 999", timeout_s=0.05)
    assert timed_out is True
    assert "partial-output" in output


def test_max_terminal_timeout_raised() -> None:
    assert MAX_TERMINAL_TIMEOUT_S >= 300.0


@pytest.mark.asyncio
async def test_terminal_run_respects_raised_timeout(ctx: ToolContext) -> None:
    from sevn.tools import terminal as terminal_mod

    captured: dict[str, float] = {}

    def _fake_run_sync(*, child: Any, command: str, timeout_s: float) -> tuple[str, bool]:
        _ = (child, command)
        captured["timeout_s"] = timeout_s
        return ("done", False)

    with patch.object(terminal_mod, "_run_sync", side_effect=_fake_run_sync):
        from sevn.tools.terminal import terminal_run_tool

        raw = await terminal_run_tool(
            ctx,
            command="echo hi",
            timeout_s=180.0,
            prefer_sandbox=False,
        )

    env = json.loads(raw)
    assert env["ok"] is True
    assert captured["timeout_s"] == 180.0
