"""Provider catalog, secret-backed model resolution, and the echo test model (D5)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

import httpx
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers import Provider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from sevn.config import Settings
from sevn.log import logger
from sevn.paths import Paths
from sevn.runtime.errors import ModelError
from sevn.secrets.backends import open_backend
from sevn.secrets.errors import SecretNotFound

ECHO_ID = "echo"

_SECRET_NAMES = {
    "anthropic": "provider/anthropic",
    "openai": "provider/openai",
    "google": "provider/google",
    "openrouter": "provider/openrouter",
}
_KEYED_PROVIDERS = ("anthropic", "openai", "google", "openrouter")


@dataclass(frozen=True, slots=True)
class CatalogModel:
    """One model the picker can show."""

    id: str
    provider: str
    name: str


_CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel("anthropic:claude-sonnet-4-5", "anthropic", "Claude Sonnet 4.5"),
    CatalogModel("anthropic:claude-haiku-4-5", "anthropic", "Claude Haiku 4.5"),
    CatalogModel("anthropic:claude-opus-4-1", "anthropic", "Claude Opus 4.1"),
    CatalogModel("openai:gpt-5", "openai", "GPT-5"),
    CatalogModel("openai:gpt-5-mini", "openai", "GPT-5 mini"),
    CatalogModel("google:gemini-2.5-pro", "google", "Gemini 2.5 Pro"),
    CatalogModel("google:gemini-2.5-flash", "google", "Gemini 2.5 Flash"),
    CatalogModel(
        "openrouter:anthropic/claude-sonnet-4.5",
        "openrouter",
        "Claude Sonnet 4.5",
    ),
)


def echo_enabled() -> bool:
    """The echo model exists only for local e2e, and only behind both flags."""
    return os.environ.get("SEVN_DEV") == "1" and os.environ.get("SEVN_TEST_MODEL") == "echo"


def model_allowed(model_id: str) -> bool:
    """Catalog ids are selectable. Echo is selectable only behind the dev flags."""
    if model_id == ECHO_ID:
        return echo_enabled()
    return any(item.id == model_id for item in _CATALOG)


_override: Model | None = None


def use_model(model: Model | None) -> None:
    """Install ``model`` for later ``resolve_model`` calls. ``None`` clears it.

    Tests script a ``FunctionModel`` this way. Production leaves the override unset,
    so resolution still reads provider keys from the secret backend.
    """
    global _override
    _override = model


def resolve_model(name: str) -> Model:
    """Build a model for ``name``. API keys come from the secret backend and are not logged."""
    chosen = _override
    if chosen is not None:
        return chosen
    if name == ECHO_ID:
        if not echo_enabled():
            raise ModelError("echo model is disabled")
        return _echo_model()
    if name == "":
        raise ModelError("bot has no model")
    factory = cast("Callable[[str], Provider[Any]]", _provider_for)
    return infer_model(_resolvable_name(name), provider_factory=factory)


def first_catalog_id(provider: str) -> str:
    """The first catalog id for a bare provider, or the name when it has none."""
    for item in _CATALOG:
        if item.provider == provider:
            return item.id
    return provider


def _resolvable_name(name: str) -> str:
    """Picker ids are ``provider:model``. A bare provider uses its first catalog id."""
    if ":" in name:
        return name
    return first_catalog_id(name)


async def list_models() -> list[CatalogModel]:
    """Models for providers that have a key, plus Ollama and echo when enabled."""
    configured = await asyncio.to_thread(_configured_providers)
    found = [item for item in _CATALOG if item.provider in configured]
    url = _ollama_url()
    if url is not None:
        found.extend(await _ollama_models(url))
    if echo_enabled():
        found.append(CatalogModel(id=ECHO_ID, provider="echo", name="Echo"))
    return found


def _configured_providers() -> set[str]:
    backend = open_backend(Settings.load(), Paths.from_env())
    found: set[str] = set()
    for name in _KEYED_PROVIDERS:
        try:
            backend.get(_SECRET_NAMES[name])
        except SecretNotFound:
            continue
        found.add(name)
    return found


def _ollama_url() -> str | None:
    raw = os.environ.get("SEVN_OLLAMA_URL")
    if raw is None or raw == "":
        return None
    return raw


def _provider_key(provider_name: str) -> str | None:
    secret = _SECRET_NAMES.get(provider_name)
    if secret is None:
        return None
    try:
        return open_backend(Settings.load(), Paths.from_env()).get(secret)
    except SecretNotFound:
        return None


def _provider_for(provider_name: str) -> object:
    if provider_name == "ollama":
        url = _ollama_url()
        if url is None:
            raise ModelError("ollama url is not set")
        return OllamaProvider(base_url=url)
    key = _provider_key(provider_name)
    if provider_name == "anthropic":
        return AnthropicProvider(api_key=key)
    if provider_name == "openai":
        return OpenAIProvider(api_key=key)
    if provider_name == "google":
        return GoogleProvider(api_key=key)
    if provider_name == "openrouter":
        return OpenRouterProvider(api_key=key)
    raise ModelError("unknown provider")


async def _ollama_models(url: str) -> list[CatalogModel]:
    target = f"{url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(target)
            response.raise_for_status()
            payload: object = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("ollama model list failed")
        return []
    return _tags(payload)


def _tags(payload: object) -> list[CatalogModel]:
    body = _object_dict(payload)
    if body is None:
        return []
    items = _object_list(body.get("models"))
    if items is None:
        return []
    found: list[CatalogModel] = []
    for item in items:
        row = _object_dict(item)
        if row is None:
            continue
        name = row.get("name")
        if not isinstance(name, str) or name == "":
            continue
        found.append(CatalogModel(id=f"ollama:{name}", provider="ollama", name=name))
    return found


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    body: dict[str, object] = {}
    for key, item in cast("dict[object, object]", value).items():
        if isinstance(key, str):
            body[key] = item
    return body


def _object_list(value: object) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return list(cast("list[object]", value))


def _echo_model() -> FunctionModel:
    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=_echo_text(messages))])

    async def stream(messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        yield _echo_text(messages)

    return FunctionModel(respond, stream_function=stream, model_name=ECHO_ID)


def _echo_text(messages: Sequence[ModelMessage]) -> str:
    return f"echo: {_user_text(messages)}"


def _user_text(messages: Sequence[ModelMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if isinstance(part, UserPromptPart):
                return _prompt_text(part.content)
    return ""


def _prompt_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in cast("list[object]", content):
        if isinstance(item, str):
            parts.append(item)
    return "".join(parts)
