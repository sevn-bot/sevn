"""Telegram Mini App rich artifact viewer helpers (`specs/19-channel-webui.md` §2.5).

Module: sevn.gateway.webapp.webapp_viewer
Depends: json, re, secrets, sqlite3, time, typing, sevn.config.defaults,
    sevn.gateway.dispatcher.dispatcher_state, sevn.gateway.webapp.webapp_qa

Exports:
    mint_webapp_viewer_token — dispatcher token for viewer payload handoff.
    load_webapp_viewer_payload — fetch non-consumed viewer token payload.
    register_viewer_stream — seed in-memory stream buffer for SSE/poll.
    append_viewer_stream_chunk — append one chunk to a stream buffer.
    mark_viewer_stream_done — mark stream complete.
    viewer_stream_snapshot — poll/SSE payload slice from a stream buffer.
    evict_stale_viewer_streams — drop stream buffers past TTL (1800s, max 256 entries).
    webapp_viewer_launch_allowed — HTTPS + config gate for viewer launch.
    webapp_share_to_story_enabled — config gate for ``shareToStory`` (D13).
    build_viewer_webapp_url — HTTPS viewer shell URL with dispatcher token.
    infer_viewer_payload_from_markdown — map Markdown to viewer view + data.
    build_viewer_web_app_button — one ``web_app`` inline button when allowed.
    attach_inline_viewer_launch_buttons — I3 artifact rows + Open viewer button.
    cast_viewer_kind — validate viewer layout name strings.
    build_chat_menu_webapp_request — ``setChatMenuButton`` body for viewer launch (M2).
    sync_telegram_chat_menu_button — push or clear chat menu Web App button (D12).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from sevn.gateway.dispatcher.dispatcher_state import (
    dispatcher_state_ttl_for_kind,
    insert_dispatcher_state,
)
from sevn.gateway.webapp.webapp_qa import (
    load_webapp_dispatcher_payload,
    resolve_webapp_public_base,
    webapp_inline_buttons_allowed,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

ViewerViewKind = Literal["slideshow", "gallery", "table", "stream"]
WebappViewerKind = Literal["webapp_viewer"]


@dataclass
class _ViewerStreamState:
    """In-memory stream chunks keyed by ``stream_id``."""

    chunks: list[str] = field(default_factory=list)
    done: bool = False
    created_at: float = 0.0


VIEWER_STREAM_MAX_ENTRIES = 256
VIEWER_STREAM_TTL_SECONDS = 1800.0

_VIEWER_STREAMS: dict[str, _ViewerStreamState] = {}
_MENU_VIEWER_PAYLOADS: dict[str, dict[str, Any]] = {}

_MARKDOWN_REGION_EXPORTS = frozenset(
    {
        "_SLIDESHOW_BLOCK_RE",
        "_COLLAGE_BLOCK_RE",
        "_MEDIA_IMAGE_RE",
        "_parse_markdown_table",
    },
)


def _shared_markdown_regions() -> Any:
    """Return the shared Markdown region parser module.

    Returns:
        Any: ``sevn.channels.telegram_markdown_regions`` module object.

    Examples:
        >>> _shared_markdown_regions().__name__
        'sevn.channels.telegram_markdown_regions'
    """
    from sevn.channels import telegram_markdown_regions as mod

    return mod


def __getattr__(name: str) -> Any:
    """Lazy-bind shared Markdown region helpers (avoids gateway↔channels import cycle).

    Args:
        name (str): Legacy private alias requested by tests or callers.

    Returns:
        Any: Bound regex or parser callable from ``telegram_markdown_regions``.

    Examples:
        >>> isinstance(__getattr__("_SLIDESHOW_BLOCK_RE").pattern, str)
        True
    """
    if name not in _MARKDOWN_REGION_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    _regions = _shared_markdown_regions()
    binding = {
        "_SLIDESHOW_BLOCK_RE": _regions.SLIDESHOW_BLOCK_RE,
        "_COLLAGE_BLOCK_RE": _regions.COLLAGE_BLOCK_RE,
        "_MEDIA_IMAGE_RE": _regions.MEDIA_IMAGE_RE,
        "_parse_markdown_table": _regions.parse_markdown_table,
    }
    value = binding[name]
    globals()[name] = value
    return value


def webapp_viewer_launch_allowed(workspace: WorkspaceConfig) -> bool:
    """Return whether the rich viewer Mini App may be launched.

    Args:
        workspace (WorkspaceConfig): Active workspace document.

    Returns:
        bool: ``True`` when viewer is enabled and public base is HTTPS.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> webapp_viewer_launch_allowed(WorkspaceConfig.minimal(workspace_root="."))
        False
    """
    channels = workspace.channels
    tg = channels.telegram if channels is not None else None
    webapp_cfg = tg.webapp if tg is not None else None
    if webapp_cfg is not None and not bool(webapp_cfg.viewer_enabled):
        return False
    return webapp_inline_buttons_allowed(resolve_webapp_public_base(workspace))


def webapp_share_to_story_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether the viewer may expose ``Telegram.WebApp.shareToStory`` (D13).

    Args:
        workspace (WorkspaceConfig): Active workspace document.

    Returns:
        bool: ``True`` when ``channels.telegram.webapp.share_to_story`` is enabled.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.config.sections.channels import (
        ...     ChannelsWorkspaceSectionConfig,
        ...     TelegramChannelConfig,
        ...     TelegramWebappConfig,
        ... )
        >>> ws = WorkspaceConfig(
        ...     schema_version=1,
        ...     workspace_root=".",
        ...     gateway={"token": "t"},
        ...     channels=ChannelsWorkspaceSectionConfig(
        ...         telegram=TelegramChannelConfig(
        ...             webapp=TelegramWebappConfig(viewer_enabled=True, share_to_story=False),
        ...         ),
        ...     ),
        ... )
        >>> webapp_share_to_story_enabled(ws)
        False
    """
    channels = workspace.channels
    tg = channels.telegram if channels is not None else None
    webapp_cfg = tg.webapp if tg is not None else None
    if webapp_cfg is None:
        return True
    return bool(webapp_cfg.share_to_story)


