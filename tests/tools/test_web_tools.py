"""Web search and fetch tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.web import (
    _PROXY_BRAVE_PATH,
    _PROXY_FETCH_PATH,
    HTML_FETCH_CHUNK_CHARS,
    MAX_HTML_FETCH_CHARS,
    _extract_main_html,
    _html_to_markdown_text,
    build_egress_web_headers,
    proxy_post_json,
    reset_proxy_http_client_for_tests,
    serp_tool,
)

_DUTCHNEWS_STYLE_HTML = """
<html><body>
<nav>
  <a href="/">Home</a>
  <a href="/news">News</a>
  <a href="/sport">Sport</a>
  <a href="/business">Business</a>
  <a href="/culture">Culture</a>
</nav>
<div class="site-chrome">
  <a href="/archive">Archive</a>
  <a href="/newsletters">Newsletters</a>
  <a href="/jobs">Jobs</a>
  <a href="/expat">Expat</a>
  <a href="/podcast">Podcast</a>
  <a href="/video">Video</a>
  <a href="/weather">Weather</a>
  <a href="/events">Events</a>
</div>
<article>
  <h1>DutchNews Headline</h1>
  <p>Main article paragraph with useful signal for the operator.</p>
</article>
<footer>
  <a href="/privacy">Privacy</a>
  <a href="/terms">Terms</a>
</footer>
</body></html>
"""

_ARTICLE_ONLY_HTML = """
<div id="readability-page">
  <h1>DutchNews Headline</h1>
  <p>Main article paragraph with useful signal for the operator.</p>
</div>
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="web-sess",
        workspace_path=workspace,
        workspace_id="web-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


def test_web_tools_registered(executor: ToolExecutor) -> None:
    names = {definition.name for definition in executor.definitions()}
    assert {"serp", "web_search", "get_page_content", "web_fetch"} <= names


def test_build_egress_web_headers_injects_tokens() -> None:
    headers = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token="sess-tok",
        proxy_shared_secret="shared-secret",
    )
    assert headers["X-Sevn-Session-Token"] == "sess-tok"
    assert headers["X-Sevn-Proxy-Token"] == "shared-secret"


@pytest.mark.asyncio
async def test_web_fetch_requires_proxy_url(ctx: ToolContext, executor: ToolExecutor) -> None:
    with patch("sevn.tools.web._resolve_process_egress", return_value=(None, None, None)):
        raw = await executor.dispatch(
            ctx,
            ToolCall(name="web_fetch", arguments={"url": "https://example.com"}),
        )
    env = json.loads(raw)
    assert env["ok"] is False
    assert "SEVN_PROXY_URL" in env["error"]
    assert env.get("data", {}).get("fallback_tool") == "serp"


@pytest.mark.asyncio
async def test_web_fetch_dispatches_via_proxy_with_headers(ctx: ToolContext) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        captured.update(kwargs)
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/plain",
            "text": "hello",
            "truncated": False,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "sess-1", "proxy-shared"),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import web_fetch_tool

        result = await web_fetch_tool(ctx, url="https://example.com/page")

    env = json.loads(result)
    assert env["ok"] is True
    assert env["data"]["text"] == "hello"
    assert captured["path"] == _PROXY_FETCH_PATH
    assert captured["headers"]["X-Sevn-Session-Token"] == "sess-1"
    assert captured["headers"]["X-Sevn-Proxy-Token"] == "proxy-shared"


@pytest.mark.asyncio
async def test_web_search_brave_via_proxy(ctx: ToolContext) -> None:
    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        assert kwargs["path"] == _PROXY_BRAVE_PATH
        return 200, {
            "query": "sevn bot",
            "count": 1,
            "results": [{"title": "T", "url": "https://x", "description": "D"}],
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", "sec"),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="sevn bot")

    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["results"][0]["title"] == "T"


def test_extract_main_html_full_passthrough() -> None:
    html = "<html><body><p>keep</p></body></html>"
    assert _extract_main_html(html, mode="full") == html


def test_extract_main_html_auto_without_readability_returns_full() -> None:
    html = "<html><body><article><p>x</p></article></body></html>"
    with patch("sevn.tools.web._HAS_READABILITY", False):
        assert _extract_main_html(html, mode="auto") == html


@pytest.mark.asyncio
async def test_get_page_content_extract_auto_omits_nav_noise(ctx: ToolContext) -> None:
    """News-style HTML: auto extract keeps headline and drops nav/footer link flood."""

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": _DUTCHNEWS_STYLE_HTML,
            "truncated": False,
        }

    def _fake_extract(html: str, *, mode: str) -> str:
        if mode == "auto":
            return _ARTICLE_ONLY_HTML
        return html

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
        patch("sevn.tools.web._extract_main_html", side_effect=_fake_extract),
    ):
        from sevn.tools.web import get_page_content_tool

        raw_auto = await get_page_content_tool(
            ctx,
            url="https://www.dutchnews.nl/",
            extract="auto",
        )
        raw_full = await get_page_content_tool(
            ctx,
            url="https://www.dutchnews.nl/",
            extract="full",
        )

    auto_env = json.loads(raw_auto)
    full_env = json.loads(raw_full)
    assert auto_env["ok"] is True
    assert full_env["ok"] is True

    auto_md = auto_env["data"]["markdown"]
    full_md = full_env["data"]["markdown"]
    assert "DutchNews Headline" in auto_md
    assert "useful signal" in auto_md
    assert "Archive" not in auto_md
    assert "Newsletters" not in auto_md
    assert "Privacy" not in auto_md

    auto_lines = [line for line in auto_md.splitlines() if line.strip()]
    full_lines = [line for line in full_md.splitlines() if line.strip()]
    assert len(auto_lines) <= len(full_lines) * 0.5


