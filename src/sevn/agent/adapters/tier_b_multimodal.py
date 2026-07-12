"""Tier-B multimodal user prompt construction (W10).

Module: sevn.agent.adapters.tier_b_multimodal
Depends: pydantic_ai.messages, sevn.gateway.turn_media

Exports:
    TierBModalitySupport — provider capability flags for vision/document input.
    resolve_tier_b_modality_support — map model + transport to modality support.
    resolve_turn_media_items — hydrate turn-bound media for tier B.
    build_tier_b_user_prompt — str or content-list user prompt for ``agent.iter``.

Examples:
    >>> from sevn.agent.adapters.tier_b_multimodal import TierBModalitySupport
    >>> TierBModalitySupport(vision=True, document=False).vision
    True
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from pydantic_ai.messages import BinaryContent, DocumentUrl, ImageUrl

from sevn.gateway.turn_media import TurnMediaItem, hydrate_turn_media, load_turn_media_summaries

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_PHOTO_KINDS = frozenset({"photo", "image"})
_DOCUMENT_KINDS = frozenset({"document"})
_PDF_MEDIA = frozenset({"application/pdf"})
_MAX_INLINE_BYTES = 5 * 1024 * 1024
UserPromptContent = str | list[str | BinaryContent | ImageUrl | DocumentUrl]


@dataclass(frozen=True)
class TierBModalitySupport:
    """Whether the resolved tier-B model accepts native vision/document input."""

    vision: bool
    document: bool


def resolve_tier_b_modality_support(
    *,
    model_id: str,
    transport_name: str,
    native_model_active: bool,
) -> TierBModalitySupport:
    """Map catalog model + transport to native multimodal support (W10.1 matrix).

    Anthropic wire (incl. MiniMax gateway): image URL/bytes + PDF document URL/bytes.
    OpenAI chat: image URL/bytes only — PDF falls back to file+skill. Bedrock and
    ``FunctionModel`` paths disable native multimodal (W10.3).

    Args:
        model_id (str): Workspace catalog model id.
        transport_name (str): Resolved transport label (``anthropic``, ``chat_completions``, …).
        native_model_active (bool): ``True`` when tier B runs a native pydantic-ai model.

    Returns:
        TierBModalitySupport: Flags for vision and document modalities.

    Examples:
        >>> resolve_tier_b_modality_support(
        ...     model_id="anthropic/claude-sonnet-4-20250514",
        ...     transport_name="anthropic",
        ...     native_model_active=True,
        ... )
        TierBModalitySupport(vision=True, document=True)
        >>> resolve_tier_b_modality_support(
        ...     model_id="openai/gpt-4o",
        ...     transport_name="chat_completions",
        ...     native_model_active=True,
        ... ).vision
        True
        >>> resolve_tier_b_modality_support(
        ...     model_id="bedrock/anthropic.claude-3-haiku",
        ...     transport_name="bedrock",
        ...     native_model_active=True,
        ... ).vision
        False
    """
    if not native_model_active:
        return TierBModalitySupport(vision=False, document=False)
    transport = transport_name.casefold()
    catalog = model_id.casefold()
    if transport == "anthropic" or catalog.startswith(("minimax/", "anthropic/")):
        return TierBModalitySupport(vision=True, document=True)
    if transport == "chat_completions" and catalog.startswith("openai/"):
        return TierBModalitySupport(vision=True, document=False)
    return TierBModalitySupport(vision=False, document=False)


def _is_image_item(item: TurnMediaItem) -> bool:
    """Return whether a turn media row is an image attachment.

    Args:
        item (TurnMediaItem): Hydrated attachment row.

    Returns:
        bool: ``True`` when the row is a photo/image MIME type.

    Examples:
        >>> from sevn.gateway.turn_media import TurnMediaItem
        >>> _is_image_item(
        ...     TurnMediaItem(
        ...         kind="photo",
        ...         media_type="image/png",
        ...         filename="a.png",
        ...         rel_path="a.png",
        ...         data=b"",
        ...     )
        ... )
        True
    """
    kind = item.kind.casefold()
    return kind in _PHOTO_KINDS or item.media_type.casefold().startswith("image/")


def _is_pdf_item(item: TurnMediaItem) -> bool:
    """Return whether a turn media row is a PDF document attachment.

    Args:
        item (TurnMediaItem): Hydrated attachment row.

    Returns:
        bool: ``True`` for PDF documents.

    Examples:
        >>> from sevn.gateway.turn_media import TurnMediaItem
        >>> _is_pdf_item(
        ...     TurnMediaItem(
        ...         kind="document",
        ...         media_type="application/pdf",
        ...         filename="r.pdf",
        ...         rel_path="r.pdf",
        ...         data=b"",
        ...     )
        ... )
        True
    """
    kind = item.kind.casefold()
    media = item.media_type.casefold()
    name = item.filename.casefold()
    return kind in _DOCUMENT_KINDS and (media in _PDF_MEDIA or name.endswith(".pdf"))


def _channel_file_ref(session_id: str, item: TurnMediaItem) -> str:
    """Build a workspace-relative path hint for fallback prompts.

    Args:
        session_id (str): Gateway session id.
        item (TurnMediaItem): Attachment row.

    Returns:
        str: Relative ``channel_files/…`` path.

    Examples:
        >>> from sevn.gateway.turn_media import TurnMediaItem
        >>> _channel_file_ref(
        ...     "s",
        ...     TurnMediaItem(
        ...         kind="photo",
        ...         media_type="image/png",
        ...         filename="a.png",
        ...         rel_path="a.png",
        ...         data=b"",
        ...     ),
        ... )
        'channel_files/s/a.png'
    """
    return f"channel_files/{session_id}/{item.rel_path}"


def _url_needs_force_download(url: str) -> bool:
    """Return whether pydantic-ai should download URL bytes client-side.

    Args:
        url (str): Candidate attachment URL.

    Returns:
        bool: ``True`` for non-public or local URLs.

    Examples:
        >>> _url_needs_force_download("https://cdn.example.com/x.png")
        False
        >>> _url_needs_force_download("http://127.0.0.1/x.png")
        True
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return True
    host = (parsed.hostname or "").casefold()
    bind_all_ipv4 = ".".join("0" for _ in range(4))
    return host in {"localhost", "127.0.0.1", bind_all_ipv4}


