"""Structured LLM extraction via ``Transport`` (`specs/32-memory-honcho.md` §2.3).

Module: sevn.memory.user_model.extractor
Depends: json, re, uuid, datetime, typing, sevn.memory.user_model.models

Exports:
    UserModelExtractor — async structured call via proxy ``Transport`` only.

Examples:
    >>> import sevn.memory.user_model.extractor as e
    >>> e._LLMIGNORE_MARK
    '.llmignore/'
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from sevn.agent.providers.wire import adapt_request_for_transport
from sevn.config.llm_params import resolve_effective_max_output_tokens, resolve_llm_request_params
from sevn.memory.user_model.deny_topics import topic_denied
from sevn.memory.user_model.models import InferredFact
from sevn.memory.user_model.queue import USER_MODEL_PROMPT_REV

if TYPE_CHECKING:
    from sevn.agent.providers.transport import Transport

_LLMIGNORE_MARK = ".llmignore/"


def _workspace_content_root(workspace_root: str) -> Path:
    """Return normalized workspace content root for ``LLM_params_config.json`` lookup.

    Args:
        workspace_root (str): Workspace filesystem root.

    Returns:
        Path: Expanded absolute content root.

    Examples:
        >>> str(_workspace_content_root("/tmp/ws"))
        '/tmp/ws'
    """
    return Path(workspace_root).expanduser()


class UserModelExtractor:
    """Structured-output LLM call; returns ``[]`` on guardrails or parse failure."""

    def __init__(self, transport: Transport) -> None:
        """Bind a proxy ``Transport`` (spec **05**); no direct env API keys.

        Args:
            transport (Transport): Outbound LLM transport (proxy-backed).

        Returns:
            None: Always.

        Examples:
            >>> class T:
            ...     name = "t"
            ...     async def complete(self, r):
            ...         return {}
            ...     async def stream(self, r):
            ...         if False:
            ...             yield {}
            ...     def auth_header(self, m):
            ...         return {}
            ...     def tokens_used(self, resp):
            ...         return (0, 0)
            ...     def cache_breakpoints(self, segs):
            ...         return list(segs)
            >>> isinstance(UserModelExtractor(T()), UserModelExtractor)  # type: ignore[arg-type]
            True
        """

        self._transport = transport

    async def extract_deltas(
        self,
        *,
        workspace_root: str,
        turn_user_text: str,
        active_session_id: str,
        model_id: str,
        deny_topic_patterns: list[str],
    ) -> list[InferredFact]:
        """Return candidate facts (pre-merge); never persists.

        Args:
            workspace_root (str): Workspace root (reserved for future path guards).
            turn_user_text (str): Sanitised user text for this turn.
            active_session_id (str): Session id for provenance.
            model_id (str): Model id forwarded to ``Transport.complete``.
            deny_topic_patterns (list[str]): Substrings applied before merge.

        Returns:
            list[InferredFact]: Zero or more candidate rows.

        Examples:
            >>> import asyncio
            >>> from sevn.memory.user_model.extractor import UserModelExtractor
            >>> class T:
            ...     name = "t"
            ...     async def complete(self, r):
            ...         return {"choices": [{"message": {"content": "{}"}}]}
            ...     async def stream(self, r):
            ...         if False:
            ...             yield {}
            ...     def auth_header(self, m):
            ...         return {}
            ...     def tokens_used(self, resp):
            ...         return (0, 0)
            ...     def cache_breakpoints(self, segs):
            ...         return list(segs)
            >>> ex = UserModelExtractor(T())  # type: ignore[arg-type]
            >>> out = asyncio.run(
            ...     ex.extract_deltas(
            ...         workspace_root=".",
            ...         turn_user_text="hello",
            ...         active_session_id="s",
            ...         model_id="m",
            ...         deny_topic_patterns=[],
            ...     )
            ... )
            >>> out == []
            True
        """

        content_root = _workspace_content_root(workspace_root)
        if _LLMIGNORE_MARK in turn_user_text.lower():
            return []
        system = (
            f"You extract stable, operator-facing preference facts from one user turn. "
            f"(prompt_rev={USER_MODEL_PROMPT_REV}). "
            "Reply with a single JSON object ONLY, shape "
            '{"facts":[{"topic":"snake_case_id","value":"short human text",'
            '"confidence":"low"|"medium"|"high"}]} . '
            "Omit facts you cannot justify from the text. Max 5 facts."
        )
        user = json.dumps(
            {"turn": turn_user_text, "session_id": active_session_id}, ensure_ascii=False
        )
        req: dict[str, Any] = {
            "model": model_id,
            "max_tokens": resolve_effective_max_output_tokens(
                "user_model", model_id, None, content_root=content_root
            ),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # W7.4: user_model sampling from LLM_params_config.json (built-in default 0.0).
            **resolve_llm_request_params(
                "user_model", model_id, self._transport.name, content_root=content_root
            ),
        }
        try:
            resp = await self._transport.complete(adapt_request_for_transport(self._transport, req))
        except (TimeoutError, OSError, RuntimeError):
            return []
        content = _assistant_text(resp)
        if not content:
            return []
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{[\s\S]*\}\s*$", content.strip())
            if m is None:
                return []
            try:
                payload = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
        raw_facts = payload.get("facts") if isinstance(payload, dict) else None
        if not isinstance(raw_facts, list):
            return []
        out: list[InferredFact] = []
        now = datetime.now(tz=UTC)
        for row in raw_facts[:8]:
            if not isinstance(row, dict):
                continue
            topic = str(row.get("topic", "")).strip()
            value = str(row.get("value", "")).strip()
            conf_any = row.get("confidence", "low")
            if conf_any not in ("low", "medium", "high"):
                conf_any = "low"
            confidence = cast("Literal['low', 'medium', 'high']", conf_any)
            if not topic or not value:
                continue
            if topic_denied(topic, deny_topic_patterns):
                continue
            out.append(
                InferredFact(
                    id=uuid.uuid4().hex[:16],
                    topic=topic,
                    value=value,
                    confidence=confidence,
                    source_session_ids=[active_session_id][:5],
                    last_observed_at=now,
                    superseded_by_id=None,
                ),
            )
        return out


def _assistant_text(resp: dict[str, object]) -> str:
    """Extract assistant text from an OpenAI- or Anthropic-shaped completion payload.

    Args:
        resp (dict[str, object]): Parsed JSON completion object.

    Returns:
        str: Trimmed assistant content, or empty string when absent.

    Examples:
        >>> from sevn.memory.user_model.extractor import _assistant_text
        >>> _assistant_text({"choices": [{"message": {"content": " hi "}}]})
        'hi'
        >>> _assistant_text({"content": [{"type": "text", "text": "hi"}]})
        'hi'
    """

    choices = resp.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content.strip()
    blocks = resp.get("content")
    if isinstance(blocks, list):
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        if parts:
            return "".join(parts).strip()
    return ""


__all__ = ["UserModelExtractor"]