def build_viewer_webapp_url(public_base: str, token: str) -> str:
    """Build the HTTPS Mini App shell URL for one viewer dispatcher token.

    Args:
        public_base (str): Gateway public origin (``resolve_webapp_public_base``).
        token (str): Opaque ``webapp_viewer`` dispatcher token.

    Returns:
        str: Absolute viewer shell URL.

    Examples:
        >>> build_viewer_webapp_url("https://bot.example.com", "abc")
        'https://bot.example.com/webapp/viewer?token=abc'
    """
    base = public_base.rstrip("/")
    safe_tok = token.strip()
    return f"{base}/webapp/viewer?token={safe_tok}"


def _markdown_image_refs(text: str) -> list[tuple[str, str]]:
    """Return ``(alt, url)`` pairs from Markdown image lines in *text*.

    Args:
        text (str): Markdown source text.

    Returns:
        list[tuple[str, str]]: Parsed image references in document order.

    Examples:
        >>> _markdown_image_refs("![a](https://x.test/a.png)")
        [('a', 'https://x.test/a.png')]
    """
    return [
        (m.group(1), m.group(2).strip())
        for m in _shared_markdown_regions().MEDIA_IMAGE_RE.finditer(text)
    ]


def infer_viewer_payload_from_markdown(text: str) -> tuple[ViewerViewKind, dict[str, Any]] | None:
    """Infer viewer layout + payload from assistant Markdown (M2 launch helper).

    Args:
        text (str): Assistant reply or artifact body.

    Returns:
        tuple[ViewerViewKind, dict[str, Any]] | None: ``(view, view_data)`` when
        the content maps to slideshow, gallery, table, or stream layouts.

    Examples:
        >>> infer_viewer_payload_from_markdown("| A |\\n| - |\\n| 1 |") is not None
        True
        >>> infer_viewer_payload_from_markdown("plain hello") is None
        True
    """
    regions = _shared_markdown_regions()
    body = (text or "").strip()
    if not body:
        return None
    slideshow_match = regions.SLIDESHOW_BLOCK_RE.search(body)
    if slideshow_match is not None:
        refs = _markdown_image_refs(slideshow_match.group(1))
        if refs:
            slides = [{"url": url, "caption": alt} for alt, url in refs]
            return "slideshow", {"slides": slides}
    collage_match = regions.COLLAGE_BLOCK_RE.search(body)
    if collage_match is not None:
        refs = _markdown_image_refs(collage_match.group(1))
        if refs:
            return "gallery", {"images": [url for _alt, url in refs]}
    table_data = regions.parse_markdown_table(body)
    if table_data is not None:
        return "table", table_data
    refs = _markdown_image_refs(body)
    if len(refs) >= 2:
        return "gallery", {"images": [url for _alt, url in refs]}
    if len(refs) == 1:
        _alt, url = refs[0]
        return "slideshow", {"slides": [{"url": url, "caption": _alt}]}
    if len(body) >= 120:
        return "stream", {"chunks": [body], "done": True}
    return None


