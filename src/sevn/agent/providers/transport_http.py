"""HTTP helpers for proxy-backed LLM transports (non-streaming + SSE streaming).

Module: sevn.agent.providers.transport_http
Depends: httpx, json

Exports:
    TransportBadRequest — typed proxy HTTP 400 for LLM POST failures.
    post_llm_json — single POST returning parsed JSON.
    iter_llm_sse — async iterator over ``data:`` JSON lines (OpenAI-style SSE).

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(post_llm_json)
    True
    >>> inspect.isasyncgenfunction(iter_llm_sse)
    True
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from loguru import logger


class TransportBadRequest(httpx.HTTPStatusError):
    """Proxy rejected an LLM request with HTTP 400.

    Raised by :func:`post_llm_json` after logging a redacted summary of the
    request body shape (roles, block types, sizes — no message text).
    """


def _redacted_request_body_shape(body: dict[str, Any]) -> dict[str, Any]:
    """Summarize an LLM request body without leaking prompt or tool arguments.

    Args:
        body (dict[str, Any]): Provider-shaped JSON request body.

    Returns:
        dict[str, Any]: Redaction-safe shape metadata for logs.

    Examples:
        >>> shape = _redacted_request_body_shape({
        ...     "model": "minimax/MiniMax-M3",
        ...     "messages": [{"role": "user", "content": "secret prompt"}],
        ...     "tools": [{"name": "final_result"}],
        ... })
        >>> shape["model"], shape["messages_count"], shape["roles"]
        ('minimax/MiniMax-M3', 1, ['user'])
        >>> shape["tools_count"]
        1
    """
    shape: dict[str, Any] = {}
    model = body.get("model")
    if model is not None:
        shape["model"] = str(model)
    system = body.get("system")
    if isinstance(system, str):
        shape["system_chars"] = len(system)
    elif isinstance(system, list):
        shape["system_blocks"] = len(system)
    tools = body.get("tools")
    if isinstance(tools, list):
        shape["tools_count"] = len(tools)
    tool_config = body.get("toolConfig")
    if isinstance(tool_config, dict):
        nested = tool_config.get("tools")
        if isinstance(nested, list):
            shape["tools_count"] = len(nested)
    messages = body.get("messages")
    if isinstance(messages, list):
        shape["messages_count"] = len(messages)
        roles: list[str] = []
        block_types: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            roles.append(str(msg.get("role", "?")))
            content = msg.get("content")
            if isinstance(content, str):
                block_types.append(f"text:{len(content)}")
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        block_types.append("?")
                        continue
                    kind = block.get("type")
                    if kind == "text":
                        text = block.get("text")
                        block_types.append(f"text:{len(str(text or ''))}")
                    elif kind == "tool_use":
                        block_types.append(f"tool_use:{block.get('name', '?')}")
                    elif kind == "tool_result":
                        block_types.append("tool_result")
                    elif kind == "thinking":
                        think = block.get("thinking", block.get("text", ""))
                        block_types.append(f"thinking:{len(str(think or ''))}")
                    else:
                        block_types.append(str(kind or "?"))
        shape["roles"] = roles
        shape["block_types"] = block_types
    return shape


async def post_llm_json(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """POST JSON to ``{base_url}{path}`` and return the response JSON object.

        Args:
    base_url (str): Egress proxy origin with no trailing slash.
    path (str): Path beginning with ``/``.
    headers (dict[str, str]): Merged request headers.
    body (dict): JSON-serializable provider-shaped body.
    timeout_s (float): Client timeout in seconds.

        Returns:
    dict[str, Any]: Parsed JSON object.

        Raises:
    TransportBadRequest: On HTTP 400 (logged with redacted body shape).
    httpx.HTTPStatusError: On other non-success status (caller may translate).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(post_llm_json)
            True
    """
    url = f"{base_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(url, json=body, headers=headers)
        if response.status_code == 400:
            shape = _redacted_request_body_shape(body)
            error_info: dict[str, object] = {}
            try:
                resp_json = response.json()
                if isinstance(resp_json, dict):
                    err = resp_json.get("error")
                    if isinstance(err, dict):
                        if "type" in err:
                            error_info["error.type"] = str(err["type"])
                        if "message" in err:
                            error_info["error.message"] = str(err["message"])
            except (ValueError, TypeError):
                logger.debug(
                    "llm_transport_bad_request error body not parseable path={}",
                    path,
                )
            logger.warning(
                "llm_transport_bad_request path={} shape={} error_info={}",
                path,
                shape,
                error_info,
            )
            raise TransportBadRequest(
                f"LLM proxy returned 400 for {path}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            msg = f"expected JSON object from proxy, got {type(data).__name__}"
            raise TypeError(msg)
        return data


async def iter_llm_sse(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_s: float = 120.0,
) -> AsyncIterator[dict[str, Any]]:
    """Stream SSE chunks where each ``data:`` line is a JSON object.

        Args:
    base_url (str): Egress proxy origin with no trailing slash.
    path (str): Path beginning with ``/``.
    headers (dict[str, str]): Merged request headers.
    body (dict): Request body; ``stream: True`` should already be set by caller.
    timeout_s (float): Client timeout in seconds.

        Yields:
    dict[str, Any]: Parsed JSON from each ``data:`` line (skips ``[DONE]``).

        Returns:
    collections.abc.AsyncIterator[dict[str, Any]]: Async generator of chunk dicts.

        Examples:
            >>> import inspect
            >>> inspect.isasyncgenfunction(iter_llm_sse)
            True
    """
    url = f"{base_url.rstrip('/')}{path}"
    async with (
        httpx.AsyncClient(timeout=timeout_s) as client,
        client.stream("POST", url, json=body, headers=headers) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[line.find(":") + 1 :].strip()
            if payload == "[DONE]":
                break
            yield json.loads(payload)
