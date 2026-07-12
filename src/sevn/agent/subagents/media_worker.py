"""Execute ``media_generator`` specialist tasks and persist artifacts (W8.1/W8.2).

Module: sevn.agent.subagents.media_worker
Depends: json, pathlib, sqlite3, sevn.agent.subagents.media_minimax,
    sevn.agent.subagents.specialists, sevn.config.loader, sevn.gateway.media_store

Exports:
    MediaTask — parsed generation request.
    parse_media_task — task-string → :class:`MediaTask`.
    require_media_generator — resolve configured specialist or raise.
    resolve_minimax_api_key — workspace MiniMax API key lookup.
    execute_media_generator_task — run one media job and return artifact metadata.
    execute_media_generator_for_context — :class:`ToolContext` wrapper for spawn tool.

Examples:
    >>> from sevn.agent.subagents.media_worker import MEDIA_GENERATOR_SPECIALIST
    >>> MEDIA_GENERATOR_SPECIALIST
    'media_generator'
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sevn.agent.subagents.media_minimax import (
    MiniMaxMediaError,
    generate_image_bytes,
    generate_music_bytes,
    generate_video_bytes,
)
from sevn.agent.subagents.specialists import resolve_specialist
from sevn.config.loader import load_workspace
from sevn.config.provider_secrets import provider_secret_alias
from sevn.config.sections.providers import providers_section_dict
from sevn.gateway.media_store import MediaStore
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import EnvUnresolvedError, expand_refs_env_then_secret

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
    from sevn.tools.context import ToolContext

MEDIA_GENERATOR_SPECIALIST = "media_generator"
MEDIA_GENERATOR_UNCONFIGURED = (
    "media generation requires subagents.specialists.media_generator — "
    "configure the specialist (see infra/sevn.schema.json D8 example)"
)

MediaKind = Literal["image", "video", "music"]
_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True, slots=True)
class MediaTask:
    """One media generation request parsed from a spawn/skill task string."""

    kind: MediaKind
    prompt: str
    aspect_ratio: str = "1:1"
    duration: int = 6
    resolution: str = "720P"
    lyrics: str | None = None
    is_instrumental: bool = False


def parse_media_task(task: str) -> MediaTask:
    """Parse a media task string (JSON or ``kind:prompt`` shorthand).

    Args:
        task (str): Spawn/skill task text.

    Returns:
        MediaTask: Parsed request.

    Raises:
        ValueError: When the task is empty or malformed.

    Examples:
        >>> parse_media_task('{"kind":"image","prompt":"a cat"}').kind
        'image'
        >>> parse_media_task("image:a red balloon").prompt
        'a red balloon'
    """
    text = task.strip()
    if not text:
        msg = "media task must be non-empty"
        raise ValueError(msg)
    if text.startswith("{"):
        raw = json.loads(text)
        if not isinstance(raw, dict):
            msg = "media task JSON must be an object"
            raise ValueError(msg)
        kind = str(raw.get("kind") or raw.get("media") or "").strip().lower()
        prompt = str(raw.get("prompt") or "").strip()
        if kind not in ("image", "video", "music") or not prompt:
            msg = "media task JSON requires kind=image|video|music and prompt"
            raise ValueError(msg)
        return MediaTask(
            kind=kind,  # type: ignore[arg-type]
            prompt=prompt,
            aspect_ratio=str(raw.get("aspect_ratio") or "1:1"),
            duration=int(raw.get("duration") or 6),
            resolution=str(raw.get("resolution") or "720P"),
            lyrics=(str(raw["lyrics"]).strip() if raw.get("lyrics") else None),
            is_instrumental=bool(raw.get("is_instrumental")),
        )
    if ":" in text:
        head, _, tail = text.partition(":")
        kind = head.strip().lower()
        prompt = tail.strip()
        if kind in ("image", "video", "music") and prompt:
            return MediaTask(kind=kind, prompt=prompt)  # type: ignore[arg-type]
    msg = "media task must be JSON or kind:prompt (image|video|music)"
    raise ValueError(msg)


def require_media_generator(
    cfg: SubAgentsWorkspaceConfig | None,
) -> SpecialistConfig:
    """Return the configured ``media_generator`` specialist entry.

    Args:
        cfg (SubAgentsWorkspaceConfig | None): Parsed ``subagents`` subtree.

    Returns:
        SpecialistConfig: Configured specialist.

    Raises:
        MiniMaxMediaError: When the specialist is not configured.

    Examples:
        >>> require_media_generator(None)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        MiniMaxMediaError
    """
    entry = resolve_specialist(cfg, MEDIA_GENERATOR_SPECIALIST)
    if entry is None:
        raise MiniMaxMediaError(MEDIA_GENERATOR_UNCONFIGURED)
    return entry


async def _resolve_plaintext_ref(ref: str, chain: SecretsChain) -> str | None:
    """Expand one credential ref via the workspace secrets chain.

    Args:
        ref (str): Literal or ``${SECRET:…}`` / ``${ENV:…}`` reference.
        chain (SecretsChain): Workspace secrets chain.

    Returns:
        str | None: Resolved plaintext when available.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_plaintext_ref)
        True
    """
    stripped = ref.strip()
    if not stripped:
        return None
    if not stripped.startswith("${"):
        return stripped
    cache = ResolvedSecretsCache(chain, ttl_seconds=300)
    try:
        expanded = await expand_refs_env_then_secret(stripped, cache)
    except (EnvUnresolvedError, ValueError):
        expanded = stripped
    expanded = expanded.strip()
    if expanded.startswith("${"):
        inner = expanded.removeprefix("${").removesuffix("}").strip()
        if inner.upper().startswith("SECRET:"):
            alias = inner.split(":", 1)[1].strip()
            return await get_secret_resilient(chain, alias)
        return None
    return expanded or None


async def resolve_minimax_api_key(
    *,
    content_root: Path,
    providers_obj: dict[str, Any] | None = None,
) -> str:
    """Resolve the MiniMax API key for media generation.

    Precedence: ``providers.minimax.api_key`` ref → ``SEVN_SECRET_MINIMAX`` /
    ``MINIMAX_API_KEY`` env.

    Args:
        content_root (Path): Workspace content root (``SEVN_CONTENT_ROOT``).
        providers_obj (dict[str, Any] | None, optional): Pre-loaded providers block.

    Returns:
        str: Plaintext API key.

    Raises:
        MiniMaxMediaError: When no key is configured.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(resolve_minimax_api_key)
        True
    """
    cfg, _layout = load_workspace(start_dir=content_root)
    providers = (
        providers_obj if providers_obj is not None else providers_section_dict(cfg.providers)
    )
    minimax = providers.get("minimax")
    api_ref: str | None = None
    if isinstance(minimax, dict):
        raw = minimax.get("api_key")
        if isinstance(raw, str) and raw.strip():
            api_ref = raw.strip()
    chain = secrets_chain_from_workspace(content_root, cfg.secrets_backend)
    if api_ref:
        resolved = await _resolve_plaintext_ref(api_ref, chain)
        if resolved:
            return resolved
    env_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if env_key:
        return env_key
    alias = provider_secret_alias("minimax")
    from_store = await get_secret_resilient(chain, alias)
    if from_store:
        return from_store
    raise MiniMaxMediaError(
        "MiniMax API key missing — set providers.minimax.api_key or "
        f"store `{alias}` / MINIMAX_API_KEY",
    )


def _safe_filename(kind: MediaKind, prompt: str) -> str:
    """Build a filesystem-safe artifact basename.

    Args:
        kind (MediaKind): Media kind.
        prompt (str): User prompt (truncated for the stem).

    Returns:
        str: Filename with extension.

    Examples:
        >>> _safe_filename("image", "Hello World!")
        'media-image-hello-world.jpg'
    """
    stem = _FILENAME_SAFE.sub("-", prompt.strip().lower())[:48].strip("-") or "artifact"
    ext = {"image": "jpg", "video": "mp4", "music": "mp3"}[kind]
    return f"media-{kind}-{stem}.{ext}"


async def _persist_bytes(
    *,
    conn: sqlite3.Connection,
    content_root: Path,
    session_id: str,
    filename: str,
    data: bytes,
) -> str:
    """Write bytes under ``channel_files/<session_id>/`` via :class:`MediaStore`.

    Args:
        conn (sqlite3.Connection): Workspace DB connection.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.
        filename (str): Target basename.
        data (bytes): Artifact bytes.

    Returns:
        str: Workspace-relative path ``channel_files/<session_id>/<filename>``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_persist_bytes)
        True
    """
    store = MediaStore(conn, content_root)
    encoded = base64.b64encode(data).decode("ascii")
    await store.persist_attachment_descriptors(
        session_id,
        [{"filename": filename, "data_base64": encoded}],
    )
    return f"channel_files/{session_id}/{filename}"


async def execute_media_generator_task(
    task: str,
    *,
    session_id: str,
    content_root: Path,
    conn: sqlite3.Connection,
    subagents_cfg: SubAgentsWorkspaceConfig | None,
    providers_obj: dict[str, Any] | None = None,
    http_client: Any | None = None,
    video_poll_interval_s: float | None = None,
    video_max_polls: int | None = None,
) -> dict[str, object]:
    """Run one ``media_generator`` job and persist the artifact.

    Args:
        task (str): Spawn/skill task (JSON or ``kind:prompt``).
        session_id (str): Gateway session id for ``channel_files/`` layout.
        content_root (Path): Workspace content root.
        conn (sqlite3.Connection): Open workspace DB (for :class:`MediaStore`).
        subagents_cfg (SubAgentsWorkspaceConfig | None): ``subagents`` subtree.
        providers_obj (dict[str, Any] | None, optional): Providers block override.
        http_client (Any | None, optional): Injectable ``httpx.AsyncClient`` for tests.
        video_poll_interval_s (float | None, optional): Test-only poll interval override.
        video_max_polls (int | None, optional): Test-only poll cap override.

    Returns:
        dict[str, object]: ``artifact_path``, ``kind``, ``bytes`` metadata.

    Raises:
        MiniMaxMediaError: When specialist/API/config is missing or generation fails.
        ValueError: When the task string is malformed.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(execute_media_generator_task)
        True
    """
    specialist = require_media_generator(subagents_cfg)
    media_task = parse_media_task(task)
    api_key = await resolve_minimax_api_key(
        content_root=content_root,
        providers_obj=providers_obj,
    )
    poll_interval = video_poll_interval_s if video_poll_interval_s is not None else 5.0
    poll_cap = video_max_polls if video_max_polls is not None else 120
    if media_task.kind == "image":
        data = await generate_image_bytes(
            api_key,
            media_task.prompt,
            aspect_ratio=media_task.aspect_ratio,
            client=http_client,
        )
    elif media_task.kind == "video":
        data = await generate_video_bytes(
            api_key,
            media_task.prompt,
            duration=media_task.duration,
            resolution=media_task.resolution,
            poll_interval_s=poll_interval,
            max_polls=poll_cap,
            client=http_client,
        )
    else:
        data = await generate_music_bytes(
            api_key,
            media_task.prompt,
            lyrics=media_task.lyrics,
            is_instrumental=media_task.is_instrumental,
            client=http_client,
        )
    filename = _safe_filename(media_task.kind, media_task.prompt)
    rel_path = await _persist_bytes(
        conn=conn,
        content_root=content_root,
        session_id=session_id,
        filename=filename,
        data=data,
    )
    return {
        "artifact_path": rel_path,
        "kind": media_task.kind,
        "bytes": len(data),
        "specialist": MEDIA_GENERATOR_SPECIALIST,
        "model": specialist.model,
        "provider": specialist.provider,
    }


async def execute_media_generator_for_context(ctx: ToolContext, task: str) -> str:
    """Run ``media_generator`` using spawn-tool :class:`ToolContext` handles.

    Args:
        ctx (ToolContext): Active tool invocation context.
        task (str): Spawn task string.

    Returns:
        str: JSON string with artifact metadata for the spawn tool result body.

    Raises:
        MiniMaxMediaError: When configuration or generation fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(execute_media_generator_for_context)
        True
    """
    supervisor = ctx.subagent_supervisor
    subagents_cfg = supervisor.config if supervisor is not None else None
    conn = None
    if ctx.channel_router is not None:
        conn = ctx.channel_router._sessions.connection
    if conn is None:
        from sevn.lcm.script_cli import open_workspace_db

        conn = open_workspace_db(ctx.workspace_path)
        close_conn = True
    else:
        close_conn = False
    try:
        payload = await execute_media_generator_task(
            task,
            session_id=ctx.session_id,
            content_root=ctx.workspace_path,
            conn=conn,
            subagents_cfg=subagents_cfg,
        )
    finally:
        if close_conn:
            conn.close()
    return json.dumps(payload, separators=(",", ":"))


__all__ = [
    "MEDIA_GENERATOR_SPECIALIST",
    "MEDIA_GENERATOR_UNCONFIGURED",
    "MediaTask",
    "execute_media_generator_for_context",
    "execute_media_generator_task",
    "parse_media_task",
    "require_media_generator",
    "resolve_minimax_api_key",
]
