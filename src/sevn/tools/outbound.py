"""Outbound messaging and media tools (`plan/tools-skills-full-inventory-wave-plan.md` Wave 6).

``message`` routes proactive text via :meth:`ChannelRouter.route_outgoing`.
``send_file`` attaches a workspace file on the outbound envelope metadata.
``tts`` synthesizes audio through the gateway TTS pipeline and delivers it.

Module: sevn.tools.outbound
Depends: mimetypes, sevn.gateway.channel_router, sevn.tools.base, sevn.tools.context,
    sevn.tools.decorator, sevn.tools.paths

Exports:
    message_tool — proactive outbound text via ``route_outgoing``.
    send_file_tool — attach a workspace file for channel delivery.
    tts_tool — synthesize speech and route audio to the active channel.
    register_outbound_tools — register the three tools on a ``ToolExecutor``.

Examples:
    >>> from sevn.tools.outbound import register_outbound_tools
    >>> from sevn.tools.base import ToolExecutor
    >>> exe = ToolExecutor()
    >>> register_outbound_tools(exe)
    >>> "message" in {d.name for d in exe.definitions()}
    True
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.channels.telegram import TelegramSendError
from sevn.gateway.channel_router import OutgoingMessage
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.tools.paths import resolve_workspace_relative_path

if TYPE_CHECKING:
    from sevn.tools.base import ToolExecutor

_PHOTO_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".mov", ".webm", ".mkv"})
_AUDIO_EXTENSIONS: frozenset[str] = frozenset({".mp3", ".ogg", ".wav", ".m4a", ".opus"})
_OUTBOUND_TOOLS: tuple[Any, ...] = ()


def _attachment_kind(path: Path) -> str:
    """Classify a file for channel-native send method selection.

    Args:
        path (Path): Resolved attachment path.

    Returns:
        str: One of ``photo``, ``video``, ``audio``, or ``document``.

    Examples:
        >>> from pathlib import Path
        >>> _attachment_kind(Path("shot.png"))
        'photo'
        >>> _attachment_kind(Path("notes.txt"))
        'document'
    """
    ext = path.suffix.casefold()
    if ext in _PHOTO_EXTENSIONS:
        return "photo"
    if ext in _VIDEO_EXTENSIONS:
        return "video"
    if ext in _AUDIO_EXTENSIONS:
        return "audio"
    return "document"


def _guess_mime(path: Path) -> str:
    """Return a MIME type for ``path`` when known.

    Args:
        path (Path): Resolved attachment path.

    Returns:
        str: Guessed MIME type or ``application/octet-stream``.

    Examples:
        >>> from pathlib import Path
        >>> _guess_mime(Path("readme.txt")).startswith("text/")
        True
    """
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


async def _route_outbound(
    ctx: ToolContext,
    *,
    channel: str | None,
    user_id: str | None,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Deliver one outbound envelope through the gateway router when wired.

    Args:
        ctx (ToolContext): Invocation context with ``channel_router`` + routing hints.
        channel (str | None): Target channel key; defaults to ``ctx.delivery_channel``.
        user_id (str | None): Destination user id; defaults to ``ctx.outbound_user_id``.
        text (str): Outbound body or caption text.
        metadata (dict[str, Any] | None): Adapter-specific metadata merged atop routing hints.

    Returns:
        str | None: §3.1 failure envelope JSON when routing is unavailable; ``None`` on success.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_route_outbound)
        True
    """
    router = ctx.channel_router
    if router is None:
        return enveloped_failure(
            "outbound routing is unavailable (gateway channel_router not wired)",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    target_channel = (channel or ctx.delivery_channel or "").strip()
    target_user = (user_id or ctx.outbound_user_id or "").strip()
    if not target_channel:
        return enveloped_failure(
            "channel is required for proactive outbound delivery",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    if not target_user:
        return enveloped_failure(
            "user_id is required for proactive outbound delivery",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    meta = dict(ctx.outbound_metadata)
    if metadata:
        meta.update(metadata)
    try:
        await router.route_outgoing(
            OutgoingMessage(
                channel=target_channel,
                user_id=target_user,
                text=text,
                session_id=ctx.session_id,
                metadata=meta,
            ),
        )
    except Exception as exc:
        if isinstance(exc, TelegramSendError):
            return enveloped_failure(
                exc.description,
                code=ToolResultCode.INTERNAL_ERROR,
            )
        raise
    return None


@sevn_tool(
    name="message",
    category="outbound",
    description="Send a proactive text message on the active or specified channel.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Message body to deliver."},
            "channel": {
                "type": "string",
                "description": "Optional channel key (defaults to active session channel).",
            },
            "user_id": {
                "type": "string",
                "description": "Optional destination user id (defaults to session user).",
            },
        },
        "required": ["text"],
    },
    abortable=True,
)
async def message_tool(
    ctx: ToolContext,
    *,
    text: str,
    channel: str | None = None,
    user_id: str | None = None,
) -> str:
    """Route proactive text through :meth:`ChannelRouter.route_outgoing`.

    Args:
        ctx (ToolContext): Invocation context (``channel_router``, routing metadata).
        text (str): Message body.
        channel (str | None): Optional override channel key.
        user_id (str | None): Optional override destination user id.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(message_tool)
        True
    """
    body = text.strip()
    if not body:
        return enveloped_failure("text must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    err = await _route_outbound(ctx, channel=channel, user_id=user_id, text=body)
    if err is not None:
        return err
    return enveloped_success(
        {
            "channel": (channel or ctx.delivery_channel or "").strip(),
            "user_id": (user_id or ctx.outbound_user_id or "").strip(),
            "text_length": len(body),
        },
    )


@sevn_tool(
    name="send_file",
    category="outbound",
    description="Send a workspace file to the user on their active channel.",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative path to the file to send.",
            },
            "filename": {
                "type": "string",
                "description": "Optional display filename for the attachment.",
            },
            "caption": {
                "type": "string",
                "description": "Optional caption shown with the attachment.",
            },
        },
        "required": ["path"],
    },
    abortable=False,
)
async def send_file_tool(
    ctx: ToolContext,
    *,
    path: str,
    filename: str | None = None,
    caption: str | None = None,
) -> str:
    """Attach a workspace file on an outbound envelope for channel delivery.

    Args:
        ctx (ToolContext): Invocation context (``channel_router``, routing metadata).
        path (str): Workspace-relative file path.
        filename (str | None): Optional display filename override.
        caption (str | None): Optional caption text.

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(send_file_tool)
        True
    """
    rel = path.strip()
    if not rel:
        return enveloped_failure("path must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    try:
        prefix = ctx.artifact_output_prefix.strip()
        if prefix:
            from sevn.tools.paths import resolve_artifact_tool_path

            resolved, rel = resolve_artifact_tool_path(
                ctx.workspace_path,
                rel,
                output_prefix=prefix,
                allow_existing_outside=True,
            )
        else:
            resolved = resolve_workspace_relative_path(ctx.workspace_path, rel)
    except (OSError, PermissionError, ValueError) as exc:
        return enveloped_failure(str(exc), code=ToolResultCode.PERMISSION_DENIED)
    if not resolved.is_file():
        return enveloped_failure(
            f"path is not a file: {rel}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    display_name = (filename or resolved.name).strip() or resolved.name
    attachment_meta = {
        "attachment_path": str(resolved),
        "attachment_filename": display_name,
        "attachment_mime": _guess_mime(resolved),
        "attachment_kind": _attachment_kind(resolved),
    }
    err = await _route_outbound(
        ctx,
        channel=None,
        user_id=None,
        text=(caption or "").strip(),
        metadata=attachment_meta,
    )
    if err is not None:
        return err
    return enveloped_success(
        {
            "path": rel,
            "filename": display_name,
            "attachment_kind": attachment_meta["attachment_kind"],
            "bytes": resolved.stat().st_size,
        },
    )


@sevn_tool(
    name="tts",
    category="outbound",
    description="Convert text to speech and deliver audio on the active channel.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to synthesize."},
            "voice": {
                "type": "string",
                "description": "Optional provider voice id override.",
            },
            "speed": {
                "type": "number",
                "description": "Optional playback speed hint (reserved; providers may ignore).",
            },
        },
        "required": ["text"],
    },
    abortable=True,
    # Kokoro cold-start needs >30s; cap below Kokoro's internal 600s subprocess budget so a
    # wedged synth cannot block tier-B for the full 10 minutes.
    dispatch_timeout_seconds=180.0,
)
async def tts_tool(
    ctx: ToolContext,
    *,
    text: str,
    voice: str | None = None,
    speed: float | None = None,
) -> str:
    """Synthesize speech via the gateway TTS pipeline and route audio outbound.

    Args:
        ctx (ToolContext): Invocation context (``tts_pipeline``, ``channel_router``).
        text (str): Text to synthesize.
        voice (str | None): Optional voice id override.
        speed (float | None): Reserved speed hint (ignored when unsupported).

    Returns:
        str: §3.1 JSON envelope string.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(tts_tool)
        True
    """
    _ = speed
    body = text.strip()
    if not body:
        return enveloped_failure("text must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    pipeline = ctx.tts_pipeline
    if pipeline is None:
        return enveloped_failure(
            "TTS pipeline is unavailable (gateway voice factory not wired)",
            code=ToolResultCode.INTERNAL_ERROR,
        )
    voice_id = (voice or ctx.voice_tts_voice_id or "").strip() or None
    synth = await pipeline.synthesize_or_skip(
        cleaned_assistant_text=body,
        voice_id=voice_id,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
    )
    if synth.result is None:
        detail = synth.exhaustion_detail
        message = (
            f"TTS synthesis failed: {detail}"
            if detail
            else "TTS synthesis failed or produced empty audio"
        )
        return enveloped_failure(message, code=ToolResultCode.INTERNAL_ERROR)
    err = await _route_outbound(
        ctx,
        channel=None,
        user_id=None,
        text="",
        metadata={"tts_audio_path": str(synth.result.path)},
    )
    if err is not None:
        return err
    return enveloped_success(
        {
            "audio_path": str(synth.result.path),
            "provider": synth.result.provider,
            "mime_type": synth.result.mime_type,
            "text_length": len(body),
        },
    )


_OUTBOUND_TOOLS = (
    message_tool,
    send_file_tool,
    tts_tool,
)


def register_outbound_tools(executor: ToolExecutor) -> None:
    """Register Wave 6 outbound messaging and media tools.

    Args:
        executor (ToolExecutor): Registry under construction.

    Returns:
        None

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.outbound import register_outbound_tools
        >>> exe = ToolExecutor()
        >>> register_outbound_tools(exe)
        >>> {"message", "send_file", "tts"} <= {d.name for d in exe.definitions()}
        True
    """
    for tool_fn in _OUTBOUND_TOOLS:
        executor.register(tool_from_decorated(tool_fn))


__all__ = [
    "message_tool",
    "register_outbound_tools",
    "send_file_tool",
    "tts_tool",
]