@pytest.mark.asyncio
async def test_get_page_content_extract_full_preserves_legacy_nav(ctx: ToolContext) -> None:
    """``extract=full`` skips readability and keeps untagged site chrome."""

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": _DUTCHNEWS_STYLE_HTML,
            "truncated": False,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
        patch("sevn.tools.web._HAS_READABILITY", False),
    ):
        from sevn.tools.web import get_page_content_tool

        raw = await get_page_content_tool(
            ctx,
            url="https://www.dutchnews.nl/",
            extract="full",
        )

    env = json.loads(raw)
    assert env["ok"] is True
    md = env["data"]["markdown"]
    assert "DutchNews Headline" in md
    assert "Archive" in md
    assert "Newsletters" in md


def test_html_to_markdown_thin_output_logs_debug() -> None:
    big_html = "<html><body>" + ("<!-- filler -->" * 400) + "<p>x</p></body></html>"
    assert len(big_html) > 5000
    with patch("sevn.tools.web.debug_event") as mock_debug:
        result = _html_to_markdown_text(big_html, url="https://example.com/long-page")
    assert len(result) < 200
    mock_debug.assert_called_once_with("web.markdownify_thin_output", url_len=29)


@pytest.mark.asyncio
async def test_get_page_content_markdownify(ctx: ToolContext) -> None:
    html = "<html><body><h1>Title</h1><p>Body text</p></body></html>"

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": html,
            "truncated": False,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import get_page_content_tool

        raw = await get_page_content_tool(ctx, url="https://example.com/article")

    env = json.loads(raw)
    assert env["ok"] is True
    assert "# Title" in env["data"]["markdown"]
    assert "Body text" in env["data"]["markdown"]


@pytest.mark.asyncio
async def test_get_page_content_large_html_does_not_report_empty_body(ctx: ToolContext) -> None:
    """Regression: HTML beyond the spill threshold must not surface as 'empty body'.

    Mirrors the real Wikipedia failure — a large HTML shell (head/skin chrome)
    with a small extractable body. Before the fix, the internal ``web_fetch``
    spilled its 40 KB payload to disk, so ``get_page_content`` read no ``text``
    and returned ``"fetched page had empty body"`` with ``status_code: null``.
    """
    big_comment = "<!-- " + ("a" * 50_000) + " -->"
    html = f"<html><head>{big_comment}</head><body><h1>Title</h1><p>Body text</p></body></html>"
    assert len(html) > 32_768  # exceeds TOOL_LARGE_RESULT_THRESHOLD_BYTES

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": html,
            "truncated": False,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import get_page_content_tool

        raw = await get_page_content_tool(ctx, url="https://en.wikipedia.org/wiki/OpenClaw")

    env = json.loads(raw)
    assert env["ok"] is True
    assert "Body text" in env["data"]["markdown"]
    assert env["data"]["status_code"] == 200


@pytest.mark.asyncio
async def test_get_page_content_no_max_length_uses_single_streaming_fetch(ctx: ToolContext) -> None:
    """Without ``max_length`` the proxy receives one streaming fetch (no ``byte_offset``)."""
    captured: list[dict[str, Any]] = []

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        captured.append(dict(kwargs["body"]))
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": "<html><body><p>hi</p></body></html>",
            "truncated": False,
            "streamed": True,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import get_page_content_tool

        raw = await get_page_content_tool(ctx, url="https://example.com/article")

    env = json.loads(raw)
    assert env["ok"] is True
    assert len(captured) == 1
    assert "byte_offset" not in captured[0]
    assert "max_length" not in captured[0]


@pytest.mark.asyncio
async def test_get_page_content_empty_body_still_errors(ctx: ToolContext) -> None:
    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 204,
            "content_type": "text/html",
            "text": "",
            "truncated": False,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import get_page_content_tool

        raw = await get_page_content_tool(ctx, url="https://example.com/empty")

    env = json.loads(raw)
    assert env["ok"] is False
    assert "empty body" in env["error"]
    assert env["data"]["status_code"] == 204


