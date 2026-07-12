"""LLM and offline providers for README section generation.

Module: sevn.docs.readme.providers
Depends: asyncio, tomllib, jinja2, sevn.agent.providers.resolve, sevn.docs.readme.render

Exports:
    ReadmeProviderConfig — transport/model/offline settings.
    SectionProvider — protocol for section renderers.
    OfflineProvider — deterministic template-only section bodies.
    LlmProvider — LLM polish via egress proxy + Transport (no provider keys).
    build_provider — factory from config.

Examples:
    >>> from sevn.docs.readme.providers import OfflineProvider
    >>> p = OfflineProvider()
    >>> p.render_section_sync("summary", {"title": "Gateway", "profile": "subsystem",
    ...     "context_json": "{}"})
    'Gateway — see manifest summary.'
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import Any, Protocol

from jinja2 import Environment, select_autoescape

from sevn.agent.providers.resolve import resolve_model
from sevn.agent.providers.transport import Transport
from sevn.docs.readme.paths import prompts_dir

_TRANSPORT_ALIASES: dict[str, str] = {
    "anthropic": "anthropic",
    "openai_chat": "chat_completions",
    "openai_responses": "responses_api",
    "bedrock_converse": "bedrock",
}


@dataclass(frozen=True)
class ReadmeProviderConfig:
    """Config-driven provider settings (mirrors ``docs.readme.*``)."""

    offline: bool = True
    model: str = "claude-sonnet-4-6"
    transport: str = "anthropic"
    temperature: float = 0.2
    proxy_base_url: str | None = None


class SectionProvider(Protocol):
    """Section renderer — offline sync or LLM async."""

    async def render_section(self, prompt_name: str, variables: dict[str, Any]) -> str:
        """Render one section body from a prompt file and variables.

                Args:
        prompt_name (str): Prompt stem (e.g. ``summary``).
        variables (dict[str, Any]): Template variables.

                Returns:
                    str: Section body text.

                Examples:
                    >>> import asyncio
                    >>> asyncio.run(OfflineProvider().render_section("summary", {"title": "X"}))
                    'X — see manifest summary.'
        """
        ...


class OfflineProvider:
    """Deterministic offline section bodies (no network, no API keys)."""

    def render_section_sync(self, prompt_name: str, variables: dict[str, Any]) -> str:
        """Return a deterministic stub for ``prompt_name``.

                Args:
        prompt_name (str): Prompt stem (e.g. ``summary``).
        variables (dict[str, Any]): Template variables.

                Returns:
                    str: Section body text.

                Examples:
                    >>> OfflineProvider().render_section_sync(
                    ...     "summary",
                    ...     {"title": "Gateway", "profile": "subsystem", "context_json": "{}"},
                    ... )
                    'Gateway — see manifest summary.'
        """
        title = str(variables.get("title", "README"))
        summary = str(variables.get("summary", ""))
        if prompt_name == "summary":
            return summary or f"{title} — see manifest summary."
        if prompt_name in {"overview", "how-it-works", "deep-dive"}:
            excerpt = str(variables.get("source_excerpt", variables.get("context_json", "")))
            return excerpt or f"Offline scaffold for {title} ({prompt_name})."
        if prompt_name == "root-valueprop":
            return str(variables.get("value_prop", summary or title))
        if prompt_name == "highlights":
            highlights = variables.get("highlights")
            if isinstance(highlights, list):
                return "\n".join(f"- {item}" for item in highlights)
        return summary or title

    async def render_section(self, prompt_name: str, variables: dict[str, Any]) -> str:
        """Async wrapper around :meth:`render_section_sync`.

                Args:
        prompt_name (str): Prompt stem.
        variables (dict[str, Any]): Template variables.

                Returns:
                    str: Section body text.

                Examples:
                    >>> import asyncio
                    >>> asyncio.run(OfflineProvider().render_section("summary", {"title": "X"}))
                    'X — see manifest summary.'
        """
        return self.render_section_sync(prompt_name, variables)


class LlmProvider:
    """LLM section polish via egress proxy Transport — never reads provider keys."""

    def __init__(self, config: ReadmeProviderConfig) -> None:
        """Bind transport resolved from config (proxy URL only).

                Args:
        config (ReadmeProviderConfig): Model, transport, temperature, proxy URL.

                Examples:
                    >>> LlmProvider(ReadmeProviderConfig(offline=False)).config.offline
                    False
        """
        self.config = config
        transport_key = _TRANSPORT_ALIASES.get(config.transport, config.transport)
        _, transport = resolve_model(
            model_id=config.model,
            transport_name=transport_key,
            proxy_base_url=config.proxy_base_url,
        )
        self._transport = transport
        self._transport_key = transport_key

    async def render_section(self, prompt_name: str, variables: dict[str, Any]) -> str:
        """Render one section via the configured Transport.

                Args:
        prompt_name (str): Prompt stem under ``prompts/``.
        variables (dict[str, Any]): Variables for the prompt ``user_template``.

                Returns:
                    str: Model-generated section body.

                Examples:
                    >>> import asyncio
                    >>> from unittest.mock import AsyncMock, MagicMock
                    >>> cfg = ReadmeProviderConfig(offline=False, proxy_base_url="http://proxy")
                    >>> provider = LlmProvider(cfg)
                    >>> provider._transport = MagicMock()
                    >>> provider._transport.name = "anthropic"
                    >>> provider._transport.complete = AsyncMock(return_value={
                    ...     "content": [{"type": "text", "text": "Done."}],
                    ... })
                    >>> asyncio.run(provider.render_section("summary", {"title": "G",
                    ...     "profile": "subsystem", "context_json": "{}"}))
                    'Done.'
        """
        prompt = _load_prompt(prompt_name)
        system = str(prompt.get("system", "")).strip()
        user_template = str(prompt.get("user_template", "{{ title }}"))
        max_tokens = int(prompt.get("max_tokens", 512))
        user_content = _render_prompt_template(user_template, variables)
        request = _build_llm_request(
            transport=self._transport,
            model=self.config.model,
            system=system,
            user_content=user_content,
            max_tokens=max_tokens,
            temperature=self.config.temperature,
        )
        response = await self._transport.complete(request)
        return _extract_completion_text(self._transport.name, response)


def build_provider(config: ReadmeProviderConfig) -> OfflineProvider | LlmProvider:
    """Return offline or LLM provider from config.

        Args:
    config (ReadmeProviderConfig): Provider settings.

        Returns:
            OfflineProvider | LlmProvider: Section renderer.

        Examples:
            >>> isinstance(build_provider(ReadmeProviderConfig()), OfflineProvider)
            True
    """
    if config.offline:
        return OfflineProvider()
    return LlmProvider(config)


def _load_prompt(prompt_name: str) -> dict[str, Any]:
    """Load one prompt TOML from ``prompts_dir``.

        Args:
    prompt_name (str): Stem without ``.toml`` (e.g. ``summary``).

        Returns:
            dict[str, Any]: Parsed prompt table.

        Examples:
            >>> data = _load_prompt("summary")
            >>> "system" in data
            True
    """
    path = prompts_dir / f"{prompt_name}.toml"
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"{path}: prompt must be a TOML table"
        raise ValueError(msg)
    return data


def _render_prompt_template(template: str, variables: dict[str, Any]) -> str:
    """Render a prompt ``user_template`` with Jinja2.

        Args:
    template (str): Jinja2 template string.
    variables (dict[str, Any]): Variables for rendering.

        Returns:
            str: Rendered user prompt.

        Examples:
            >>> _render_prompt_template("Hello {{ title }}", {"title": "Gateway"})
            'Hello Gateway'
    """
    env = Environment(autoescape=select_autoescape(enabled_extensions=()))
    return env.from_string(template).render(**variables)


def _build_llm_request(
    *,
    transport: Transport,
    model: str,
    system: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, object]:
    """Build a provider-shaped request dict for ``transport.complete``.

        Args:
    transport (Transport): Resolved transport instance.
    model (str): LiteLLM model id.
    system (str): System prompt text.
    user_content (str): User message body.
    max_tokens (int): Max output tokens.
    temperature (float): Sampling temperature.

        Returns:
            dict[str, object]: Provider JSON body.

        Examples:
            >>> from sevn.agent.providers.transport import AnthropicTransport
            >>> req = _build_llm_request(
            ...     transport=AnthropicTransport(proxy_base_url="http://x"),
            ...     model="m",
            ...     system="s",
            ...     user_content="u",
            ...     max_tokens=64,
            ...     temperature=0.1,
            ... )
            >>> req["model"]
            'm'
    """
    if transport.name == "anthropic":
        body: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_content}],
        }
        if system:
            body["system"] = system
        return body
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_content})
    return {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }


def _extract_completion_text(transport_name: str, response: dict[str, object]) -> str:
    """Extract assistant text from a Transport completion response.

        Args:
    transport_name (str): Transport wire name (``anthropic``, ``chat_completions``, …).
    response (dict[str, object]): Parsed completion JSON.

        Returns:
            str: Assistant text (may be empty).

        Examples:
            >>> _extract_completion_text(
            ...     "anthropic",
            ...     {"content": [{"type": "text", "text": "Hi"}]},
            ... )
            'Hi'
    """
    if transport_name == "anthropic":
        content = response.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return str(block.get("text", "")).strip()
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                return str(message.get("content", "")).strip()
            text = choice.get("text")
            if text is not None:
                return str(text).strip()
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, list) and content:
                    part = content[0]
                    if isinstance(part, dict):
                        return str(part.get("text", "")).strip()
    return ""
