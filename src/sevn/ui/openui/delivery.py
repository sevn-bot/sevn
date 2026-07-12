"""Map :class:`OpenUIRenderResult` to channel outbound metadata (`specs/29-openui.md` §4.5).

Module: sevn.ui.openui.delivery
Depends: sevn.ui.openui.models

Exports:
    build_openui_delivery_metadata — ``OutgoingMessage.metadata`` keys per channel.
    build_telegram_openui_inline_keyboard — cover-message keyboard for live URLs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sevn.ui.openui.models import OpenUIRenderResult


def build_telegram_openui_inline_keyboard(live_url: str) -> dict[str, Any]:
    """Build the locked two-button inline keyboard (`prd/10-generated-ui.md` §5.6).

    Args:
        live_url (str): Absolute or site-relative ``GET /openui/<token>`` URL.

    Returns:
        dict[str, Any]: Telegram ``reply_markup`` inline keyboard payload.

    Examples:
        >>> kb = build_telegram_openui_inline_keyboard("https://gw.example/openui/tok")
        >>> kb["inline_keyboard"][0][0]["text"]
        '🪟 Open here'
    """

    url = live_url.strip()
    return {
        "inline_keyboard": [
            [
                {"text": "🪟 Open here", "web_app": {"url": url}},
                {"text": "🌐 Open in browser", "url": url},
            ]
        ]
    }


def build_openui_delivery_metadata(
    result: OpenUIRenderResult,
    *,
    channel: str,
    title: str | None = None,
    safe_origin: str = "",
) -> dict[str, Any]:
    """Translate a bridge result into adapter routing metadata.

    Webchat prefers ``openui_iframe_src`` (live iframe). Telegram uses live
    cover + inline keyboard when ``live_url`` is set; otherwise raster paths
    for WeasyPrint PNG/PDF fallbacks (`specs/29-openui.md` §4.5).

    Args:
        result (OpenUIRenderResult): Successful or partial bridge output.
        channel (str): Active delivery channel (``webchat``, ``telegram``, …).
        title (str | None): Optional cover title for Telegram / iframe chrome.
        safe_origin (str): Gateway origin hint for webchat sandbox (optional).

    Returns:
        dict[str, Any]: Keys merged into :class:`~sevn.gateway.channel_router.OutgoingMessage.metadata`.

    Examples:
        >>> from sevn.ui.openui.models import OpenUIRenderResult
        >>> md = build_openui_delivery_metadata(
        ...     OpenUIRenderResult(live_url="/openui/tok", fallback_text="fb"),
        ...     channel="webchat",
        ... )
        >>> md["openui_iframe_src"]
        '/openui/tok'
    """

    meta: dict[str, Any] = {}
    cover = (title or "").strip() or "Open form"
    if safe_origin.strip():
        meta["openui_safe_origin"] = safe_origin.strip()
    if cover:
        meta["openui_title"] = cover

    if result.error is not None:
        meta["openui_fallback_only"] = True
        return meta

    ch = channel.strip().lower()
    if ch == "webchat":
        if result.live_url:
            meta["openui_iframe_src"] = result.live_url
        return meta

    if ch == "telegram":
        if result.live_url:
            meta["openui_live_url"] = result.live_url
            meta["inline_keyboard"] = build_telegram_openui_inline_keyboard(result.live_url)
        if result.image_path:
            meta["openui_image_path"] = result.image_path
        if result.pdf_path:
            meta["openui_pdf_path"] = result.pdf_path
        return meta

    if result.live_url:
        meta["openui_live_url"] = result.live_url
    if result.image_path:
        meta["openui_image_path"] = result.image_path
    if result.pdf_path:
        meta["openui_pdf_path"] = result.pdf_path
    return meta


__all__ = ["build_openui_delivery_metadata", "build_telegram_openui_inline_keyboard"]