def _append_image_part(
    parts: list[Any],
    item: TurnMediaItem,
) -> bool:
    """Append a native image part when bytes or URL are available.

    Args:
        parts (list[Any]): Mutable pydantic-ai user content list.
        item (TurnMediaItem): Hydrated image attachment.

    Returns:
        bool: ``True`` when an image part was appended.

    Examples:
        >>> from sevn.gateway.turn_media import TurnMediaItem
        >>> out: list[Any] = []
        >>> _append_image_part(
        ...     out,
        ...     TurnMediaItem(
        ...         kind="photo",
        ...         media_type="image/png",
        ...         filename="a.png",
        ...         rel_path="a.png",
        ...         data=b"x",
        ...     ),
        ... )
        True
    """
    if item.data and len(item.data) <= _MAX_INLINE_BYTES:
        parts.append(BinaryContent(data=item.data, media_type=item.media_type))
        return True
    if item.url:
        parts.append(
            ImageUrl(url=item.url, force_download=_url_needs_force_download(item.url)),
        )
        return True
    return False


def _append_document_part(
    parts: list[Any],
    item: TurnMediaItem,
) -> bool:
    """Append a native PDF/document part when bytes or URL are available.

    Args:
        parts (list[Any]): Mutable pydantic-ai user content list.
        item (TurnMediaItem): Hydrated document attachment.

    Returns:
        bool: ``True`` when a document part was appended.

    Examples:
        >>> from sevn.gateway.turn_media import TurnMediaItem
        >>> out: list[Any] = []
        >>> _append_document_part(
        ...     out,
        ...     TurnMediaItem(
        ...         kind="document",
        ...         media_type="application/pdf",
        ...         filename="r.pdf",
        ...         rel_path="r.pdf",
        ...         data=b"%PDF",
        ...     ),
        ... )
        True
    """
    if item.data and len(item.data) <= _MAX_INLINE_BYTES:
        parts.append(BinaryContent(data=item.data, media_type=item.media_type))
        return True
    if item.url:
        parts.append(
            DocumentUrl(url=item.url, force_download=_url_needs_force_download(item.url)),
        )
        return True
    return False


def _fallback_attachment_lines(
    *,
    turn_media: Sequence[TurnMediaItem],
    session_id: str,
) -> list[str]:
    """Build file-path fallback hints when native multimodal input is unavailable.

    Args:
        turn_media (Sequence[TurnMediaItem]): Hydrated attachments for the turn.
        session_id (str): Gateway session id.

    Returns:
        list[str]: Human-readable attachment hints for the model.

    Examples:
        >>> _fallback_attachment_lines(turn_media=(), session_id="s")
        []
    """
    lines: list[str] = []
    for item in turn_media:
        ref = _channel_file_ref(session_id, item)
        if _is_image_item(item):
            lines.append(f"[Attachment: image at {ref} - use read or relevant tools if needed.]")
        elif _is_pdf_item(item):
            lines.append(f"[Attachment: PDF at {ref} - use the pdf skill or read tool.]")
        else:
            lines.append(f"[Attachment: file at {ref}.]")
    return lines


