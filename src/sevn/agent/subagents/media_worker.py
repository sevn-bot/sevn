"""Execute ``media_generator`` specialist tasks and persist artifacts (W8.1/W8.2).

Module: sevn.agent.subagents.media_worker
Depends: json, pathlib, sqlite3, sevn.agent.subagents.media_minimax,
    sevn.agent.subagents.media_prompts, sevn.agent.subagents.specialists,
    sevn.config.loader, sevn.gateway.media.media_store

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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.agent.subagents.media_minimax import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_MUSIC_MODEL,
    DEFAULT_SPEECH_MODEL,
    DEFAULT_VIDEO_FL2V_MODEL,
    DEFAULT_VIDEO_I2V_MODEL,
    DEFAULT_VIDEO_MODEL,
    DEFAULT_VIDEO_S2V_MODEL,
    MiniMaxMediaError,
    clone_voice_bytes,
    generate_image_bytes,
    generate_image_from_reference_bytes,
    generate_music_bytes,
    generate_video_bytes,
    generate_video_first_last_frame_bytes,
    generate_video_from_image_bytes,
    generate_video_subject_reference_bytes,
    generate_video_template_bytes,
    synthesize_speech_bytes,
)
from sevn.agent.subagents.media_prompts import (
    MediaPromptVars,
    augment_prompt,
    build_media_trace,
    resolve_video_agent_template,
)
from sevn.agent.subagents.specialists import resolve_specialist
from sevn.config.loader import load_workspace
from sevn.config.provider_secrets import provider_secret_alias
from sevn.config.sections.providers import providers_section_dict
from sevn.gateway.media.media_store import MediaStore
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, get_secret_resilient
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.security.secrets.value_expand import EnvUnresolvedError, expand_refs_env_then_secret

if TYPE_CHECKING:
    import sqlite3

    from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
    from sevn.tools.context import ToolContext

MEDIA_GENERATOR_SPECIALIST = "media_generator"
MEDIA_GENERATOR_UNCONFIGURED = (
    "media generation requires subagents.specialists.media_generator — "
    "configure the specialist (see infra/sevn.schema.json D8 example)"
)

MediaKind = Literal[
    "image",
    "image_i2i",
    "video",
    "video_i2v",
    "video_s2v",
    "video_fl2v",
    "video_template",
    "music",
    "voice",
]
_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}


@dataclass(frozen=True, slots=True)
class MediaTask:
    """One media generation request parsed from a spawn/skill task string."""

    kind: MediaKind
    prompt: str
    template_key: str | None = None
    aspect_ratio: str = "1:1"
    duration: int = 6
    resolution: str = "720P"
    lyrics: str | None = None
    is_instrumental: bool = False
    first_frame_image: str | None = None
    template_id: str | None = None
    text_inputs: tuple[str, ...] = ()
    media_inputs: tuple[str, ...] = ()
    voice_id: str | None = None
    source_audio: str | None = None
    preview_text: str | None = None
    prompt_audio: str | None = None
    prompt_text: str | None = None
    speech_text: str | None = None
    reference_image: str | None = None
    subject_reference: str | None = None
    last_frame_image: str | None = None
    prompt_vars: MediaPromptVars = field(default_factory=MediaPromptVars)


def _coerce_str_list(raw: object) -> tuple[str, ...]:
    """Normalize a JSON list field to a tuple of strings.

    Args:
        raw (object): Parsed JSON value.

    Returns:
        tuple[str, ...]: Stripped string entries.

    Examples:
        >>> _coerce_str_list([" a ", "b"])
        ('a', 'b')
    """
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return tuple(out)


def parse_media_task(task: str) -> MediaTask:
    """Parse a media task string (JSON or ``kind:prompt`` shorthand).

    JSON fields:
        - ``kind`` / ``media``: ``image``, ``video``, ``video_i2v``, ``video_template``,
          ``music``, ``voice``
        - ``prompt``: short user intent (augmented with templates server-side)
        - ``template``: augmentation template slug (e.g. ``portrait``, ``lofi``)
        - ``first_frame_image``: URL or workspace path for image-to-video
        - ``template_id`` / ``template_slug``: Video Agent template ref
        - ``text_inputs``, ``media_inputs``: Video Agent slot values
        - ``voice_id``, ``source_audio``, ``preview_text``, ``speech_text``: voice flows

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
        prompt = str(raw.get("prompt") or raw.get("user_request") or "").strip()
        valid_kinds = (
            "image",
            "image_i2i",
            "video",
            "video_i2v",
            "video_s2v",
            "video_fl2v",
            "video_template",
            "music",
            "voice",
        )
        if kind not in valid_kinds:
            msg = f"media task JSON requires kind in {valid_kinds}"
            raise ValueError(msg)
        if kind != "video_template" and not prompt:
            msg = "media task JSON requires prompt (short user intent)"
            raise ValueError(msg)
        template_ref = (
            str(
                raw.get("template_id")
                or raw.get("template_slug")
                or raw.get("video_template")
                or "",
            ).strip()
            or None
        )
        return MediaTask(
            kind=kind,  # type: ignore[arg-type]
            prompt=prompt,
            template_key=(str(raw["template"]).strip() if raw.get("template") else None),
            aspect_ratio=str(raw.get("aspect_ratio") or "1:1"),
            duration=int(raw.get("duration") or 6),
            resolution=str(raw.get("resolution") or "720P"),
            lyrics=(str(raw["lyrics"]).strip() if raw.get("lyrics") else None),
            is_instrumental=bool(raw.get("is_instrumental")),
            first_frame_image=(
                str(raw["first_frame_image"]).strip() if raw.get("first_frame_image") else None
            ),
            template_id=template_ref,
            text_inputs=_coerce_str_list(raw.get("text_inputs")),
            media_inputs=_coerce_str_list(raw.get("media_inputs")),
            voice_id=(str(raw["voice_id"]).strip() if raw.get("voice_id") else None),
            source_audio=(str(raw["source_audio"]).strip() if raw.get("source_audio") else None),
            preview_text=(str(raw["preview_text"]).strip() if raw.get("preview_text") else None),
            prompt_audio=(str(raw["prompt_audio"]).strip() if raw.get("prompt_audio") else None),
            prompt_text=(str(raw["prompt_text"]).strip() if raw.get("prompt_text") else None),
            speech_text=(str(raw["speech_text"]).strip() if raw.get("speech_text") else None),
            reference_image=(
                str(raw["reference_image"]).strip() if raw.get("reference_image") else None
            ),
            subject_reference=(
                str(raw["subject_reference"]).strip() if raw.get("subject_reference") else None
            ),
            last_frame_image=(
                str(raw["last_frame_image"]).strip() if raw.get("last_frame_image") else None
            ),
            prompt_vars=MediaPromptVars.from_mapping(raw),
        )
    if ":" in text:
        head, _, tail = text.partition(":")
        kind = head.strip().lower()
        prompt = tail.strip()
        if kind in ("image", "video", "video_i2v", "music", "voice") and prompt:
            return MediaTask(kind=kind, prompt=prompt)  # type: ignore[arg-type]
    msg = "media task must be JSON or kind:prompt (image|video|video_i2v|music|voice)"
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