def build_viewer_web_app_button(
    conn: sqlite3.Connection,
    *,
    workspace: WorkspaceConfig,
    user_id: str,
    chat_id: int = 0,
    topic_id: int | None = None,
    gateway_message_id: int,
    platform_message_id: int = 0,
    view: ViewerViewKind,
    view_data: dict[str, Any],
    stream_id: str | None = None,
    label: str = "Open viewer",
) -> dict[str, Any] | None:
    """Build one Telegram ``web_app`` inline button for the rich viewer (M2.1).

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        workspace (WorkspaceConfig): Active workspace document.
        user_id (str): Operator user id for token binding.
        chat_id (int): Telegram chat id (``0`` when unknown).
        topic_id (int | None): Forum thread id when set.
        gateway_message_id (int): ``gateway_messages.id`` or inline surrogate id.
        platform_message_id (int): Telegram ``message_id`` when known.
        view (ViewerViewKind): Viewer layout discriminator.
        view_data (dict[str, Any]): Layout-specific JSON payload.
        stream_id (str | None): Stream key when ``view`` is ``stream``.
        label (str): Button label shown in Telegram.

    Returns:
        dict[str, Any] | None: ``{"text", "web_app": {"url"}}`` or ``None`` when gated off.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> btn = build_viewer_web_app_button(
        ...     c,
        ...     workspace=WorkspaceConfig.minimal(workspace_root="."),
        ...     user_id="1",
        ...     gateway_message_id=1,
        ...     view="table",
        ...     view_data={"headers": ["A"], "rows": [["1"]]},
        ... )
        >>> btn is None
        True
        >>> c.close()
    """
    if not webapp_viewer_launch_allowed(workspace):
        return None
    base = resolve_webapp_public_base(workspace)
    if not webapp_inline_buttons_allowed(base):
        return None
    token = mint_webapp_viewer_token(
        conn,
        workspace=workspace,
        user_id=user_id,
        chat_id=int(chat_id),
        topic_id=topic_id,
        gateway_message_id=int(gateway_message_id),
        platform_message_id=int(platform_message_id),
        view=view,
        view_data=view_data,
        stream_id=stream_id,
    )
    return {"text": label, "web_app": {"url": build_viewer_webapp_url(base, token)}}


def attach_inline_viewer_launch_buttons(
    results: list[dict[str, Any]],
    *,
    workspace: WorkspaceConfig,
    conn: sqlite3.Connection,
    user_id: str,
) -> list[dict[str, Any]]:
    """Attach ``Open viewer`` ``web_app`` buttons to artifact inline rows (M2.4).

    Args:
        results (list[dict[str, Any]]): Inline result dicts (may carry ``_viewer_spec``).
        workspace (WorkspaceConfig): Active workspace document.
        conn (sqlite3.Connection): Open gateway SQLite handle.
        user_id (str): Requesting Telegram user id.

    Returns:
        list[dict[str, Any]]: Rows with ``reply_markup`` when launch is allowed.

    Examples:
        >>> attach_inline_viewer_launch_buttons([], workspace=__import__(
        ...     "sevn.config.workspace_config",
        ...     fromlist=["WorkspaceConfig"],
        ... ).WorkspaceConfig.minimal(workspace_root="."), conn=__import__(
        ...     "sqlite3",
        ... ).connect(":memory:"), user_id="1")
        []
    """
    if not results or not webapp_viewer_launch_allowed(workspace):
        return results
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(results):
        patched = dict(row)
        spec = patched.pop("_viewer_spec", None)
        if not isinstance(spec, dict):
            out.append(patched)
            continue
        view_raw = spec.get("view")
        view_data = spec.get("view_data")
        if not isinstance(view_raw, str) or not isinstance(view_data, dict):
            out.append(patched)
            continue
        view = cast_viewer_kind(view_raw)
        if view is None:
            out.append(patched)
            continue
        btn = build_viewer_web_app_button(
            conn,
            workspace=workspace,
            user_id=user_id,
            gateway_message_id=-(idx + 1),
            view=view,
            view_data=view_data,
            stream_id=str(spec["stream_id"]) if isinstance(spec.get("stream_id"), str) else None,
        )
        if btn is not None:
            patched["reply_markup"] = {"inline_keyboard": [[btn]]}
        out.append(patched)
    return out


