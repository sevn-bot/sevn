"""Forward primitive header-sanitizing tests (P1 defensive guard + P3 logging).

Locks the belt-and-braces guard in :func:`sevn.proxy.forward.post_json` /
:func:`sevn.proxy.forward.post_sse_stream`: an inbound ``content-length`` / ``host``
/ ``transfer-encoding`` in the ``headers`` dict must never reach the outgoing httpx
request (root cause of the Codex OAuth HTTP 500, ``LocalProtocolError``). Also
covers the Responses-shaped summary used by the upstream log line (P3).
"""

from __future__ import annotations

import functools
from typing import Any

import httpx
import pytest

from sevn.proxy import forward
from sevn.proxy.forward import (
    _sanitize_outbound_headers,
    post_json,
    post_sse_stream,
    summarize_request_body,
)

# --- P1: helper drops framing headers without mutating the caller's dict ------


def test_sanitize_outbound_headers_drops_framing_case_insensitive() -> None:
    src = {"Content-Length": "9", "HOST": "evil", "Transfer-Encoding": "chunked", "x-api-key": "k"}
    out = _sanitize_outbound_headers(src)
    assert out == {"x-api-key": "k"}
    # Caller's dict is untouched.
    assert "Content-Length" in src
    assert "HOST" in src


def _capturing_client_factory(captured: dict[str, Any]) -> Any:
    """Return an ``httpx.AsyncClient`` factory that records the outgoing request headers."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    return functools.partial(httpx.AsyncClient, transport=transport)


@pytest.mark.anyio
async def test_post_json_strips_framing_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """``post_json`` never forwards an inbound ``content-length`` / ``host``."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(forward.httpx, "AsyncClient", _capturing_client_factory(captured))

    await post_json(
        url="https://upstream.example/v1",
        headers={"content-length": "285", "host": "127.0.0.1:8787", "authorization": "Bearer t"},
        body={"model": "M", "messages": [{"role": "user", "content": "hi"}]},
    )

    sent = {k.lower(): v for k, v in captured["headers"].items()}
    # httpx recomputes content-length/host from the body+URL — assert ours did not
    # carry the stale inbound values.
    assert sent.get("content-length") != "285"
    assert sent.get("host") != "127.0.0.1:8787"
    assert sent.get("authorization") == "Bearer t"


@pytest.mark.anyio
async def test_post_sse_stream_strips_framing_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """``post_sse_stream`` never forwards an inbound ``content-length`` / ``host``."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(forward.httpx, "AsyncClient", _capturing_client_factory(captured))

    client, resp = await post_sse_stream(
        url="https://upstream.example/v1",
        headers={"content-length": "999", "host": "127.0.0.1:8787", "authorization": "Bearer t"},
        body={"model": "M", "messages": [], "stream": True},
    )
    await resp.aread()
    await resp.aclose()
    await client.aclose()

    sent = {k.lower(): v for k, v in captured["headers"].items()}
    assert sent.get("content-length") != "999"
    assert sent.get("host") != "127.0.0.1:8787"
    assert sent.get("authorization") == "Bearer t"


# --- P3: Responses-shaped bodies summarise their own shape (not messages_count=0)


def test_summarize_request_body_detects_responses_shape() -> None:
    summary = summarize_request_body(
        {
            "model": "gpt-5.5",
            "instructions": "be terse",
            "input": [{"role": "user"}, {"role": "assistant"}],
            "include": ["reasoning.encrypted_content"],
        }
    )
    assert summary["wire_format"] == "responses"
    assert summary["input_count"] == 2
    assert summary["instructions_chars"] == len("be terse")
    assert summary["include"] == ["reasoning.encrypted_content"]
    # The misleading chat-completions key is absent for Responses bodies.
    assert "messages_count" not in summary


def test_summarize_request_body_chat_shape_unchanged() -> None:
    summary = summarize_request_body(
        {"model": "M", "messages": [{"role": "user", "content": "hi"}], "stream": False}
    )
    assert summary["messages_count"] == 1
    assert summary["messages_roles"] == ["user"]
    assert "wire_format" not in summary
