"""Select existing prompt sources for one routed turn."""

from __future__ import annotations

from contextvars import ContextVar
from typing import cast

from sevn.decisions.base import DEFAULT_PROFILE, ContextProfile, object_dict

# Runtime.open builds Claude's system prompt before run_turn receives a TurnContext.
turn_profile: ContextVar[ContextProfile] = ContextVar("turn_profile", default=DEFAULT_PROFILE)


def select_history(
    history: list[object] | None, profile: ContextProfile, *, resuming: bool = False
) -> list[object] | None:
    if not history or (profile.history == "full" and profile.attachments == "include"):
        return history
    selected = history
    if profile.history != "full":
        # Start on a fresh user request so a tool return keeps its preceding call.
        starts = [index for index, raw in enumerate(history) if _starts_turn(raw)]
        keep = (3 if profile.history == "recent" else 1) + int(resuming)
        if len(starts) > keep:
            selected = history[starts[-keep] :]
    if profile.attachments == "skip":
        selected = [_without_attachments(raw) for raw in selected]
    return selected


def _starts_turn(raw: object) -> bool:
    msg = object_dict(raw)
    if not msg or msg.get("kind") != "request":
        return False
    parts = msg.get("parts")
    if not isinstance(parts, list):
        return False
    kinds = [(object_dict(part) or {}).get("part_kind") for part in cast("list[object]", parts)]
    return "user-prompt" in kinds and "tool-return" not in kinds and "retry-prompt" not in kinds


def _without_attachments(raw: object) -> object:
    msg = object_dict(raw)
    if not msg or msg.get("kind") != "request":
        return raw
    parts = msg.get("parts")
    if not isinstance(parts, list):
        return raw
    filtered: list[object] = []
    for raw_part in cast("list[object]", parts):
        part = object_dict(raw_part)
        if part and part.get("part_kind") == "user-prompt":
            content = part.get("content")
            if isinstance(content, list):
                raw_part = {
                    **part,
                    "content": [
                        item for item in cast("list[object]", content) if isinstance(item, str)
                    ],
                }
        filtered.append(raw_part)
    return {**msg, "parts": filtered}
