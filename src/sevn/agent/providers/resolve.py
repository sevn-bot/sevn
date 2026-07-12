"""Resolve ``(model_id, transport)`` pairs for outbound LLM calls.

Module: sevn.agent.providers.resolve
Depends: sevn.agent.providers.transport, sevn.config.settings

Exports:
    resolve_model — map a transport name to a concrete `Transport` instance.

Examples:
    >>> mid, t = resolve_model(model_id="claude-test", transport_name="anthropic")
    >>> mid
    'claude-test'
    >>> t.name
    'anthropic'
"""

from __future__ import annotations

from typing import cast

from sevn.agent.providers.transport import (
    AnthropicTransport,
    BedrockTransport,
    ChatCompletionsTransport,
    ResponsesApiTransport,
    Transport,
)
from sevn.config.settings import ProcessSettings

_TRANSPORT_FACTORIES: dict[
    str,
    type[AnthropicTransport | BedrockTransport | ChatCompletionsTransport | ResponsesApiTransport],
] = cast(
    "dict[str, type[AnthropicTransport | BedrockTransport | ChatCompletionsTransport | ResponsesApiTransport]]",
    {
        "anthropic": AnthropicTransport,
        "chat_completions": ChatCompletionsTransport,
        "responses_api": ResponsesApiTransport,
        "bedrock": BedrockTransport,
    },
)


def resolve_model(
    *,
    model_id: str,
    transport_name: str,
    proxy_base_url: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str, Transport]:
    """Bind a model id to a transport implementation (spec 05 proxy-backed).

        Args:
    model_id (str): Workspace-resolved model identifier to forward to the proxy.
    transport_name (str): One of ``anthropic``, ``chat_completions``, ``responses_api``,
                ``bedrock`` (case-insensitive).
    proxy_base_url (str | None): Egress proxy origin; default ``ProcessSettings.proxy_url``.
    extra_headers (dict[str, str] | None): Extra headers on every LLM call (e.g. session).

        Returns:
            tuple[str, Transport]: ``model_id`` and a fresh transport instance.

        Raises:
            ValueError: If ``transport_name`` is unknown.

        Examples:
            >>> resolve_model(model_id="m", transport_name="CHAT_COMPLETIONS")[1].name
            'chat_completions'
    """
    key = transport_name.strip().lower()
    if key == "responses":
        key = "responses_api"
    try:
        cls = _TRANSPORT_FACTORIES[key]
    except KeyError as exc:
        known = ", ".join(sorted(_TRANSPORT_FACTORIES))
        msg = f"unknown transport_name={transport_name!r}; expected one of: {known}"
        raise ValueError(msg) from exc
    base = proxy_base_url
    if base is None:
        raw = ProcessSettings().proxy_url
        base = raw if raw else None
    return model_id, cast("Transport", cls(proxy_base_url=base, extra_headers=extra_headers))
