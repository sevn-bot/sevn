"""Egress proxy ``web_fetch_json`` truncation semantics (`specs/07-egress-proxy.md`)."""

from __future__ import annotations

from typing import Any

import pytest

from sevn.proxy import web_forward
from sevn.proxy.web_forward import MAX_HTML_FETCH_CHARS


class _FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        status_code: int = 200,
        content: bytes | None = None,
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/plain"}
        self.content = content if content is not None else text.encode("utf-8")


class _FakeStreamResponse:
    def __init__(
        self,
        text: str,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = text.encode("utf-8")
        self.status_code = status_code
        self.headers = {"content-type": "text/plain", **(headers or {})}

    async def aiter_bytes(self) -> Any:
        chunk_size = 4096
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset : offset + chunk_size]


class _FakeStreamCtx:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _FakeClient:
    def __init__(self, text: str, *, status_code: int = 200) -> None:
        self._text = text
        self._status_code = status_code
        self.last_headers: dict[str, str] | None = None
        self.request_count = 0
        self.stream_count = 0

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def stream(self, method: str, url: str, **kwargs: Any) -> _FakeStreamCtx:
        self.stream_count += 1
        headers = kwargs.get("headers") or {}
        self.last_headers = dict(headers)
        return _FakeStreamCtx(_FakeStreamResponse(self._text, status_code=self._status_code))

    async def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.request_count += 1
        headers = kwargs.get("headers") or {}
        self.last_headers = dict(headers)
        if headers.get("Range") and self._status_code == 416:
            return _FakeResponse("", status_code=416)
        if headers.get("Range"):
            range_val = headers["Range"]
            start_s, end_s = range_val.removeprefix("bytes=").split("-", 1)
            start = int(start_s)
            end = int(end_s)
            chunk = self._text.encode("utf-8")[start : end + 1]
            return _FakeResponse(chunk.decode("utf-8"), content=chunk)
        return _FakeResponse(self._text, status_code=self._status_code)


class _RangeIgnoredClient(_FakeClient):
    """Simulates upstream that ignores Range and returns the full body on 200."""

    async def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.request_count += 1
        headers = kwargs.get("headers") or {}
        self.last_headers = dict(headers)
        if headers.get("Range"):
            return _FakeResponse(self._text, content=self._text.encode("utf-8"))
        return _FakeResponse(self._text, content=self._text.encode("utf-8"))


