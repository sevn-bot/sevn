"""Call sevn's configured model tier from a skill script via the egress proxy.

Module: job-ops/scripts/lib/llm.py

No shipped "LLM-from-script" helper exists, so this wires directly into the same
transport stack the tier executors use (``resolve_model`` + egress proxy). When the
proxy environment is unavailable it raises :class:`LlmUnavailable` so callers can
fall back to agent-side scoring (``needs_agent_scoring``).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


class LlmUnavailable(RuntimeError):
    """Raised when the model tier cannot be reached from the skill subprocess."""


def _extract_text(raw: Any) -> str:
    """Pull assistant text out of a chat-completions or anthropic response body."""
    if not isinstance(raw, dict):
        return ""
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    content = raw.get("content")
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict)]
        return "".join(p for p in parts if isinstance(p, str))
    if isinstance(content, str):
        return content
    return ""


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort parse of the first balanced JSON object in ``text``."""
    text = text.strip()
    for candidate in (text, _first_object(text)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _first_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _proxy_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip()
    if secret:
        headers["X-Sevn-Proxy-Token"] = secret
    session_token = os.environ.get("SEVN_SESSION_TOKEN", "").strip()
    if session_token:
        headers["X-Sevn-Session-Token"] = session_token
    return headers


def complete_json(prompt: str, *, content_root: Path, max_tokens: int = 1024) -> dict[str, Any]:
    """Send ``prompt`` to the tier-B model and parse a JSON object from the reply.

    Args:
        prompt (str): User prompt instructing the model to reply with a JSON object.
        content_root (Path): Workspace content root (for ``sevn.json`` resolution).
        max_tokens (int): Max output tokens.

    Returns:
        dict[str, Any]: Parsed JSON object (may be empty when the model returns none).

    Raises:
        LlmUnavailable: When the proxy/config is not reachable from the subprocess.
    """
    proxy_url = os.environ.get("SEVN_PROXY_URL", "").strip()
    if not proxy_url:
        try:
            from sevn.config.settings import ProcessSettings

            proxy_url = (ProcessSettings().proxy_url or "").strip()
        except Exception as exc:  # noqa: BLE001
            raise LlmUnavailable(f"proxy settings unavailable: {exc}") from exc
    if not proxy_url:
        raise LlmUnavailable("SEVN_PROXY_URL is not set in the skill subprocess")

    try:
        from sevn.agent.providers.resolve import resolve_model
        from sevn.agent.providers.wire import adapt_request_for_transport
        from sevn.config.loader import load_workspace
        from sevn.config.model_resolution import (
            ModelSlot,
            resolve_model_slot,
            resolve_transport_for_model_id,
        )
        from sevn.config.sections.providers import providers_section_dict

        cfg, _layout = load_workspace(start_dir=content_root)
        model_id = resolve_model_slot(cfg, ModelSlot.tier_b)
        transport_name = resolve_transport_for_model_id(
            providers_section_dict(getattr(cfg, "providers", None)), model_id
        )
        _mid, transport = resolve_model(
            model_id=model_id,
            transport_name=transport_name,
            proxy_base_url=proxy_url,
            extra_headers=_proxy_headers(),
        )
        req: dict[str, Any] = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        raw = asyncio.run(transport.complete(adapt_request_for_transport(transport, req)))
    except LlmUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LlmUnavailable(str(exc)) from exc

    return _extract_json(_extract_text(raw))