def _resolve_local_file(path_ref: str, *, content_root: Path) -> Path:
    """Resolve a workspace-relative or absolute file path.

    Args:
        path_ref (str): Path reference.
        content_root (Path): Workspace content root.

    Returns:
        Path: Resolved existing file.

    Raises:
        MiniMaxMediaError: When the file is not found.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolve_local_file)
        True
    """
    ref = path_ref.strip()
    path = Path(ref).expanduser()
    if not path.is_absolute():
        candidate = (content_root / ref).resolve()
        if candidate.is_file():
            return candidate
    if path.is_file():
        return path.resolve()
    raise MiniMaxMediaError(f"file not found: {path_ref}")


def _read_audio_bytes(path_ref: str, *, content_root: Path) -> tuple[bytes, str]:
    """Read audio bytes and infer filename from a path reference.

    Args:
        path_ref (str): Workspace-relative or absolute audio path.
        content_root (Path): Workspace content root.

    Returns:
        tuple[bytes, str]: ``(bytes, filename)``.

    Raises:
        MiniMaxMediaError: When the file is missing or has an unsupported extension.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_read_audio_bytes)
        True
    """
    path = _resolve_local_file(path_ref, content_root=content_root)
    if path.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise MiniMaxMediaError(
            f"unsupported audio format {path.suffix!r} — use mp3, m4a, or wav",
        )
    return path.read_bytes(), path.name


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
    ext = {
        "image": "jpg",
        "image_i2i": "jpg",
        "video": "mp4",
        "video_i2v": "mp4",
        "video_s2v": "mp4",
        "video_fl2v": "mp4",
        "video_template": "mp4",
        "music": "mp3",
        "voice": "mp3",
    }[kind]
    return f"media-{kind}-{stem}.{ext}"