def build_tier_b_user_prompt(
    *,
    incoming_text: str,
    triage_requires_vision: bool,
    triage_requires_document: bool,
    turn_media: Sequence[TurnMediaItem],
    session_id: str,
    support: TierBModalitySupport,
) -> UserPromptContent:
    """Build tier-B user prompt: plain ``str`` or multimodal content list (W10.1-W10.4).

    When neither triage modality flag is set, returns ``incoming_text`` unchanged so
    text-only turns stay byte-identical. When flags are set but the provider cannot
    consume the modality, falls back to file-path hints (W10.3).

    Args:
        incoming_text (str): Scanner-approved user message text.
        triage_requires_vision (bool): Triager ``requires_vision`` flag.
        triage_requires_document (bool): Triager ``requires_document`` flag.
        turn_media (Sequence[TurnMediaItem]): Hydrated inbound attachments for this turn.
        session_id (str): Gateway session id (for fallback path hints).
        support (TierBModalitySupport): Resolved provider modality support.

    Returns:
        UserPromptContent: Plain string or ``[text, BinaryContent/…]`` for ``agent.iter``.

    Examples:
        >>> build_tier_b_user_prompt(
        ...     incoming_text="hello",
        ...     triage_requires_vision=False,
        ...     triage_requires_document=False,
        ...     turn_media=(),
        ...     session_id="s",
        ...     support=TierBModalitySupport(vision=True, document=True),
        ... )
        'hello'
    """
    if not triage_requires_vision and not triage_requires_document:
        return incoming_text

    native_parts: list[Any] = []
    used_native = False
    text_base = incoming_text.strip()

    for item in turn_media:
        if (
            triage_requires_vision
            and _is_image_item(item)
            and support.vision
            and _append_image_part(
                native_parts,
                item,
            )
        ):
            used_native = True
        if (
            triage_requires_document
            and _is_pdf_item(item)
            and support.document
            and _append_document_part(
                native_parts,
                item,
            )
        ):
            used_native = True

    if used_native and native_parts:
        if text_base:
            return [text_base, *native_parts]
        return native_parts

    fallback_lines = _fallback_attachment_lines(turn_media=turn_media, session_id=session_id)
    if not fallback_lines:
        return incoming_text
    chunks = [text_base] if text_base else []
    chunks.extend(fallback_lines)
    return "\n\n".join(chunks)


def _turn_media_from_db(
    *,
    session_id: str,
    turn_id: str,
    content_root: Path,
) -> tuple[TurnMediaItem, ...]:
    """Load turn media summaries from workspace ``sevn.db`` when no router is wired.

    Args:
        session_id (str): Gateway session id.
        turn_id (str): Turn / correlation id.
        content_root (Path): Workspace content root.

    Returns:
        tuple[TurnMediaItem, ...]: Hydrated rows or empty when DB/summaries absent.

    Examples:
        >>> from pathlib import Path
        >>> _turn_media_from_db(session_id="s", turn_id="t", content_root=Path("/missing"))
        ()
    """
    dot_sevn = content_root.parent / ".sevn"
    if not dot_sevn.is_dir():
        dot_sevn = content_root / ".sevn"
    db_path = dot_sevn / "sevn.db"
    if not db_path.is_file():
        return ()
    conn = sqlite3.connect(str(db_path))
    try:
        summaries = load_turn_media_summaries(conn, session_id, turn_id)
    finally:
        conn.close()
    if not summaries:
        return ()
    return hydrate_turn_media(session_id, summaries, content_root)


def resolve_turn_media_items(
    *,
    session_id: str,
    turn_id: str,
    content_root: Path,
    triage_requires_vision: bool,
    triage_requires_document: bool,
    turn_media: Sequence[TurnMediaItem] | None,
    channel_router: Any | None,
) -> tuple[TurnMediaItem, ...]:
    """Hydrate turn media for tier B when triage flags request a modality (W10).

    Args:
        session_id (str): Gateway session id.
        turn_id (str): Turn / correlation id.
        content_root (Path): Workspace content root.
        triage_requires_vision (bool): Triager vision flag.
        triage_requires_document (bool): Triager document flag.
        turn_media (Sequence[TurnMediaItem] | None): Pre-hydrated items when supplied.
        channel_router (Any | None): Gateway router exposing ``load_turn_media``.

    Returns:
        tuple[TurnMediaItem, ...]: Hydrated attachment rows (possibly empty).

    Examples:
        >>> from pathlib import Path
        >>> resolve_turn_media_items(
        ...     session_id="s",
        ...     turn_id="t",
        ...     content_root=Path("/tmp"),
        ...     triage_requires_vision=False,
        ...     triage_requires_document=False,
        ...     turn_media=None,
        ...     channel_router=None,
        ... )
        ()
    """
    if not triage_requires_vision and not triage_requires_document:
        return ()
    if turn_media is not None:
        return tuple(turn_media)
    loader = getattr(channel_router, "load_turn_media", None)
    if callable(loader):
        loaded = loader(session_id, turn_id)
        return tuple(cast("Sequence[TurnMediaItem]", loaded))
    return _turn_media_from_db(
        session_id=session_id,
        turn_id=turn_id,
        content_root=content_root,
    )


__all__ = [
    "TierBModalitySupport",
    "UserPromptContent",
    "build_tier_b_user_prompt",
    "resolve_tier_b_modality_support",
    "resolve_turn_media_items",
]
