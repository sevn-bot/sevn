"""Transport-aware request body adapter (`specs/05-llm-transports.md` §2.3, `specs/07-egress-proxy.md` §5).

Module: sevn.agent.providers.wire
Depends: sevn.agent.providers.transport, sevn.config.model_resolution

Exports:
    adapt_request_for_transport — convert chat-completions-shaped body to transport-native shape.

LCM compaction, memory extractor, dreaming reranker, and CD harness build OpenAI
chat-completions bodies (``{model, messages: [system/user/...]}``). When the resolved
transport for a catalog model is ``AnthropicTransport`` (MiniMax catalog ids, Claude
models routed via Messages), the upstream wire requires Anthropic shape — top-level
``system``, no ``role: system`` inside ``messages``. This helper lifts ``system``
messages out, ensures a sensible ``max_tokens`` floor (MiniMax parity), and strips the
``minimax/`` catalog prefix from ``model``.

Examples:
    >>> from sevn.agent.providers.wire import adapt_request_for_transport
    >>> from sevn.agent.providers.transport import ChatCompletionsTransport
    >>> req = {"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    >>> adapt_request_for_transport(ChatCompletionsTransport(), req) == req
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.config.model_resolution import resolve_wire_model_id
from sevn.proxy.anthropic_body import normalize_anthropic_request_body

if TYPE_CHECKING:
    from sevn.agent.providers.transport import Transport

_ANTHROPIC_MIN_MAX_TOKENS: int = 1024
"""Lower bound for ``max_tokens`` on MiniMax thinking models (legacy MinimaxProvider)."""


def adapt_request_for_transport(
    transport: Transport,
    request: dict[str, object],
) -> dict[str, object]:
    """Return a request body matching ``transport``'s native wire shape.

    Always strips ``minimax/`` from the ``model`` field. For anthropic transports,
    converts chat-completions ``messages`` (with possible ``role: system`` entries)
    into Anthropic shape with top-level ``system`` and applies a ``max_tokens`` floor.
    For other transports, the request is returned with only ``model`` rewritten.

    Args:
        transport (Transport): Resolved proxy-backed transport.
        request (dict[str, object]): Chat-completions-shaped body.

    Returns:
        dict[str, object]: Body ready for ``Transport.complete``.

    Examples:
        >>> from sevn.agent.providers.transport import AnthropicTransport
        >>> out = adapt_request_for_transport(
        ...     AnthropicTransport(),
        ...     {
        ...         "model": "minimax/MiniMax-M2.7",
        ...         "messages": [
        ...             {"role": "system", "content": "S"},
        ...             {"role": "user", "content": "U"},
        ...         ],
        ...     },
        ... )
        >>> out["model"], out["system"], out["max_tokens"] >= 1024
        ('MiniMax-M2.7', 'S', True)
    """
    body = dict(request)
    raw_model = body.get("model")
    if isinstance(raw_model, str):
        body["model"] = resolve_wire_model_id(raw_model)
    if transport.name != "anthropic":
        return body
    body = normalize_anthropic_request_body(body)
    max_tokens = body.get("max_tokens")
    if not isinstance(max_tokens, int) or max_tokens < _ANTHROPIC_MIN_MAX_TOKENS:
        body["max_tokens"] = _ANTHROPIC_MIN_MAX_TOKENS
    return body


__all__ = ["adapt_request_for_transport"]
