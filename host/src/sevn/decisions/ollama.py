"""Local Ollama fallback. ``SEVN_OLLAMA_URL`` must answer ``/api/chat``."""

from __future__ import annotations

import os

import httpx

from sevn.config import Settings
from sevn.decisions.base import (
    Attempt,
    attempt_from_model,
    model_prompt,
    object_dict,
    parse_model_route,
)
from sevn.decisions.thresholds import step_accepts
from sevn.log import logger


class OllamaDecider:
    """One non-streaming chat call. An unreachable server is skipped."""

    async def attempt(self, state: str) -> Attempt | None:
        url = _url()
        if url is None:
            return None
        model = Settings.load().decisions.ollama_model
        try:
            text = await _chat(url, model, model_prompt(state))
        except (httpx.HTTPError, OSError, ValueError):
            logger.warning("ollama decider failed")
            return None
        if text is None:
            return None
        parsed = parse_model_route(text)
        if parsed is None:
            return None
        return attempt_from_model(parsed, "ollama", accepted=step_accepts(parsed.confidence))


def _url() -> str | None:
    raw = os.environ.get("SEVN_OLLAMA_URL", "").strip()
    if raw == "":
        return None
    return raw.rstrip("/")


async def _chat(url: str, model: str, prompt: str) -> str | None:
    body = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(f"{url}/api/chat", json=body)
    if response.status_code >= 400:
        return None
    payload = object_dict(response.json())
    if payload is None:
        return None
    message = object_dict(payload.get("message"))
    if message is None:
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    return content