def cast_viewer_kind(raw: str) -> ViewerViewKind | None:
    """Return a typed viewer kind when *raw* is supported.

    Args:
        raw (str): Layout name from Markdown inference or inline metadata.

    Returns:
        ViewerViewKind | None: Supported kind or ``None``.

    Examples:
        >>> cast_viewer_kind("table")
        'table'
        >>> cast_viewer_kind("unknown") is None
        True
    """
    if raw in ("slideshow", "gallery", "table", "stream"):
        return raw  # type: ignore[return-value]
    return None


def _chat_menu_viewer_view_data() -> dict[str, Any]:
    """Return the static viewer payload for the chat-menu Web App entry point.

    Returns:
        dict[str, Any]: Empty gallery layout shown before a message-specific launch.

    Examples:
        >>> _chat_menu_viewer_view_data()["images"]
        []
    """
    return {"images": []}


def _mint_chat_menu_viewer_token(
    *,
    workspace: WorkspaceConfig,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Mint a ``webapp_viewer`` dispatcher token for the chat menu button.

    Args:
        workspace (WorkspaceConfig): Active workspace document (TTL overrides).
        conn (sqlite3.Connection | None): When set, persist in ``dispatcher_state``.

    Returns:
        str: URL-safe opaque token (never the legacy ``menu`` sentinel).

    Examples:
        >>> tok = _mint_chat_menu_viewer_token(
        ...     workspace=__import__(
        ...         "sevn.config.workspace_config",
        ...         fromlist=["WorkspaceConfig"],
        ...     ).WorkspaceConfig.minimal(workspace_root="."),
        ... )
        >>> tok != "menu" and len(tok) >= 8
        True
    """
    view_data = _chat_menu_viewer_view_data()
    if conn is not None:
        return mint_webapp_viewer_token(
            conn,
            workspace=workspace,
            user_id="",
            chat_id=0,
            topic_id=None,
            gateway_message_id=0,
            platform_message_id=0,
            view="gallery",
            view_data=view_data,
        )
    token = secrets.token_urlsafe(16)
    _MENU_VIEWER_PAYLOADS[token] = {
        "v": 1,
        "user_id": "",
        "gateway_message_id": 0,
        "platform_message_id": 0,
        "view": "gallery",
        "view_data": view_data,
        "stream_id": None,
    }
    return token


def build_chat_menu_webapp_request(
    workspace: WorkspaceConfig,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Build ``setChatMenuButton`` JSON for the rich artifact viewer (M2 / D12).

    Args:
        workspace (WorkspaceConfig): Active workspace document.
        conn (sqlite3.Connection | None): Optional SQLite handle to persist menu token.

    Returns:
        dict[str, Any]: Bot API body with ``MenuButtonWebApp`` or ``MenuButtonDefault``.

    Examples:
        >>> body = build_chat_menu_webapp_request(
        ...     __import__(
        ...         "sevn.config.workspace_config",
        ...         fromlist=["WorkspaceConfig"],
        ...     ).WorkspaceConfig.minimal(workspace_root="."),
        ... )
        >>> body["menu_button"]["type"]
        'default'
    """
    if not webapp_viewer_launch_allowed(workspace):
        return {"menu_button": {"type": "default"}}
    base = resolve_webapp_public_base(workspace)
    if not webapp_inline_buttons_allowed(base):
        return {"menu_button": {"type": "default"}}
    token = _mint_chat_menu_viewer_token(workspace=workspace, conn=conn)
    return {
        "menu_button": {
            "type": "web_app",
            "text": "Viewer",
            "web_app": {"url": build_viewer_webapp_url(base, token)},
        },
    }


async def sync_telegram_chat_menu_button(
    api_call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    workspace: WorkspaceConfig,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Push or reset the Telegram chat menu Web App button (D12).

    Args:
        api_call (Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]):
            Async Bot API caller ``(method, body) -> response``.
        workspace (WorkspaceConfig): Active workspace document.
        conn (sqlite3.Connection | None): Optional SQLite handle to persist menu token.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(sync_telegram_chat_menu_button)
        True
    """
    body = build_chat_menu_webapp_request(workspace, conn=conn)
    await api_call("setChatMenuButton", body)


def evict_stale_viewer_streams() -> None:
    """Remove stream buffers older than ``VIEWER_STREAM_TTL_SECONDS``.

    Examples:
        >>> evict_stale_viewer_streams()
    """
    now = time.time()
    stale = [
        stream_id
        for stream_id, state in _VIEWER_STREAMS.items()
        if now - state.created_at > VIEWER_STREAM_TTL_SECONDS
    ]
    for stream_id in stale:
        del _VIEWER_STREAMS[stream_id]


def _enforce_viewer_stream_bounds() -> None:
    """Evict expired streams and trim to ``VIEWER_STREAM_MAX_ENTRIES`` (oldest first).

    Examples:
        >>> _VIEWER_STREAMS.clear()
        >>> _enforce_viewer_stream_bounds()
    """
    evict_stale_viewer_streams()
    while len(_VIEWER_STREAMS) > VIEWER_STREAM_MAX_ENTRIES:
        oldest_id = min(_VIEWER_STREAMS.items(), key=lambda item: item[1].created_at)[0]
        del _VIEWER_STREAMS[oldest_id]


def register_viewer_stream(
    stream_id: str,
    *,
    chunks: list[str] | None = None,
    done: bool = False,
) -> None:
    """Seed or replace the in-memory buffer for ``stream_id``.

    Args:
        stream_id (str): Opaque stream key from viewer payload.
        chunks (list[str] | None): Initial text chunks.
        done (bool): When ``True``, stream is finalized.

    Examples:
        >>> register_viewer_stream("s1", chunks=["hello"], done=False)
        >>> snap = viewer_stream_snapshot("s1", offset=0)
        >>> snap["chunks"] == ["hello"]
        True
        >>> snap["done"] is False
        True
    """
    _VIEWER_STREAMS[stream_id] = _ViewerStreamState(
        chunks=list(chunks or []),
        done=bool(done),
        created_at=time.time(),
    )
    _enforce_viewer_stream_bounds()


def append_viewer_stream_chunk(stream_id: str, chunk: str) -> None:
    """Append one text chunk to an existing viewer stream buffer.

    Args:
        stream_id (str): Stream key.
        chunk (str): Text fragment to append.

    Examples:
        >>> register_viewer_stream("s2", chunks=["a"])
        >>> append_viewer_stream_chunk("s2", "b")
        >>> viewer_stream_snapshot("s2", offset=0)["chunks"]
        ['a', 'b']
    """
    state = _VIEWER_STREAMS.get(stream_id)
    if state is None:
        register_viewer_stream(stream_id, chunks=[chunk], done=False)
        return
    state.chunks.append(chunk)


def mark_viewer_stream_done(stream_id: str) -> None:
    """Mark a viewer stream as complete (no further chunks expected).

    Args:
        stream_id (str): Stream key.

    Examples:
        >>> register_viewer_stream("s3", chunks=["x"], done=False)
        >>> mark_viewer_stream_done("s3")
        >>> viewer_stream_snapshot("s3", offset=0)["done"]
        True
    """
    state = _VIEWER_STREAMS.get(stream_id)
    if state is None:
        register_viewer_stream(stream_id, chunks=[], done=True)
        return
    state.done = True


def viewer_stream_snapshot(stream_id: str, *, offset: int = 0) -> dict[str, Any]:
    """Return incremental stream chunks from ``offset`` for poll/SSE clients.

    Args:
        stream_id (str): Stream key.
        offset (int): Number of chunks already received by the client.

    Returns:
        dict[str, Any]: ``{"chunks": [...], "done": bool, "next_offset": int}``.

    Examples:
        >>> register_viewer_stream("s4", chunks=["one", "two"], done=True)
        >>> snap = viewer_stream_snapshot("s4", offset=1)
        >>> snap["chunks"] == ["two"] and snap["done"] is True
        True
    """
    state = _VIEWER_STREAMS.get(stream_id)
    if state is None:
        return {"chunks": [], "done": True, "next_offset": int(offset)}
    start = max(0, int(offset))
    new_chunks = state.chunks[start:]
    next_offset = start + len(new_chunks)
    return {"chunks": new_chunks, "done": state.done, "next_offset": next_offset}


def mint_webapp_viewer_token(
    conn: sqlite3.Connection,
    *,
    workspace: WorkspaceConfig | None,
    user_id: str,
    chat_id: int,
    topic_id: int | None,
    gateway_message_id: int,
    platform_message_id: int,
    view: ViewerViewKind,
    view_data: dict[str, Any],
    stream_id: str | None = None,
) -> str:
    """Insert a short-lived ``webapp_viewer`` dispatcher token.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        workspace (WorkspaceConfig | None): TTL overrides.
        user_id (str): Operator user id string.
        chat_id (int): Telegram chat id (``0`` when unknown).
        topic_id (int | None): Forum thread id when set.
        gateway_message_id (int): ``gateway_messages.id`` join key.
        platform_message_id (int): Telegram ``message_id``.
        view (ViewerViewKind): Layout discriminator.
        view_data (dict[str, Any]): View-specific JSON payload.
        stream_id (str | None): Stream key when ``view`` is ``stream``.

    Returns:
        str: URL-safe opaque token.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> tok = mint_webapp_viewer_token(
        ...     c,
        ...     workspace=None,
        ...     user_id="42",
        ...     chat_id=1,
        ...     topic_id=None,
        ...     gateway_message_id=5,
        ...     platform_message_id=9,
        ...     view="table",
        ...     view_data={"headers": ["A"], "rows": [["1"]]},
        ... )
        >>> len(tok) >= 8
        True
        >>> c.close()
    """
    token = secrets.token_urlsafe(16)
    sid = stream_id or secrets.token_urlsafe(8)
    if view == "stream":
        register_viewer_stream(
            sid,
            chunks=list(view_data.get("chunks") or []),
            done=bool(view_data.get("done")),
        )
    payload = json.dumps(
        {
            "v": 1,
            "user_id": user_id,
            "gateway_message_id": int(gateway_message_id),
            "platform_message_id": int(platform_message_id),
            "view": view,
            "view_data": view_data,
            "stream_id": sid if view == "stream" else None,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    uid_int = int(user_id) if user_id.isdigit() else 0
    insert_dispatcher_state(
        conn,
        token=token,
        kind="webapp_viewer",
        user_id=uid_int,
        chat_id=int(chat_id),
        topic_id=topic_id,
        payload_json=payload,
        ttl_seconds=dispatcher_state_ttl_for_kind("webapp_viewer", workspace),
        consumed=0,
    )
    return token


def load_webapp_viewer_payload(
    conn: sqlite3.Connection,
    *,
    token: str,
) -> dict[str, Any] | None:
    """Load a non-consumed ``webapp_viewer`` dispatcher token payload.

    Args:
        conn (sqlite3.Connection): Open ``sevn.db`` handle.
        token (str): Opaque token from the Web App URL.

    Returns:
        dict[str, Any] | None: Parsed payload or ``None`` when invalid.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> tok = mint_webapp_viewer_token(
        ...     c,
        ...     workspace=None,
        ...     user_id="u",
        ...     chat_id=1,
        ...     topic_id=None,
        ...     gateway_message_id=1,
        ...     platform_message_id=2,
        ...     view="gallery",
        ...     view_data={"images": []},
        ... )
        >>> load_webapp_viewer_payload(c, token=tok) is not None
        True
        >>> c.close()
    """
    cached = _MENU_VIEWER_PAYLOADS.get(token.strip())
    if cached is not None:
        return dict(cached)
    return load_webapp_dispatcher_payload(
        conn,
        token=token,
        expected_kind="webapp_viewer",
    )


__all__ = [
    "VIEWER_STREAM_MAX_ENTRIES",
    "VIEWER_STREAM_TTL_SECONDS",
    "ViewerViewKind",
    "append_viewer_stream_chunk",
    "attach_inline_viewer_launch_buttons",
    "build_chat_menu_webapp_request",
    "build_viewer_web_app_button",
    "build_viewer_webapp_url",
    "cast_viewer_kind",
    "evict_stale_viewer_streams",
    "infer_viewer_payload_from_markdown",
    "load_webapp_viewer_payload",
    "mark_viewer_stream_done",
    "mint_webapp_viewer_token",
    "register_viewer_stream",
    "sync_telegram_chat_menu_button",
    "viewer_stream_snapshot",
    "webapp_share_to_story_enabled",
    "webapp_viewer_launch_allowed",
]
