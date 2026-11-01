"""The host panel: Ollama, loaded models and the job queue (phase 6)."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import cast

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sevn import __version__
from sevn.config import Settings
from sevn.store.db import utcnow
from sevn.store.models import Job as JobRow
from sevn.store.models import Turn as TurnRow

_CACHE_S = 30.0
_TIMEOUT_S = 2.0


class LoadedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    vram_bytes: int | None


class OllamaStatus(BaseModel):
    """``reachable`` is null when no Ollama URL is set."""

    model_config = ConfigDict(extra="forbid")

    configured: bool
    reachable: bool | None
    models: list[str]
    loaded: list[LoadedModel]
    error: str | None
    checked_at: datetime | None


class FleetHost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    version: str
    queued_jobs: int
    running_turns: int
    max_running_turns: int
    ollama: OllamaStatus


_cache: dict[str, tuple[float, OllamaStatus]] = {}


def reset_cache() -> None:
    """Forget the last Ollama check. Tests call this between cases."""
    _cache.clear()


async def host_status(session: AsyncSession) -> FleetHost:
    queued = await session.scalar(
        select(func.count()).select_from(JobRow).where(JobRow.status == "queued")
    )
    running = await session.scalar(
        select(func.count()).select_from(TurnRow).where(TurnRow.status == "running")
    )
    return FleetHost(
        as_of=utcnow(),
        version=__version__,
        queued_jobs=int(queued or 0),
        running_turns=int(running or 0),
        max_running_turns=Settings.load().runtime.max_running_turns,
        ollama=await ollama_status(),
    )


async def ollama_status() -> OllamaStatus:
    """Ask Ollama what it has and what is loaded. Cached for 30 seconds."""
    url = os.environ.get("SEVN_OLLAMA_URL", "")
    if url == "":
        return OllamaStatus(
            configured=False, reachable=None, models=[], loaded=[], error=None, checked_at=None
        )
    cached = _cache.get(url)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_S:
        return cached[1]
    status = await _probe(url.rstrip("/"))
    _cache[url] = (time.monotonic(), status)
    return status


async def _probe(base: str) -> OllamaStatus:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            tags = await client.get(f"{base}/api/tags")
            tags.raise_for_status()
            running = await client.get(f"{base}/api/ps")
            running.raise_for_status()
            tags_body: object = tags.json()
            running_body: object = running.json()
    except httpx.HTTPStatusError:
        return _down("error response")
    except (httpx.HTTPError, ValueError):
        return _down("unreachable")
    return OllamaStatus(
        configured=True,
        reachable=True,
        models=[name for name, _ in _models(tags_body)],
        loaded=[LoadedModel(name=name, vram_bytes=vram) for name, vram in _models(running_body)],
        error=None,
        checked_at=utcnow(),
    )


def _down(reason: str) -> OllamaStatus:
    return OllamaStatus(
        configured=True,
        reachable=False,
        models=[],
        loaded=[],
        error=reason,
        checked_at=utcnow(),
    )


def _models(payload: object) -> list[tuple[str, int | None]]:
    if not isinstance(payload, dict):
        return []
    items = cast("dict[object, object]", payload).get("models")
    if not isinstance(items, list):
        return []
    found: list[tuple[str, int | None]] = []
    for item in cast("list[object]", items):
        if not isinstance(item, dict):
            continue
        body = cast("dict[object, object]", item)
        name = body.get("name")
        vram = body.get("size_vram")
        if isinstance(name, str) and name != "":
            found.append((name, vram if isinstance(vram, int) else None))
    return found