@pytest.mark.asyncio
async def test_web_fetch_large_body_spills(ctx: ToolContext) -> None:
    """``web_fetch`` still spills oversized payloads to disk (unchanged)."""
    text = "x" * 50_000

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/plain",
            "text": text,
            "truncated": False,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import web_fetch_tool

        raw = await web_fetch_tool(ctx, url="https://example.com/big")

    env = json.loads(raw)
    assert env["ok"] is True
    assert "spill_path" in env["data"]


@pytest.mark.asyncio
async def test_serp_returns_structured_results(ctx: ToolContext) -> None:
    fake_rows = [{"title": "A", "href": "https://a", "body": "snippet"}]

    with (
        patch("sevn.tools.web._HAS_DDGS", True),
        patch(
            "sevn.tools.web._serp_search_sync",
            return_value=fake_rows,
        ),
    ):
        raw = await serp_tool(ctx, query="hello world", count=3)

    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["count"] == 1
    assert env["data"]["results"][0]["title"] == "A"


@pytest.mark.asyncio
async def test_proxy_post_json_uses_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[object] = []

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"ok": "yes"}

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self, path: str, *, json: dict[str, Any], headers: dict[str, str], **kwargs: Any
        ) -> _FakeResponse:
            assert path == "/web/fetch"
            assert json["url"] == "https://example.com"
            assert headers["X-Sevn-Session-Token"] == "abc"
            return _FakeResponse()

    def _factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient()
        created.append(client)
        return client

    await reset_proxy_http_client_for_tests()
    monkeypatch.setattr("sevn.tools.web.httpx.AsyncClient", _factory)
    status, data = await proxy_post_json(
        proxy_url="http://proxy.test",
        path="/web/fetch",
        body={"url": "https://example.com"},
        headers={"X-Sevn-Session-Token": "abc"},
    )
    assert status == 200
    assert data["ok"] == "yes"
    assert len(created) == 1