def _new_voice_id() -> str:
    """Generate a MiniMax-compatible custom voice id.

    Returns:
        str: Voice id starting with a letter, 8+ chars.

    Examples:
        >>> vid = _new_voice_id()
        >>> vid[0].isalpha() and len(vid) >= 8
        True
    """
    return f"SevnVoice{uuid.uuid4().hex[:12]}"


def _augment_task(
    kind: str,
    media_task: MediaTask,
    *,
    prompt_override: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Augment prompt with task template and structured variables.

    Args:
        kind (str): Media prompt family passed to :func:`augment_prompt`.
        media_task (MediaTask): Parsed task with template key and vars.
        prompt_override (str | None, optional): Replace ``media_task.prompt`` when set.

    Returns:
        tuple[str, str, dict[str, str]]: ``(template_key, augmented_prompt, format_context)``.

    Examples:
        >>> from sevn.agent.subagents.media_worker import MediaTask, _augment_task
        >>> key, text, ctx = _augment_task("image", MediaTask(kind="image", prompt="fox"))
        >>> key == "default" and "fox" in text
        True
    """
    prompt = (prompt_override or media_task.prompt).strip()
    template_key, augmented, ctx = augment_prompt(
        kind,  # type: ignore[arg-type]
        prompt,
        template_key=media_task.template_key,
        vars=media_task.prompt_vars,
    )
    return template_key, augmented, ctx


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

    Every kind augments the short ``prompt`` with templates before calling MiniMax.
    Results include a ``trace`` block for observability.

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
        dict[str, object]: ``artifact_path``, ``kind``, ``bytes``, ``trace`` metadata.

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

    trace_extra: dict[str, object] = {}
    api_model: str | None = None
    format_ctx: dict[str, str] = {}
    voice_id: str | None = None
    data: bytes
    template_key = "default"
    augmented = media_task.prompt

    if media_task.kind == "image":
        template_key, augmented, format_ctx = _augment_task("image", media_task)
        api_model = DEFAULT_IMAGE_MODEL
        data = await generate_image_bytes(
            api_key,
            augmented,
            aspect_ratio=media_task.aspect_ratio,
            client=http_client,
        )
    elif media_task.kind == "image_i2i":
        if not media_task.reference_image:
            raise MiniMaxMediaError("image_i2i requires reference_image")
        template_key, augmented, format_ctx = _augment_task("image_i2i", media_task)
        api_model = DEFAULT_IMAGE_MODEL
        data = await generate_image_from_reference_bytes(
            api_key,
            augmented,
            media_task.reference_image,
            aspect_ratio=media_task.aspect_ratio,
            content_root=content_root,
            client=http_client,
        )
        trace_extra["reference_image"] = media_task.reference_image
    elif media_task.kind == "video":
        prompt_kind = "video_i2v" if media_task.first_frame_image else "video"
        template_key, augmented, format_ctx = _augment_task(prompt_kind, media_task)
        api_model = DEFAULT_VIDEO_MODEL
        data = await generate_video_bytes(
            api_key,
            augmented,
            duration=media_task.duration,
            resolution=media_task.resolution,
            first_frame_image=media_task.first_frame_image,
            content_root=content_root,
            poll_interval_s=poll_interval,
            max_polls=poll_cap,
            client=http_client,
        )
        if media_task.first_frame_image:
            trace_extra["first_frame_image"] = media_task.first_frame_image
    elif media_task.kind == "video_i2v":
        if not media_task.first_frame_image:
            raise MiniMaxMediaError("video_i2v requires first_frame_image")
        template_key, augmented, format_ctx = _augment_task("video_i2v", media_task)
        api_model = DEFAULT_VIDEO_I2V_MODEL
        data = await generate_video_from_image_bytes(
            api_key,
            augmented,
            media_task.first_frame_image,
            duration=media_task.duration,
            resolution=media_task.resolution,
            content_root=content_root,
            poll_interval_s=poll_interval,
            max_polls=poll_cap,
            client=http_client,
        )
        trace_extra["first_frame_image"] = media_task.first_frame_image
    elif media_task.kind == "video_s2v":
        ref = media_task.subject_reference or media_task.reference_image
        if not ref:
            raise MiniMaxMediaError("video_s2v requires subject_reference")
        template_key, augmented, format_ctx = _augment_task("video_s2v", media_task)
        api_model = DEFAULT_VIDEO_S2V_MODEL
        data = await generate_video_subject_reference_bytes(
            api_key,
            augmented,
            ref,
            content_root=content_root,
            poll_interval_s=poll_interval,
            max_polls=poll_cap,
            client=http_client,
        )
        trace_extra["subject_reference"] = ref
    elif media_task.kind == "video_fl2v":
        if not media_task.first_frame_image or not media_task.last_frame_image:
            raise MiniMaxMediaError("video_fl2v requires first_frame_image and last_frame_image")
        template_key, augmented, format_ctx = _augment_task("video_fl2v", media_task)
        api_model = DEFAULT_VIDEO_FL2V_MODEL
        data = await generate_video_first_last_frame_bytes(
            api_key,
            augmented,
            first_frame_image=media_task.first_frame_image,
            last_frame_image=media_task.last_frame_image,
            duration=media_task.duration,
            resolution=media_task.resolution,
            content_root=content_root,
            poll_interval_s=poll_interval,
            max_polls=poll_cap,
            client=http_client,
        )
        trace_extra["first_frame_image"] = media_task.first_frame_image
        trace_extra["last_frame_image"] = media_task.last_frame_image
    elif media_task.kind == "video_template":
        if not media_task.template_id:
            raise MiniMaxMediaError("video_template requires template_id or template_slug")
        catalog_entry = resolve_video_agent_template(media_task.template_id)
        template_key = media_task.template_key or "default"
        augmented = media_task.prompt or catalog_entry.description
        format_ctx = {"user_request": augmented}
        text_inputs = list(media_task.text_inputs)
        if media_task.prompt and not text_inputs and catalog_entry.text_inputs_required:
            text_inputs = [media_task.prompt]
        api_model = f"video_agent:{catalog_entry.template_id}"
        data = await generate_video_template_bytes(
            api_key,
            catalog_entry.template_id,
            text_inputs=text_inputs or None,
            media_inputs=list(media_task.media_inputs) or None,
            content_root=content_root,
            poll_interval_s=poll_interval,
            max_polls=poll_cap,
            client=http_client,
        )
        trace_extra["video_template"] = {
            "template_id": catalog_entry.template_id,
            "slug": catalog_entry.slug,
            "name": catalog_entry.name,
        }
    elif media_task.kind == "music":
        template_key, augmented, format_ctx = _augment_task("music", media_task)
        api_model = DEFAULT_MUSIC_MODEL
        data = await generate_music_bytes(
            api_key,
            augmented,
            lyrics=media_task.lyrics,
            is_instrumental=media_task.is_instrumental,
            client=http_client,
        )
    else:
        template_key, augmented, format_ctx = _augment_task("voice", media_task)
        api_model = DEFAULT_SPEECH_MODEL
        voice_id = media_task.voice_id
        cloned_voice_id: str | None = None

        if media_task.source_audio:
            source_bytes, source_name = _read_audio_bytes(
                media_task.source_audio,
                content_root=content_root,
            )
            assigned_voice = voice_id or _new_voice_id()
            prompt_audio_bytes: bytes | None = None
            prompt_name = "prompt_sample.mp3"
            if media_task.prompt_audio:
                prompt_audio_bytes, prompt_name = _read_audio_bytes(
                    media_task.prompt_audio,
                    content_root=content_root,
                )
            preview = media_task.preview_text or media_task.speech_text or augmented
            cloned_voice_id, preview_bytes = await clone_voice_bytes(
                api_key,
                source_bytes,
                voice_id=assigned_voice,
                source_filename=source_name,
                preview_text=preview,
                prompt_audio=prompt_audio_bytes,
                prompt_text=media_task.prompt_text,
                prompt_filename=prompt_name,
                client=http_client,
            )
            voice_id = cloned_voice_id
            trace_extra["cloned_voice_id"] = cloned_voice_id
            trace_extra["source_audio"] = media_task.source_audio
            if preview_bytes is not None:
                data = preview_bytes
            elif media_task.speech_text and voice_id:
                _, speech_aug, _ = _augment_task(
                    "voice", media_task, prompt_override=media_task.speech_text
                )
                data = await synthesize_speech_bytes(
                    api_key,
                    speech_aug,
                    voice_id=voice_id,
                    client=http_client,
                )
            else:
                raise MiniMaxMediaError(
                    "voice clone succeeded but no preview audio — set preview_text or speech_text",
                )
        elif voice_id and media_task.speech_text:
            speech_key, speech_augmented, speech_ctx = _augment_task(
                "voice",
                media_task,
                prompt_override=media_task.speech_text,
            )
            trace_extra["speech_template_key"] = speech_key
            trace_extra["speech_augmented_prompt"] = speech_augmented
            trace_extra["speech_variables"] = speech_ctx
            data = await synthesize_speech_bytes(
                api_key,
                speech_augmented,
                voice_id=voice_id,
                client=http_client,
            )
            trace_extra["voice_id"] = voice_id
        else:
            raise MiniMaxMediaError(
                "voice requires source_audio (clone) or voice_id + speech_text (TTS)",
            )

    filename = _safe_filename(
        media_task.kind, media_task.prompt or media_task.template_id or "media"
    )
    rel_path = await _persist_bytes(
        conn=conn,
        content_root=content_root,
        session_id=session_id,
        filename=filename,
        data=data,
    )
    trace = build_media_trace(
        kind=media_task.kind,
        user_request=media_task.prompt,
        augmented_prompt=augmented,
        template_key=template_key,
        api_model=api_model,
        variables=format_ctx,
        extra=trace_extra or None,
    )
    result: dict[str, object] = {
        "artifact_path": rel_path,
        "kind": media_task.kind,
        "bytes": len(data),
        "specialist": MEDIA_GENERATOR_SPECIALIST,
        "model": specialist.model,
        "provider": specialist.provider,
        "trace": trace,
    }
    if media_task.kind == "voice" and voice_id:
        result["voice_id"] = voice_id
    return result


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
