"""LLM provider integrations.

Module: sevn.agent.providers
Depends: sevn.agent.providers.budget, sevn.agent.providers.resolve, sevn.agent.providers.transport

Exports:
    BudgetRegime — subscription / per-token / free-local enum.
    ModelBudget — per-model budget metadata.
    resolve_model — stable import surface for model/transport binding.
    AnthropicTransport — Anthropic Messages via proxy.
    AnthropicMessagesTransport — Anthropic Messages alias for tier-B serializers.
    BedrockTransport — Bedrock Converse via proxy.
    ChatCompletionsTransport — OpenAI-style chat via proxy.
    ResponsesApiTransport — OpenAI Responses via proxy.
    Transport — provider protocol.

Examples:
    >>> from sevn.agent import providers
    >>> providers.ChatCompletionsTransport().name
    'chat_completions'
"""

from __future__ import annotations

from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.resolve import resolve_model
from sevn.agent.providers.transport import (
    AnthropicMessagesTransport,
    AnthropicTransport,
    BedrockTransport,
    ChatCompletionsTransport,
    ResponsesApiTransport,
    Transport,
)
from sevn.agent.providers.wire import adapt_request_for_transport

__all__ = [
    "AnthropicMessagesTransport",
    "AnthropicTransport",
    "BedrockTransport",
    "BudgetRegime",
    "ChatCompletionsTransport",
    "ModelBudget",
    "ResponsesApiTransport",
    "Transport",
    "adapt_request_for_transport",
    "resolve_model",
]