@pytest.mark.asyncio
async def test_proxy_post_json_reuses_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sequential proxy POSTs reuse one module-level ``AsyncClient`` instance."""
    created: list[object] = []

    class _FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"ok": "yes"}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self._kwargs = kwargs

        async def post(
            self, path: str, *, json: dict[str, Any], headers: dict[str, str], **kw: Any
        ) -> _FakeResponse:
            assert path == "/web/fetch"
            return _FakeResponse()

    def _factory(**kwargs: Any) -> _FakeClient:
        client = _FakeClient(**kwargs)
        created.append(client)
        return client

    await reset_proxy_http_client_for_tests()
    monkeypatch.setattr("sevn.tools.web.httpx.AsyncClient", _factory)
    headers = {"X-Sevn-Session-Token": "abc", "Content-Type": "application/json"}
    await proxy_post_json(
        proxy_url="http://proxy.test",
        path="/web/fetch",
        body={"url": "https://example.com/a"},
        headers=headers,
    )
    await proxy_post_json(
        proxy_url="http://proxy.test",
        path="/web/fetch",
        body={"url": "https://example.com/b"},
        headers=headers,
    )
    assert len(created) == 1
    await reset_proxy_http_client_for_tests()


@pytest.mark.asyncio
async def test_streaming_web_fetch_single_proxy_call_assembles_html(ctx: ToolContext) -> None:
    """Default GET fetch issues one proxy call that assembles the full HTML body."""
    full_html = "x" * 30_000
    calls = 0

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        nonlocal calls
        calls += 1
        assert "byte_offset" not in kwargs["body"]
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": full_html,
            "truncated": False,
            "streamed": True,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import web_fetch_tool

        raw = await web_fetch_tool(ctx, url="https://example.com/large")

    env = json.loads(raw)
    assert env["ok"] is True
    assert len(env["data"]["text"]) == 30_000
    assert calls == 1
    assert env["data"]["streamed"] is True
    assert env["data"]["chunks_fetched"] == 1
    assert env["data"]["batched"] is False


@pytest.mark.asyncio
async def test_streaming_web_fetch_truncates_at_one_million() -> None:
    """Single streaming proxy response is capped at ``MAX_HTML_FETCH_CHARS``."""
    huge = "y" * (MAX_HTML_FETCH_CHARS + 5_000)
    calls = 0

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        nonlocal calls
        calls += 1
        assert "byte_offset" not in kwargs["body"]
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": huge[:MAX_HTML_FETCH_CHARS],
            "truncated": True,
            "streamed": True,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import _proxy_web_fetch_batched

        err, data = await _proxy_web_fetch_batched(
            url="https://example.com/huge",
            max_html_chars=MAX_HTML_FETCH_CHARS,
        )

    assert err is None
    assert len(data["text"]) == MAX_HTML_FETCH_CHARS
    assert data["truncated"] is True
    assert data["streamed"] is True
    assert data["chunks_fetched"] == 1
    assert calls == 1


@pytest.mark.asyncio
async def test_proxy_web_fetch_single_byte_offset_still_uses_chunk_api() -> None:
    """Explicit ``byte_offset`` still routes through the legacy Range chunk API."""
    captured: list[dict[str, Any]] = []

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        captured.append(dict(kwargs["body"]))
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 206,
            "content_type": "text/html",
            "text": "chunk",
            "truncated": False,
            "byte_offset": kwargs["body"]["byte_offset"],
            "bytes_returned": 5,
            "eof": True,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import _proxy_web_fetch_single

        err, data = await _proxy_web_fetch_single(
            url="https://example.com/legacy",
            byte_offset=0,
            chunk_length=HTML_FETCH_CHUNK_CHARS,
        )

    assert err is None
    assert len(captured) == 1
    assert captured[0]["byte_offset"] == 0
    assert captured[0]["chunk_length"] == HTML_FETCH_CHUNK_CHARS
    assert data["byte_offset"] == 0
    assert data["eof"] is True


@pytest.mark.asyncio
async def test_get_page_content_passes_low_content_hint(ctx: ToolContext) -> None:
    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": kwargs["body"]["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/html",
            "text": "<html><body><p>tiny</p></body></html>",
            "truncated": False,
            "streamed": True,
            "low_content": True,
        }

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", None),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
    ):
        from sevn.tools.web import get_page_content_tool

        raw = await get_page_content_tool(ctx, url="https://example.com/thin")

    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["low_content"] is True
    assert env["data"]["hint"] == "retry without max_length or use serp for URLs"


# ---------------------------------------------------------------------------
# web_search → serp auto-fallback (readiness routing)
# ---------------------------------------------------------------------------

_SERP_ROWS: list[dict[str, Any]] = [{"title": "T", "href": "https://x", "body": "D"}]


@pytest.mark.asyncio
async def test_web_search_without_proxy_falls_back_to_serp(ctx: ToolContext) -> None:
    """No egress proxy: web_search answers via serp with an annotated payload."""
    with (
        patch("sevn.tools.web._resolve_process_egress", return_value=(None, None, None)),
        patch("sevn.tools.web._HAS_DDGS", True),
        patch("sevn.tools.web._serp_search_sync", return_value=list(_SERP_ROWS)),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="sevn bot")
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["provider"] == "serp"
    assert env["data"]["fallback_from"] == "web_search"
    assert "proxy" in env["data"]["fallback_reason"]
    assert env["data"]["results"] == _SERP_ROWS


@pytest.mark.asyncio
async def test_web_search_brave_key_missing_falls_back_to_serp(ctx: ToolContext) -> None:
    """Proxy 503 brave-not-configured: web_search answers via serp, reason names Brave."""

    async def _fake_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        assert kwargs["path"] == _PROXY_BRAVE_PATH
        return 503, {"detail": "brave not configured"}

    with (
        patch(
            "sevn.tools.web._resolve_process_egress",
            return_value=("http://127.0.0.1:8787", "tok", "sec"),
        ),
        patch("sevn.tools.web.proxy_post_json", side_effect=_fake_proxy_post_json),
        patch("sevn.tools.web._HAS_DDGS", True),
        patch("sevn.tools.web._serp_search_sync", return_value=list(_SERP_ROWS)),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="sevn bot")
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["provider"] == "serp"
    assert "Brave" in env["data"]["fallback_reason"]


@pytest.mark.asyncio
async def test_web_search_fallback_unavailable_keeps_original_error(ctx: ToolContext) -> None:
    """serp cannot run (no ddgs): the original failure envelope is preserved."""
    with (
        patch("sevn.tools.web._resolve_process_egress", return_value=(None, None, None)),
        patch("sevn.tools.web._HAS_DDGS", False),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="sevn bot")
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["data"]["readiness"] == "needs_proxy"
    assert env["data"]["fallback_tool"] == "serp"


@pytest.mark.asyncio
async def test_web_search_serp_exception_keeps_original_error(ctx: ToolContext) -> None:
    """serp raising mid-search must not mask the original Brave failure."""

    def _boom(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("ddgs down")

    with (
        patch("sevn.tools.web._resolve_process_egress", return_value=(None, None, None)),
        patch("sevn.tools.web._HAS_DDGS", True),
        patch("sevn.tools.web._serp_search_sync", side_effect=_boom),
    ):
        from sevn.tools.web import web_search_tool

        raw = await web_search_tool(ctx, query="sevn bot")
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["data"]["fallback_tool"] == "serp"