class _FallbackClient:
    """Returns 416 on Range, full body on second request."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.request_count = 0
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self) -> _FallbackClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.request_count += 1
        headers = kwargs.get("headers") or {}
        self.last_headers = dict(headers)
        if headers.get("Range"):
            return _FakeResponse("", status_code=416)
        return _FakeResponse(self._text, content=self._text.encode("utf-8"))


class _SequentialStreamClient:
    """Returns a sequence of stream responses for low-content retry tests."""

    def __init__(
        self,
        responses: list[tuple[str, int, dict[str, str] | None]],
    ) -> None:
        self._responses = responses
        self.stream_count = 0
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self) -> _SequentialStreamClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def stream(self, method: str, url: str, **kwargs: Any) -> _FakeStreamCtx:
        self.stream_count += 1
        self.last_headers = dict(kwargs.get("headers") or {})
        idx = min(self.stream_count - 1, len(self._responses) - 1)
        text, status, extra_headers = self._responses[idx]
        return _FakeStreamCtx(_FakeStreamResponse(text, status_code=status, headers=extra_headers))

    async def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        raise AssertionError("sequential stream client should not use request()")


@pytest.mark.asyncio
async def test_web_fetch_json_no_max_length_returns_full_body(monkeypatch: Any) -> None:
    body = "y" * 600_000  # well past the former 512 KB ceiling
    client = _FakeClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json({"url": "https://example.com"})

    assert status == 200
    assert payload["truncated"] is False
    assert payload["streamed"] is True
    assert len(payload["text"]) == len(body)
    assert client.stream_count == 1
    assert client.request_count == 0


@pytest.mark.asyncio
async def test_web_fetch_json_explicit_max_length_truncates(monkeypatch: Any) -> None:
    body = "z" * 5_000
    client = _FakeClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json(
        {"url": "https://example.com", "max_length": 1_000}
    )

    assert status == 200
    assert payload["truncated"] is True
    assert payload["streamed"] is True
    assert len(payload["text"]) == 1_000
    assert client.stream_count == 1


@pytest.mark.asyncio
async def test_web_fetch_json_streaming_truncates_at_cap(monkeypatch: Any) -> None:
    """Mock httpx stream with 50k body; 30k cap truncates (eof implied)."""
    body = "x" * 50_000
    client = _FakeClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json(
        {"url": "https://example.com", "max_length": 30_000}
    )

    assert status == 200
    assert payload["truncated"] is True
    assert payload["streamed"] is True
    assert len(payload["text"]) == 30_000
    assert client.stream_count == 1
    assert client.request_count == 0


@pytest.mark.asyncio
async def test_web_fetch_json_chunk_mode_sets_range_header(monkeypatch: Any) -> None:
    body = "a" * 25_000
    client = _FakeClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json(
        {"url": "https://example.com", "byte_offset": 10_000, "chunk_length": 10_000}
    )

    assert status == 200
    assert client.last_headers is not None
    assert client.last_headers["Range"] == "bytes=10000-19999"
    assert payload["byte_offset"] == 10_000
    assert payload["bytes_returned"] == 10_000
    assert payload["eof"] is False
    assert len(payload["text"]) == 10_000


@pytest.mark.asyncio
async def test_web_fetch_json_chunk_mode_eof_on_short_final_chunk(monkeypatch: Any) -> None:
    body = "b" * 15_000
    client = _FakeClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json(
        {"url": "https://example.com", "byte_offset": 10_000, "chunk_length": 10_000}
    )

    assert status == 200
    assert payload["bytes_returned"] == 5_000
    assert payload["eof"] is True


@pytest.mark.asyncio
async def test_web_fetch_json_chunk_mode_416_falls_back_to_full_body(monkeypatch: Any) -> None:
    body = "c" * 5_000
    client = _FallbackClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json(
        {"url": "https://example.com", "byte_offset": 0, "chunk_length": 10_000}
    )

    assert status == 200
    assert client.request_count == 2
    assert payload["eof"] is True
    assert payload["text"] == body
    assert payload["bytes_returned"] == len(body.encode("utf-8"))


@pytest.mark.asyncio
async def test_web_fetch_json_chunk_mode_range_ignored_falls_back(monkeypatch: Any) -> None:
    body = "d" * (MAX_HTML_FETCH_CHARS + 500)
    client = _RangeIgnoredClient(body)

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json(
        {"url": "https://example.com", "byte_offset": 0, "chunk_length": 10_000}
    )

    assert status == 200
    assert payload["eof"] is True
    assert payload["truncated"] is True
    assert len(payload["text"]) == MAX_HTML_FETCH_CHARS


@pytest.mark.asyncio
async def test_web_fetch_json_reuses_injected_client() -> None:
    """Two sequential fetches with the same injected client reuse one instance."""
    shared = _FakeClient("first")
    status_a, payload_a = await web_forward.web_fetch_json(
        {"url": "https://example.com/a"},
        client=shared,
    )
    status_b, payload_b = await web_forward.web_fetch_json(
        {"url": "https://example.com/b"},
        client=shared,
    )
    assert status_a == 200
    assert status_b == 200
    assert payload_a["text"] == "first"
    assert payload_b["text"] == "first"
    assert shared.stream_count == 2
    assert shared.request_count == 0


@pytest.mark.asyncio
async def test_web_fetch_json_scales_read_timeout_for_large_cap() -> None:
    """Large ``max_length`` requests use a scaled read timeout on the stream."""
    from sevn.proxy.http_client import build_proxy_upstream_timeout

    expected = build_proxy_upstream_timeout(max_html_chars=1_000_000)
    captured: list[Any] = []

    class _TimeoutCapturingClient(_FakeClient):
        def stream(self, method: str, url: str, **kwargs: Any) -> _FakeStreamCtx:
            captured.append(kwargs.get("timeout"))
            return super().stream(method, url, **kwargs)

    client = _TimeoutCapturingClient("body")
    await web_forward.web_fetch_json(
        {"url": "https://example.com", "max_length": 1_000_000},
        client=client,
    )
    assert captured == [expected]
    assert expected.read == 50.0


@pytest.mark.asyncio
async def test_web_fetch_json_default_headers(monkeypatch: Any) -> None:
    client = _FakeClient("body")

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    await web_forward.web_fetch_json({"url": "https://example.com"})

    assert client.last_headers is not None
    assert client.last_headers["Accept"] == web_forward._DEFAULT_ACCEPT
    assert client.last_headers["Accept-Language"] == web_forward._DEFAULT_ACCEPT_LANGUAGE
    assert client.last_headers["User-Agent"] == web_forward._DEFAULT_UA


@pytest.mark.asyncio
async def test_web_fetch_json_caller_headers_override_defaults(monkeypatch: Any) -> None:
    client = _FakeClient("body")

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    await web_forward.web_fetch_json(
        {
            "url": "https://example.com",
            "headers": {"User-Agent": "custom-agent", "X-Test": "1"},
        }
    )

    assert client.last_headers is not None
    assert client.last_headers["User-Agent"] == "custom-agent"
    assert client.last_headers["X-Test"] == "1"
    assert client.last_headers["Accept"] == web_forward._DEFAULT_ACCEPT


@pytest.mark.asyncio
async def test_web_fetch_json_206_retries_once_with_full_body(monkeypatch: Any) -> None:
    partial_css = "body{color:red}" * 20
    full_html = "<html><body><h1>Headlines</h1>" + ("x" * 5_000) + "</body></html>"
    client = _SequentialStreamClient(
        [
            (partial_css, 206, {"content-range": f"bytes 0-{len(partial_css) - 1}/50000"}),
            (full_html, 200, {"content-length": str(len(full_html.encode()))}),
        ]
    )

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json({"url": "https://dutchnews.nl/"})

    assert status == 200
    assert client.stream_count == 2
    assert payload["status_code"] == 200
    assert "Headlines" in payload["text"]
    assert payload["low_content"] is False


@pytest.mark.asyncio
async def test_web_fetch_json_thin_body_with_content_length_retries(monkeypatch: Any) -> None:
    thin = "a" * 500
    full = "b" * 8_000
    client = _SequentialStreamClient(
        [
            (thin, 200, {"content-length": "50000"}),
            (full, 200, {"content-length": str(len(full.encode()))}),
        ]
    )

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json({"url": "https://example.com/"})

    assert status == 200
    assert client.stream_count == 2
    assert len(payload["text"]) == 8_000
    assert payload["low_content"] is False


@pytest.mark.asyncio
async def test_web_fetch_json_low_content_when_retry_still_thin(monkeypatch: Any) -> None:
    thin = "c" * 400
    client = _SequentialStreamClient(
        [
            (thin, 200, {"content-length": "50000"}),
            (thin, 200, {"content-length": "50000"}),
        ]
    )

    monkeypatch.setattr(
        web_forward.httpx,
        "AsyncClient",
        lambda *a, **k: client,
    )

    status, payload = await web_forward.web_fetch_json({"url": "https://example.com/thin"})

    assert status == 200
    assert client.stream_count == 2
    assert payload["low_content"] is True
    assert len(payload["text"]) == 400
