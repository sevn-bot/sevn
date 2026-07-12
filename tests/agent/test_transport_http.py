"""Tests for proxy HTTP transport helpers."""

from __future__ import annotations

import httpx
import pytest

from sevn.agent.providers import transport_http
from sevn.agent.providers.transport_http import TransportBadRequest


def test_redacted_request_body_shape_omits_prompt_text() -> None:
    shape = transport_http._redacted_request_body_shape(
        {
            "model": "minimax/MiniMax-M3",
            "system": "secret system",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "secret user prompt"},
                        {"type": "tool_result", "tool_use_id": "t1", "content": "secret"},
                    ],
                },
            ],
            "tools": [{"name": "final_result"}],
        },
    )
    assert shape["model"] == "minimax/MiniMax-M3"
    assert shape["system_chars"] == len("secret system")
    assert shape["messages_count"] == 1
    assert shape["roles"] == ["user"]
    assert "secret" not in str(shape)


@pytest.mark.asyncio
async def test_post_llm_json_raises_transport_bad_request_on_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            request = httpx.Request("POST", url)
            return httpx.Response(
                400,
                request=request,
                json={"error": "bad messages"},
            )

    monkeypatch.setattr(transport_http.httpx, "AsyncClient", lambda **_: FakeClient())

    with pytest.raises(transport_http.TransportBadRequest):
        await transport_http.post_llm_json(
            base_url="http://proxy.test",
            path="/llm/anthropic/messages",
            headers={},
            body={"model": "minimax/MiniMax-M3", "messages": []},
        )


@pytest.mark.asyncio
async def test_post_llm_json_400_with_json_error_body_logs_type_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """400 with a JSON error body must log error.type + error.message and still raise."""
    from loguru import logger as loguru_logger

    error_body = {
        "error": {
            "type": "invalid_request_error",
            "message": "tool_use:find_file is not in tools list",
        }
    }

    class FakeClientWithBody:
        async def __aenter__(self) -> FakeClientWithBody:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            request = httpx.Request("POST", url)
            return httpx.Response(
                400,
                request=request,
                json=error_body,
            )

    monkeypatch.setattr(transport_http.httpx, "AsyncClient", lambda **_: FakeClientWithBody())

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="WARNING")
    try:
        with pytest.raises(TransportBadRequest):
            await transport_http.post_llm_json(
                base_url="http://proxy.test",
                path="/llm/anthropic/messages",
                headers={},
                body={"model": "minimax/MiniMax-M3", "messages": []},
            )
    finally:
        loguru_logger.remove(sink_id)

    log_text = " ".join(captured)
    assert "invalid_request_error" in log_text, f"expected error.type in log; got: {log_text}"
    assert "find_file" in log_text, f"expected error.message fragment in log; got: {log_text}"


@pytest.mark.asyncio
async def test_post_llm_json_400_without_json_body_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """400 with a non-JSON body must still raise ``TransportBadRequest`` gracefully."""

    class FakeClientNoJson:
        async def __aenter__(self) -> FakeClientNoJson:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, object],
            headers: dict[str, str],
        ) -> httpx.Response:
            request = httpx.Request("POST", url)
            return httpx.Response(
                400,
                request=request,
                content=b"Bad Request",
                headers={"content-type": "text/plain"},
            )

    monkeypatch.setattr(transport_http.httpx, "AsyncClient", lambda **_: FakeClientNoJson())

    with pytest.raises(TransportBadRequest):
        await transport_http.post_llm_json(
            base_url="http://proxy.test",
            path="/llm/anthropic/messages",
            headers={},
            body={"model": "minimax/MiniMax-M3", "messages": []},
        )
